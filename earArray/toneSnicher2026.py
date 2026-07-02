#!/usr/bin/env python3
"""
MotionDeluxe (Refactor) — Wi-Fi CSI + Sound Direction (DOA)

(Updated to be run-ready)
- Adds missing mic selection globals (MIC_DEVICE / MIC_NOTE) and actually applies the chosen device.
- Makes root-check portable (Linux-only).
- Adds lightweight locking for CSI window to avoid race issues.
- Keeps DOA safe when sample-rate changes (HF band clamps to Nyquist).
"""

import sys, time, threading, asyncio, subprocess, os, csv, warnings, hashlib, json, socket, math, argparse, re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from threading import Lock

import numpy as np
import sounddevice as sd
from bleak import BleakScanner

# ======================
# MIC DISCOVERY / SELECTION
# ======================
def list_input_mics():
    """
    Returns a list of dicts for input-capable devices.
    Includes index, name, hostapi, max_input_channels, default_samplerate.
    """
    devs = sd.query_devices()
    hostapis = sd.query_hostapis()
    out = []
    for i, d in enumerate(devs):
        try:
            if int(d.get("max_input_channels", 0)) <= 0:
                continue
            ha = hostapis[int(d.get("hostapi", 0))]["name"] if hostapis else ""
            out.append({
                "index": i,
                "name": d.get("name", ""),
                "hostapi": ha,
                "max_input_channels": int(d.get("max_input_channels", 0)),
                "default_samplerate": float(d.get("default_samplerate", 0.0)) if d.get("default_samplerate") else 0.0,
            })
        except Exception:
            continue
    return out

def _device_supports(dev_index: int, fs: int, channels: int) -> bool:
    """Check if a device supports the requested samplerate/channels."""
    try:
        sd.check_input_settings(device=dev_index, samplerate=int(fs), channels=int(channels))
        return True
    except Exception:
        return False

def pick_mic_device(request: str, fs: int, channels: int):
    """
    Pick an input device index based on:
      - request == 'auto' (prefers UltraMic > Rode > anything that supports fs/ch)
      - request == 'default'
      - request is an integer index
      - request is a substring match against device name
    Returns: (device_index_or_None, resolved_fs, resolved_channels, note)
    """
    mics = list_input_mics()
    note = ""

    if not mics:
        return (None, fs, channels, "No input microphones found by sounddevice.")

    req = (request or "auto").strip()

    # Default device
    if req.lower() == "default":
        try:
            di = sd.default.device[0]  # input
            if di is None:
                raise RuntimeError("No default input device")
            return (int(di), fs, channels, "Using default input device.")
        except Exception:
            req = "auto"

    # Explicit index
    if re.fullmatch(r"\d+", req):
        di = int(req)
        return (di, fs, channels, f"Using requested device index {di}.")

    # Name substring match
    if req.lower() not in ("auto", "default"):
        matches = [m for m in mics if req.lower() in (m["name"] or "").lower()]
        if matches:
            matches.sort(key=lambda m: (not _device_supports(m["index"], fs, channels),
                                        -m["max_input_channels"],
                                        -m["default_samplerate"]))
            di = matches[0]["index"]
            return (di, fs, channels, f"Using device matched by name: {matches[0]['name']}")

    # AUTO PICK:
    # Prefer UltraMic384k / UltraMic / 384k, then Rode, then anything supporting requested fs/channels.
    def score(m):
        name = (m["name"] or "").lower()
        s = 0
        if "ultramic" in name or "384k" in name or "384000" in name:
            s += 1000
        if "rode" in name:
            s += 500
        s += min(m["max_input_channels"], 8) * 10
        s += 200 if _device_supports(m["index"], fs, channels) else 0
        s += int(min(m["default_samplerate"], 48000) / 1000)
        return s

    mics_sorted = sorted(mics, key=score, reverse=True)
    chosen = mics_sorted[0]
    di = chosen["index"]

    # Resolve channels
    if channels > chosen["max_input_channels"]:
        note += f"Requested {channels}ch but device has {chosen['max_input_channels']}ch; clamping. "
        channels = chosen["max_input_channels"]

    # Resolve fs
    if not _device_supports(di, fs, channels):
        tried = [fs, 48000, 44100, 32000, 24000, 16000, 8000]
        ok = None
        for r in tried:
            if _device_supports(di, r, channels):
                ok = r
                break
        if ok is not None and ok != fs:
            note += f"Device didn't support {fs}Hz; using {ok}Hz. "
            fs = ok
        else:
            dfs = int(round(chosen["default_samplerate"])) if chosen["default_samplerate"] else fs
            note += f"Device didn't support common rates; using default_samplerate {dfs}Hz. "
            fs = dfs

    note += f"Auto-picked mic: #{di} '{chosen['name']}' ({chosen['hostapi']})"
    return (di, fs, channels, note)

def print_mics():
    mics = list_input_mics()
    if not mics:
        print("No input microphones detected.")
        return
    print("Available input microphones (sounddevice):")
    for m in mics:
        print(f"  [{m['index']:>2}] {m['name']} | hostapi={m['hostapi']} | "
              f"inputs={m['max_input_channels']} | default_fs={m['default_samplerate']:.0f}")
    try:
        di = sd.default.device[0]
        print(f"\nDefault input device index: {di}")
    except Exception:
        pass

# ======================
# SAFETY (Linux)
# ======================
if hasattr(os, "geteuid"):
    if os.geteuid() == 0:
        print("❌ Do NOT run with sudo")
        sys.exit(1)

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning
)

# ======================
# CLI
# ======================
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--wifi-mode", choices=["udp", "file", "rssi"], default="udp",
                   help="Wi-Fi input: udp/file CSI, or rssi fallback via nmcli")
    p.add_argument("--csi-port", type=int, default=9999, help="UDP port to listen for CSI frames")
    p.add_argument("--csi-host", default="0.0.0.0", help="UDP bind address")
    p.add_argument("--csi-file", default="", help="Path to newline-delimited CSI frames (JSON/CSV)")
    p.add_argument("--csi-max-subcarriers", type=int, default=64, help="Max subcarriers to keep (truncate)")
    p.add_argument("--csi-win", type=int, default=120, help="CSI window size (frames) for motion features")

    p.add_argument("--audio-fs", type=int, default=16000)
    p.add_argument("--audio-device", default="auto",
                   help="Audio input device: auto|default|<index>|<name substring>. Use --list-mics to view.")
    p.add_argument("--list-mics", action="store_true", help="List available input microphones and exit")
    p.add_argument("--audio-window", type=float, default=0.10, help="Audio block size (seconds)")
    p.add_argument("--audio-channels", type=int, default=1, help="1=mono (no DOA), 2+=DOA enabled")
    p.add_argument("--mic-spacing-m", type=float, default=0.08, help="Distance between mic0 and mic1 (meters)")
    p.add_argument("--sound-speed", type=float, default=343.0, help="Speed of sound m/s (room temp)")

    p.add_argument("--gui-refresh-ms", type=int, default=500)
    return p.parse_args()

ARGS = parse_args()

# ======================
# MIC RESOLUTION (fixes missing MIC_DEVICE / MIC_NOTE)
# ======================
MIC_DEVICE = None
MIC_NOTE = ""
AUDIO_FS = int(ARGS.audio_fs)
AUDIO_WINDOW = float(ARGS.audio_window)
AUDIO_CHANNELS = int(max(1, ARGS.audio_channels))

if not getattr(ARGS, "list_mics", False):
    MIC_DEVICE, AUDIO_FS, AUDIO_CHANNELS, MIC_NOTE = pick_mic_device(
        ARGS.audio_device, AUDIO_FS, AUDIO_CHANNELS
    )

    # Apply device defaults (input only)
    try:
        cur_out = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else None
        sd.default.device = (MIC_DEVICE, cur_out)
    except Exception:
        pass
    try:
        sd.default.samplerate = AUDIO_FS
    except Exception:
        pass

AUDIO_SAMPLES = int(AUDIO_FS * AUDIO_WINDOW)

# ======================
# OUTPUT FILES (timestamped per run)
# ======================
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = Path("logs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = OUT_DIR / f"crosslayer_activity_{RUN_TS}.csv"
DISCOVERY_FILE = OUT_DIR / f"ble_audio_discoveries_{RUN_TS}.csv"
FPRINT_FILE = OUT_DIR / f"audio_fingerprints_{RUN_TS}.csv"

# ======================
# SHARED STATE
# ======================
state_lock = Lock()
latest_state = {}

# ======================
# AUDIO (LEVEL + VAD-ish + NOVELTY + HF + BURSTS + FINGERPRINTS + DOA)
# ======================
def _clamp_hf_band(fs: int):
    nyq = fs / 2.0
    hi = min(7000.0, nyq - 100.0)
    lo = min(4000.0, hi - 500.0)
    lo = max(200.0, lo)
    if hi <= lo:
        lo = max(200.0, nyq * 0.60)
        hi = max(lo + 100.0, nyq * 0.90)
    return (float(lo), float(hi))

HF_BAND = _clamp_hf_band(AUDIO_FS)

try:
    import webrtcvad
    HAVE_VAD = True
    VAD = webrtcvad.Vad(2)
except Exception:
    HAVE_VAD = False
    VAD = None

audio_db = -100.0
audio_db_history = deque(maxlen=120)
audio_env = deque(maxlen=300)

voice_ratio_hist = deque(maxlen=12)
voice_ratio = 0.0
voice_active = False

sound_doa_deg = None
sound_tdoa_us = None
sound_doa_conf = 0.0

NFFT = 1024
NOVELTY_ALPHA = 0.02
NOVELTY_BIN_Z = 3.5
NOVELTY_HOT_FRAC = 0.10
NOVELTY_MIN_DB = -55.0
bg_spec = None
novelty_hot_frac = 0.0
new_sound_appears = False

HF_MIN_DB = -55.0
hf_hist = deque(maxlen=30)
hf_z = 0.0
hf_appears = False

BURST_GAP_S = 1.0
BURST_MIN_S = 0.4
burst_active = False
burst_id = 0
burst_start_ts = None
burst_last_hit_ts = None
burst_peak_db = -999.0
burst_spike_count = 0
burst_subtle_count = 0
recent_bursts = deque(maxlen=10)

fp_lock = Lock()
fp_counts = defaultdict(int)
fp_last_seen = {}
fp_last_db = {}
fp_last_peakhash = {}
fp_last_ctx = {}
FP_LOG_HZ = 1.0
fp_chunks = []
last_fp_bands = None

def _rms_db(audio_f32: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(audio_f32 ** 2) + 1e-12))
    return float(20 * np.log10(rms + 1e-12))

def _to_int16_pcm(x: np.ndarray) -> bytes:
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767.0).astype(np.int16).tobytes()

def _rfft_mag(x: np.ndarray, nfft: int) -> np.ndarray:
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    w = np.hanning(len(x)).astype(np.float32)
    X = np.fft.rfft(x * w, n=nfft)
    return np.abs(X).astype(np.float32)

def _band_energy(mag: np.ndarray, fs: int, nfft: int, f_lo: float, f_hi: float) -> float:
    freqs = np.fft.rfftfreq(nfft, d=1.0/fs)
    idx = (freqs >= f_lo) & (freqs <= f_hi)
    if not np.any(idx):
        return 0.0
    return float(np.mean(mag[idx]))

def _cosine_sim(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    na = np.linalg.norm(a) + 1e-9
    nb = np.linalg.norm(b) + 1e-9
    return float(np.dot(a, b) / (na * nb))

def audio_active_fn():
    return audio_db > -40

def detect_audio_spike():
    if len(audio_db_history) < 10:
        return False
    baseline = float(np.mean(list(audio_db_history)[:-1]))
    return (audio_db_history[-1] - baseline) > 6.0

def detect_subtle_sound():
    if len(audio_db_history) < 10:
        return False
    baseline = float(np.mean(list(audio_db_history)[:-1]))
    delta = audio_db_history[-1] - baseline
    return (delta > 2.0) and (delta <= 6.0)

def detect_sub_5hz_audio():
    if len(audio_env) < 60:
        return False
    env = np.array(audio_env, dtype=np.float32)
    env = env - float(np.mean(env))
    fft = np.abs(np.fft.rfft(env))
    freqs = np.fft.rfftfreq(len(env), d=AUDIO_WINDOW)
    band = fft[(freqs >= 0.3) & (freqs <= 5.0)]
    if len(band) == 0:
        return False
    ratio = float(np.mean(band) / (np.mean(fft) + 1e-6))
    return ratio > 0.35

def update_audio_burst(now_ts: float, is_spike: bool, is_subtle: bool):
    global burst_active, burst_id, burst_start_ts, burst_last_hit_ts
    global burst_peak_db, burst_spike_count, burst_subtle_count

    hit = bool(is_spike or is_subtle)

    if hit and not burst_active:
        burst_active = True
        burst_id += 1
        burst_start_ts = now_ts
        burst_last_hit_ts = now_ts
        burst_peak_db = float(audio_db)
        burst_spike_count = 1 if is_spike else 0
        burst_subtle_count = 1 if is_subtle else 0
        return None

    if burst_active and hit:
        burst_last_hit_ts = now_ts
        burst_peak_db = max(burst_peak_db, float(audio_db))
        if is_spike:
            burst_spike_count += 1
        if is_subtle:
            burst_subtle_count += 1
        return None

    if burst_active and burst_last_hit_ts is not None:
        if (now_ts - burst_last_hit_ts) >= BURST_GAP_S:
            dur = float(now_ts - burst_start_ts) if burst_start_ts else 0.0
            ended = {
                "burst_id": burst_id,
                "start_ts": burst_start_ts,
                "end_ts": now_ts,
                "duration_s": dur,
                "peak_db": float(burst_peak_db),
                "spike_count": int(burst_spike_count),
                "subtle_count": int(burst_subtle_count),
            }

            burst_active = False
            burst_start_ts = None
            burst_last_hit_ts = None
            burst_peak_db = -999.0
            burst_spike_count = 0
            burst_subtle_count = 0

            if dur < BURST_MIN_S:
                return None

            recent_bursts.appendleft(ended)
            return ended

    return None

def burst_snapshot(now_ts: float):
    if not burst_active or burst_start_ts is None:
        return {"audio_burst": False, "burst_id": "", "burst_age_s": "", "burst_peak_db": "",
                "burst_spike_count": "", "burst_subtle_count": ""}
    age = float(now_ts - burst_start_ts)
    return {"audio_burst": True, "burst_id": burst_id, "burst_age_s": round(age, 2),
            "burst_peak_db": round(float(burst_peak_db), 1),
            "burst_spike_count": int(burst_spike_count),
            "burst_subtle_count": int(burst_subtle_count)}

def _voice_ratio_from_window(x_f32: np.ndarray) -> float:
    if HAVE_VAD:
        frame_len = int(AUDIO_FS * 0.02)  # 20ms
        n = len(x_f32) // frame_len
        if n <= 0:
            return 0.0
        speech = 0
        for i in range(n):
            fr = x_f32[i*frame_len:(i+1)*frame_len]
            pcm = _to_int16_pcm(fr)
            try:
                if VAD.is_speech(pcm, AUDIO_FS):
                    speech += 1
            except Exception:
                pass
        return float(speech / n)

    mag = _rfft_mag(x_f32, NFFT)
    speech_e = _band_energy(mag, AUDIO_FS, NFFT, 300, 3400)
    total_e = float(np.mean(mag) + 1e-6)
    score = speech_e / total_e
    return float(np.clip(score, 0.0, 1.0))

def audio_fingerprint_band_energy(x, fs, n_bands=16, fmin=80, fmax=None):
    if fmax is None:
        fmax = fs / 2.0
    x = x.astype(np.float32)
    x = x - float(np.mean(x))
    w = np.hanning(len(x)).astype(np.float32)
    X = np.fft.rfft(x * w)
    mag = np.abs(X).astype(np.float32)
    freqs = np.fft.rfftfreq(len(x), d=1.0/fs)
    freqs = np.clip(freqs, 1e-6, None)

    edges = np.geomspace(max(fmin, 1.0), max(fmax, fmin + 1.0), n_bands + 1)
    bands = np.zeros(n_bands, dtype=np.float32)
    for i in range(n_bands):
        lo, hi = edges[i], edges[i+1]
        idx = (freqs >= lo) & (freqs < hi)
        bands[i] = float(np.mean(mag[idx])) if np.any(idx) else 0.0

    bands = bands / (float(np.sum(bands)) + 1e-9)
    q = np.clip(np.round(bands * 255.0), 0, 255).astype(np.uint8)
    fp_hash = hashlib.sha1(q.tobytes()).hexdigest()[:16]
    return bands, fp_hash

def audio_fingerprint_peaks(x, fs, nfft=2048, top_k=12, fmin=80, fmax=None):
    if fmax is None:
        fmax = fs / 2.0
    x = x.astype(np.float32)
    x = x - float(np.mean(x))
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    w = np.hanning(len(x)).astype(np.float32)
    mag = np.abs(np.fft.rfft(x * w, n=nfft)).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, d=1.0/fs)

    idx = (freqs >= fmin) & (freqs <= fmax)
    mag2 = mag[idx]
    freqs2 = freqs[idx]
    if len(mag2) < 10:
        return "", []

    k = min(top_k, len(mag2))
    top_idx = np.argpartition(mag2, -k)[-k:]
    top_freqs = freqs2[top_idx]
    qfreq = np.sort(np.round(top_freqs / 10.0).astype(np.int32))
    peak_str = ",".join(map(str, qfreq.tolist()))
    peak_hash = hashlib.sha1(peak_str.encode("utf-8")).hexdigest()[:16]
    return peak_hash, qfreq.tolist()

def log_fingerprint_row(ts_str, db, fp_hash, peak_hash, fp_change, bands, ctx):
    with open(FPRINT_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            ts_str, round(db, 1), fp_hash, peak_hash, round(fp_change, 3),
            ctx.get("gesture", ""), ctx.get("ble_mac", ""), ctx.get("ble_trend", ""),
            ctx.get("distance", ""),
            ctx.get("sound_doa_deg", ""), ctx.get("sound_conf", ""),
            int(ctx.get("voice_active", False)), int(ctx.get("new_sound", False)),
            int(ctx.get("hf_appears", False)), int(ctx.get("audio_burst", False)),
            ctx.get("burst_id", ""), ctx.get("burst_peak_db", ""),
            ctx.get("wifi_mode", ""), ctx.get("csi_motion", ""), ctx.get("csi_rate_hz", ""),
            ";".join(str(int(round(b * 1000))) for b in bands)
        ])

# ---- GCC-PHAT DOA ----
def gcc_phat(sig: np.ndarray, refsig: np.ndarray, fs: int, max_tau: float, interp: int = 16):
    sig = np.asarray(sig, dtype=np.float32)
    refsig = np.asarray(refsig, dtype=np.float32)

    n = sig.shape[0] + refsig.shape[0]
    SIG = np.fft.rfft(sig, n=n)
    REFSIG = np.fft.rfft(refsig, n=n)
    R = SIG * np.conj(REFSIG)

    denom = np.abs(R)
    denom[denom < 1e-12] = 1e-12
    R /= denom

    cc = np.fft.irfft(R, n=(interp * n))
    max_shift = int(interp * fs * max_tau)

    if max_shift < 1:
        return 0.0, 0.0

    cc = np.concatenate((cc[-max_shift:], cc[:max_shift+1]))
    shift = int(np.argmax(np.abs(cc)) - max_shift)
    tau = shift / float(interp * fs)

    peak = float(np.max(np.abs(cc)))
    med = float(np.median(np.abs(cc)) + 1e-9)
    peak_ratio = peak / med
    conf = float(np.clip((peak_ratio - 1.0) / 10.0, 0.0, 1.0))
    return tau, conf

def estimate_doa_deg(ch0: np.ndarray, ch1: np.ndarray) -> tuple:
    d = float(ARGS.mic_spacing_m)
    c = float(ARGS.sound_speed)
    if d <= 0:
        return None, None, 0.0

    max_tau = d / c
    tau, conf = gcc_phat(ch0, ch1, fs=AUDIO_FS, max_tau=max_tau, interp=16)
    x = float(np.clip((c * tau) / d, -1.0, 1.0))
    doa = float(np.degrees(np.arcsin(x)))
    return doa, float(tau * 1e6), conf

def audio_loop():
    global audio_db, voice_ratio, voice_active
    global bg_spec, novelty_hot_frac, new_sound_appears
    global hf_z, hf_appears
    global fp_chunks, last_fp_bands
    global sound_doa_deg, sound_tdoa_us, sound_doa_conf

    doa_buf = deque(maxlen=int(max(2, round(0.25 / AUDIO_WINDOW))))

    while True:
        now_ts = time.time()

        try:
            audio = sd.rec(
                AUDIO_SAMPLES,
                samplerate=AUDIO_FS,
                channels=AUDIO_CHANNELS,
                dtype="float32",
                device=MIC_DEVICE,
                blocking=True
            )
        except Exception:
            time.sleep(0.1)
            continue

        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        mono = np.mean(audio, axis=1).astype(np.float32)

        db = _rms_db(mono)
        audio_db = db
        audio_db_history.append(db)

        rms = float(np.sqrt(np.mean(mono ** 2) + 1e-12))
        audio_env.append(rms)

        vr = _voice_ratio_from_window(mono)
        voice_ratio_hist.append(vr)
        voice_ratio = float(np.mean(voice_ratio_hist)) if len(voice_ratio_hist) else 0.0
        voice_active = voice_ratio >= 0.55

        if db >= NOVELTY_MIN_DB:
            mag = _rfft_mag(mono, NFFT)
            if bg_spec is None:
                bg_spec = mag.copy()
            else:
                bg_spec = (1.0 - NOVELTY_ALPHA) * bg_spec + NOVELTY_ALPHA * mag
            nov = (mag - bg_spec) / (bg_spec + 1e-6)
            novelty_hot_frac = float(np.mean(nov > NOVELTY_BIN_Z))
            new_sound_appears = novelty_hot_frac >= NOVELTY_HOT_FRAC
        else:
            novelty_hot_frac = 0.0
            new_sound_appears = False

        if db >= HF_MIN_DB and bg_spec is not None:
            mag = _rfft_mag(mono, NFFT)
            hf_e = _band_energy(mag, AUDIO_FS, NFFT, HF_BAND[0], HF_BAND[1])
            hf_hist.append(hf_e)
            base = float(np.median(hf_hist)) if len(hf_hist) >= 8 else hf_e
            hf_z = float((hf_e - base) / (base + 1e-6))
            hf_appears = hf_z >= 5.0
        else:
            hf_z = 0.0
            hf_appears = False

        spike = detect_audio_spike()
        subtle = detect_subtle_sound()
        update_audio_burst(now_ts, spike, subtle)

        if AUDIO_CHANNELS >= 2:
            doa_buf.append(audio[:, :2].copy())
            if len(doa_buf) >= 2:
                seg = np.concatenate(list(doa_buf), axis=0)
                ch0 = seg[:, 0]
                ch1 = seg[:, 1]
                doa, tdoa_us, conf = estimate_doa_deg(ch0, ch1)
                sound_doa_deg = doa
                sound_tdoa_us = tdoa_us
                sound_doa_conf = conf
        else:
            sound_doa_deg = None
            sound_tdoa_us = None
            sound_doa_conf = 0.0

        fp_chunks.append(mono.copy())
        need = int(max(1, round(FP_LOG_HZ ** -1 / AUDIO_WINDOW)))
        if len(fp_chunks) >= need:
            seg = np.concatenate(fp_chunks, axis=0)
            fp_chunks.clear()

            bands, fp_hash = audio_fingerprint_band_energy(seg, AUDIO_FS, n_bands=16, fmin=80)
            peak_hash, _ = audio_fingerprint_peaks(seg, AUDIO_FS, nfft=2048, top_k=12, fmin=80)

            fp_change = 0.0
            if last_fp_bands is not None:
                fp_change = 1.0 - _cosine_sim(bands, last_fp_bands)
            last_fp_bands = bands

            with state_lock:
                ctx = dict(latest_state) if latest_state else {}

            ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
            log_fingerprint_row(ts_str, db, fp_hash, peak_hash, fp_change, bands, ctx)

            with fp_lock:
                fp_counts[fp_hash] += 1
                fp_last_seen[fp_hash] = time.time()
                fp_last_db[fp_hash] = float(db)
                fp_last_peakhash[fp_hash] = peak_hash
                fp_last_ctx[fp_hash] = {
                    "gesture": ctx.get("gesture", ""),
                    "ble_mac": ctx.get("ble_mac", ""),
                    "voice": int(bool(ctx.get("voice_active", False))),
                    "new": int(bool(ctx.get("new_sound", False))),
                    "hf": int(bool(ctx.get("hf_appears", False))),
                }

# ======================
# BLE (same logic)
# ======================
ble_packets = deque(maxlen=250)
ble_seen_time = {}
ble_rssi_hist = defaultdict(lambda: deque(maxlen=35))
ble_is_close = {}
ble_close_start = {}
ble_close_stats = {}

ble_close_events = deque(maxlen=80)
ble_drop_events = deque(maxlen=80)

BLE_CLOSE_RSSI = -55
BLE_MIN_SAMPLES = 8
BLE_TREND_WINDOW = 12
BLE_TREND_DB = 5
BLE_DROP_TIMEOUT = 6.0

def _get_rssi(device, adv):
    try:
        if adv is not None and hasattr(adv, "rssi") and adv.rssi is not None:
            return int(adv.rssi)
    except Exception:
        pass
    try:
        if device is not None and hasattr(device, "rssi") and device.rssi is not None:
            return int(device.rssi)
    except Exception:
        pass
    return None

def ble_avg_rssi(mac: str, n: int = 6):
    hist = ble_rssi_hist.get(mac)
    if not hist or len(hist) < max(2, min(n, BLE_MIN_SAMPLES)):
        return None
    vals = [r for _, r in list(hist)[-n:]]
    return float(np.mean(vals)) if vals else None

def ble_trend(mac: str):
    hist = ble_rssi_hist.get(mac)
    if not hist or len(hist) < max(BLE_MIN_SAMPLES, BLE_TREND_WINDOW):
        avg = ble_avg_rssi(mac, 6)
        return ("stable", avg, avg, 0.0)

    vals = np.array([r for _, r in list(hist)[-BLE_TREND_WINDOW:]], dtype=np.float32)
    half = len(vals) // 2
    older = vals[:half]
    recent = vals[half:]

    older_avg = float(np.mean(older)) if len(older) else float(np.mean(vals))
    recent_avg = float(np.mean(recent)) if len(recent) else float(np.mean(vals))
    delta = recent_avg - older_avg

    if delta >= BLE_TREND_DB:
        return ("approaching", recent_avg, older_avg, float(delta))
    if delta <= -BLE_TREND_DB:
        return ("receding", recent_avg, older_avg, float(delta))
    return ("stable", recent_avg, older_avg, float(delta))

def is_close(mac: str):
    avg = ble_avg_rssi(mac, 6)
    if avg is None:
        return False
    return avg >= BLE_CLOSE_RSSI

def update_close_stats(mac: str, now_ts: float):
    avg = ble_avg_rssi(mac, 6)
    if avg is None:
        return
    st = ble_close_stats.get(mac)
    if st is None:
        st = {"start_avg": avg, "last_avg": avg, "max_avg": avg, "min_avg": avg, "last_update_ts": now_ts}
    else:
        st["last_avg"] = avg
        st["max_avg"] = max(st["max_avg"], avg)
        st["min_avg"] = min(st["min_avg"], avg)
        st["last_update_ts"] = now_ts
    ble_close_stats[mac] = st

def detection_callback(device, adv):
    rssi = _get_rssi(device, adv)
    if rssi is None:
        return

    now = time.time()
    mac = (device.address or "").lower().strip()
    if not mac:
        return

    ble_packets.append(now)
    ble_seen_time[mac] = now
    ble_rssi_hist[mac].append((now, rssi))

    close_now = is_close(mac)
    close_prev = ble_is_close.get(mac, False)
    trend_label, recent_avg, older_avg, delta = ble_trend(mac)

    if close_now and not close_prev:
        ble_is_close[mac] = True
        ble_close_start[mac] = now
        update_close_stats(mac, now)
        ble_close_events.append({"ts": now, "mac": mac, "rssi": rssi, "trend": trend_label, "trend_delta": delta})
        return

    if close_now and close_prev:
        update_close_stats(mac, now)
        return

    if (not close_now) and close_prev:
        start_ts = ble_close_start.get(mac, None)
        duration = (now - start_ts) if start_ts else None

        st = ble_close_stats.get(mac, {})
        start_avg = st.get("start_avg", None)
        last_avg = st.get("last_avg", None)
        net_delta = (last_avg - start_avg) if (start_avg is not None and last_avg is not None) else None
        overall = "stable"
        if net_delta is not None:
            if net_delta >= BLE_TREND_DB:
                overall = "approaching"
            elif net_delta <= -BLE_TREND_DB:
                overall = "receding"

        ble_is_close[mac] = False
        ble_close_start.pop(mac, None)
        ble_close_stats.pop(mac, None)

        ble_drop_events.append({
            "ts": now, "mac": mac, "rssi": rssi,
            "reason": "rssi_fell",
            "duration_s": duration,
            "close_start_ts": start_ts,
            "close_end_ts": now,
            "close_start_avg": start_avg,
            "close_end_avg": last_avg,
            "close_net_delta": net_delta,
            "close_overall_trend": overall,
        })

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

def ble_rate():
    now = time.time()
    return sum(1 for t in ble_packets if now - t < 5)

def get_closest_ble():
    best = None
    for mac, hist in ble_rssi_hist.items():
        if len(hist) < BLE_MIN_SAMPLES:
            continue
        avg = ble_avg_rssi(mac, 6)
        if avg is None:
            continue
        if best is None or avg > best[1]:
            close = is_close(mac)
            trend_label, _, _, delta = ble_trend(mac)
            best = (mac, avg, close, trend_label, delta)
    if best is None:
        return (None, None, False, "stable", 0.0)
    return best

def check_ble_timeouts():
    now = time.time()
    to_drop = []
    for mac, start_ts in list(ble_close_start.items()):
        last_seen = ble_seen_time.get(mac, 0)
        if (now - last_seen) >= BLE_DROP_TIMEOUT:
            to_drop.append(mac)

    for mac in to_drop:
        start_ts = ble_close_start.get(mac)
        duration = (now - start_ts) if start_ts else None

        st = ble_close_stats.get(mac, {})
        start_avg = st.get("start_avg", None)
        last_avg = st.get("last_avg", None)
        net_delta = (last_avg - start_avg) if (start_avg is not None and last_avg is not None) else None
        overall = "stable"
        if net_delta is not None:
            if net_delta >= BLE_TREND_DB:
                overall = "approaching"
            elif net_delta <= -BLE_TREND_DB:
                overall = "receding"

        ble_is_close[mac] = False
        ble_close_start.pop(mac, None)
        ble_close_stats.pop(mac, None)

        ble_drop_events.append({
            "ts": now, "mac": mac, "rssi": None,
            "reason": "timeout",
            "duration_s": duration,
            "close_start_ts": start_ts,
            "close_end_ts": now,
            "close_start_avg": start_avg,
            "close_end_avg": last_avg,
            "close_net_delta": net_delta,
            "close_overall_trend": overall,
        })

# ======================
# Wi-Fi CSI pipeline (+ RSSI fallback)
# ======================
class CsiWindow:
    def __init__(self, win: int = 120, max_sc: int = 64):
        self.win = int(win)
        self.max_sc = int(max_sc)
        self.frames = deque(maxlen=self.win)
        self.ts = deque(maxlen=self.win)
        self.last_rx_ts = 0.0
        self.lock = Lock()

    def push_amp(self, amp: np.ndarray, ts: float):
        amp = np.asarray(amp, dtype=np.float32).reshape(-1)
        if amp.size == 0:
            return
        if amp.size > self.max_sc:
            amp = amp[:self.max_sc]
        amp = amp / (float(np.mean(amp)) + 1e-6)
        with self.lock:
            self.frames.append(amp)
            self.ts.append(float(ts))
            self.last_rx_ts = time.time()

    def has_data(self) -> bool:
        with self.lock:
            return len(self.frames) >= max(8, self.win // 6)

    def rate_hz(self, horizon_s: float = 2.0) -> float:
        now = time.time()
        with self.lock:
            n = sum(1 for t in self.ts if (now - t) <= horizon_s)
        return float(n / max(horizon_s, 1e-6))

    def motion_score(self) -> float:
        if not self.has_data():
            return 0.0
        with self.lock:
            X = list(self.frames)[-min(len(self.frames), self.win):]
            max_sc = self.max_sc

        m = max(v.size for v in X)
        M = min(m, max_sc)
        A = np.zeros((len(X), M), dtype=np.float32)
        for i, v in enumerate(X):
            vv = v[:M]
            if vv.size < M:
                vv = np.pad(vv, (0, M - vv.size))
            A[i] = vv
        A = A - np.mean(A, axis=0, keepdims=True)
        std_sc = np.std(A, axis=0)
        return float(np.mean(std_sc))

CSI = CsiWindow(win=120, max_sc=64)

def parse_csi_line(line: str):
    line = line.strip()
    if not line:
        return None

    if line[0] in "{[":
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                ts = float(obj.get("ts", time.time()))
                if "amp" in obj and isinstance(obj["amp"], list):
                    return ts, np.asarray(obj["amp"], dtype=np.float32)
                if "csi" in obj and isinstance(obj["csi"], list):
                    arr = np.asarray(obj["csi"], dtype=np.float32)
                    if arr.ndim == 2 and arr.shape[1] == 2:
                        re_ = arr[:, 0]
                        im_ = arr[:, 1]
                        amp = np.sqrt(re_*re_ + im_*im_)
                        return ts, amp
            if isinstance(obj, list) and len(obj) > 3:
                try:
                    ts = float(obj[0])
                    vals = np.asarray(obj[1:], dtype=np.float32)
                    return ts, vals
                except Exception:
                    pass
        except Exception:
            pass

    parts = [p for p in line.split(",") if p.strip() != ""]
    if len(parts) < 3:
        return None
    try:
        ts = float(parts[0])
        vals = np.asarray([float(x) for x in parts[1:]], dtype=np.float32)
        if vals.size % 2 == 0 and vals.size >= 4:
            re_ = vals[0::2]
            im_ = vals[1::2]
            amp = np.sqrt(re_*re_ + im_*im_)
            return ts, amp
        return ts, vals
    except Exception:
        return None

def csi_loop_udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ARGS.csi_host, int(ARGS.csi_port)))
    sock.settimeout(1.0)
    while True:
        try:
            data, _addr = sock.recvfrom(65535)
            line = data.decode("utf-8", errors="ignore").strip()
            parsed = parse_csi_line(line)
            if parsed is None:
                continue
            ts, amp = parsed
            CSI.push_amp(amp, ts)
        except socket.timeout:
            continue
        except Exception:
            continue

def csi_loop_file(path: str):
    p = Path(path)
    if not p.exists():
        print(f"❌ CSI file not found: {path}")
        return
    with p.open("r", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.05)
                continue
            parsed = parse_csi_line(line)
            if parsed is None:
                continue
            ts, amp = parsed
            CSI.push_amp(amp, ts)

wifi_rssi = deque(maxlen=400)

def read_wifi_rssi():
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "IN-USE,SIGNAL", "dev", "wifi", "list"],
            stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if line.startswith("*:"):
                return int(line.split(":")[1])
    except Exception:
        pass
    return None

def wifi_rssi_loop():
    while True:
        rssi = read_wifi_rssi()
        if rssi is not None:
            wifi_rssi.append(rssi)
        time.sleep(1)

# ======================
# Gesture + Fusion
# ======================
def classify_gesture():
    rate = ble_rate()
    csi_m = CSI.motion_score()
    csi_ok = CSI.has_data()

    if csi_ok:
        energy = float(csi_m + rate * 0.25)
        if csi_m < 0.03 and rate == 0:
            return "idle", energy
        if csi_m < 0.05 and detect_sub_5hz_audio():
            return "presence_nearby", energy
        if csi_m < 0.06 and audio_active_fn():
            return "listening", energy
        if csi_m >= 0.06 and audio_active_fn():
            return "talking", energy
        if csi_m > 0.12:
            return "moving", energy
        return "unknown", energy

    if len(wifi_rssi) < 40:
        return "no-data", 0.0
    sig = np.array(list(wifi_rssi)[-40:], dtype=np.float32)
    short = sig[-10:]
    short_std = float(np.std(short))
    energy = float(short_std + rate * 0.3)

    if short_std < 0.8 and rate == 0:
        return "idle", energy
    if short_std < 1.0 and detect_sub_5hz_audio():
        return "presence_nearby", energy
    if short_std < 1.2 and audio_active_fn():
        return "listening", energy
    if short_std > 1.2 and audio_active_fn():
        return "talking", energy
    if short_std > 2.0:
        return "moving", energy
    return "unknown", energy

def infer_sound_distance():
    if len(audio_db_history) < 8:
        return "unknown"
    da = float(audio_db_history[-1] - audio_db_history[-8])

    if CSI.has_data():
        m_now = CSI.motion_score()
        with CSI.lock:
            frames = list(CSI.frames)
            max_sc = CSI.max_sc
            win = CSI.win

        if len(frames) >= 16:
            prev_frames = frames[:-8]
            if len(prev_frames) >= 8:
                X = prev_frames[-min(len(prev_frames), win):]
                m = max(v.size for v in X)
                M = min(m, max_sc)
                A = np.zeros((len(X), M), dtype=np.float32)
                for i, v in enumerate(X):
                    vv = v[:M]
                    if vv.size < M:
                        vv = np.pad(vv, (0, M - vv.size))
                    A[i] = vv
                A = A - np.mean(A, axis=0, keepdims=True)
                m_prev = float(np.mean(np.std(A, axis=0)))
            else:
                m_prev = m_now
        else:
            m_prev = m_now

        dm = m_now - m_prev
        if da > 3 and dm > 0.01:
            return "approaching"
        if da < -3 and dm < -0.01:
            return "receding"
        return "stable"

    if len(wifi_rssi) < 20:
        return "unknown"
    rf_now = float(np.mean(list(wifi_rssi)[-10:]))
    rf_prev = float(np.mean(list(wifi_rssi)[-20:-10]))
    drf = rf_now - rf_prev

    if da > 3 and drf > 1:
        return "approaching"
    if da < -3 and drf < -1:
        return "receding"
    return "stable"

def build_state():
    now_ts = time.time()
    gesture, energy = classify_gesture()
    mac, avg_rssi, ble_close, ble_tr, ble_tr_delta = get_closest_ble()

    spike = detect_audio_spike()
    subtle = detect_subtle_sound()
    sub5 = detect_sub_5hz_audio()
    binfo = burst_snapshot(now_ts)

    csi_m = CSI.motion_score()
    csi_rate = CSI.rate_hz()
    csi_ok = CSI.has_data()
    wifi_mode = ARGS.wifi_mode

    doa = "" if sound_doa_deg is None else round(float(sound_doa_deg), 1)
    tdoa = "" if sound_tdoa_us is None else round(float(sound_tdoa_us), 1)
    conf = round(float(sound_doa_conf), 2)

    return {
        "gesture": gesture,
        "energy": round(energy, 3),

        "audio_db": round(audio_db, 1),
        "audio_active": audio_active_fn(),
        "audio_spike": spike,
        "audio_subtle": subtle,
        "audio_sub5hz": sub5,
        "audio_burst": binfo["audio_burst"],
        "burst_id": binfo["burst_id"],
        "burst_age_s": binfo["burst_age_s"],
        "burst_peak_db": binfo["burst_peak_db"],
        "burst_spike_count": binfo["burst_spike_count"],
        "burst_subtle_count": binfo["burst_subtle_count"],

        "voice_ratio": round(float(voice_ratio), 3),
        "voice_active": bool(voice_active),

        "novelty_hot_frac": round(float(novelty_hot_frac), 3),
        "new_sound": bool(new_sound_appears),

        "hf_z": round(float(hf_z), 2),
        "hf_appears": bool(hf_appears),

        "sound_doa_deg": doa,
        "sound_tdoa_us": tdoa,
        "sound_conf": conf,

        "ble_rate": ble_rate(),
        "ble_close": bool(ble_close),
        "ble_mac": mac or "",
        "ble_rssi_avg": round(avg_rssi, 1) if avg_rssi is not None else "",
        "ble_trend": ble_tr,
        "ble_trend_delta": round(float(ble_tr_delta), 1),

        "wifi_mode": wifi_mode,
        "csi_ok": bool(csi_ok),
        "csi_rate_hz": round(float(csi_rate), 1),
        "csi_motion": round(float(csi_m), 4),

        "rf_motion": (csi_m > 0.06) if csi_ok else (energy > 1.2),
        "distance": infer_sound_distance(),
    }

# ======================
# CROSS-LAYER RULES + DISCOVERY SIGNATURES
# ======================
KNOWN_RULES = {
    "voice_present": lambda s: s["voice_active"],
    "new_sound_appears": lambda s: s["new_sound"],
    "hf_appears": lambda s: s["hf_appears"],
    "audio_burst": lambda s: s["audio_burst"],

    "ble_close_voice": lambda s: s["ble_close"] and s["voice_active"],
    "ble_close_new_sound": lambda s: s["ble_close"] and s["new_sound"],
    "ble_close_burst": lambda s: s["ble_close"] and s["audio_burst"],
    "ble_close_hf": lambda s: s["ble_close"] and s["hf_appears"],
    "ble_approaching": lambda s: s["ble_close"] and s["ble_trend"] == "approaching",
    "ble_receding": lambda s: s["ble_close"] and s["ble_trend"] == "receding",

    "ble_close_sound_dir": lambda s: s["ble_close"] and (s.get("sound_doa_deg","") != "") and float(s.get("sound_conf",0)) >= 0.3,
    "csi_motion_burst": lambda s: s.get("csi_ok", False) and float(s.get("csi_motion", 0.0) or 0.0) >= 0.08 and s["audio_burst"],
}

pattern_counts = defaultdict(int)
DISCOVERY_THRESHOLD = 10

ble_sig_counts = defaultdict(int)
BLE_SIG_THRESHOLD = 6

def auto_discover(state):
    active_keys = [k for k, v in state.items() if isinstance(v, bool) and v]
    for i in range(len(active_keys)):
        for j in range(i + 1, len(active_keys)):
            pattern_counts[f"{active_keys[i]}+{active_keys[j]}"] += 1

def discovered_patterns():
    return [k for k, v in pattern_counts.items() if v >= DISCOVERY_THRESHOLD]

def discover_ble_signature(mac: str, state: dict):
    sig = (
        f"mac:{mac}|"
        f"ble:{state['ble_trend']}({state['ble_trend_delta']})|"
        f"dist:{state['distance']}|"
        f"gesture:{state['gesture']}|"
        f"doa:{state.get('sound_doa_deg','')}({state.get('sound_conf','')})|"
        f"csi:{state.get('csi_motion','')}@{state.get('csi_rate_hz','')}hz|"
        f"voice:{int(state['voice_active'])}|"
        f"new:{int(state['new_sound'])}|"
        f"hf:{int(state['hf_appears'])}|"
        f"burst:{int(state['audio_burst'])}"
    )
    ble_sig_counts[sig] += 1
    return sig, ble_sig_counts[sig]

def discovered_ble_signatures():
    items = [(k, v) for k, v in ble_sig_counts.items() if v >= BLE_SIG_THRESHOLD]
    items.sort(key=lambda kv: kv[1])
    return items[-10:]

def detect_cross_layers(state):
    active = []
    for name, rule in KNOWN_RULES.items():
        try:
            if rule(state):
                active.append(name)
        except Exception:
            pass
    auto_discover(state)
    return active

# ======================
# LOGGING
# ======================
def ensure_logs():
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp",
                "gesture", "energy",
                "audio_db", "audio_active", "audio_spike", "audio_subtle", "audio_sub5hz",
                "audio_burst", "burst_id", "burst_age_s", "burst_peak_db", "burst_spike_count", "burst_subtle_count",
                "voice_ratio", "voice_active",
                "novelty_hot_frac", "new_sound",
                "hf_z", "hf_appears",
                "sound_doa_deg", "sound_tdoa_us", "sound_conf",
                "wifi_mode", "csi_ok", "csi_rate_hz", "csi_motion",
                "rf_motion",
                "ble_rate", "ble_close", "ble_mac", "ble_rssi_avg", "ble_trend", "ble_trend_delta",
                "distance",
                "cross_layers",
            ])

    if not DISCOVERY_FILE.exists():
        with open(DISCOVERY_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp",
                "event",
                "ble_mac", "ble_rssi", "ble_rssi_avg", "ble_trend", "ble_trend_delta",
                "gesture", "distance",
                "audio_db", "voice_ratio", "voice_active",
                "new_sound", "novelty_hot_frac",
                "hf_appears", "hf_z",
                "audio_burst", "burst_id", "burst_peak_db",
                "sound_doa_deg", "sound_conf",
                "wifi_mode", "csi_ok", "csi_rate_hz", "csi_motion",
                "signature", "signature_count",
                "close_start_ts", "close_end_ts", "close_duration_s",
                "close_start_avg", "close_end_avg", "close_net_delta",
                "close_overall_trend",
                "drop_reason",
            ])

    if not FPRINT_FILE.exists():
        with open(FPRINT_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "audio_db",
                "fp_hash", "peak_hash", "fp_change",
                "gesture", "ble_mac", "ble_trend", "distance",
                "sound_doa_deg", "sound_conf",
                "voice_active", "new_sound", "hf_appears", "audio_burst",
                "burst_id", "burst_peak_db",
                "wifi_mode", "csi_motion", "csi_rate_hz",
                "bands_16",
            ])

def log_csv(state, cross):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            state["gesture"], state["energy"],
            state["audio_db"], int(state["audio_active"]), int(state["audio_spike"]), int(state["audio_subtle"]), int(state["audio_sub5hz"]),
            int(state["audio_burst"]), state["burst_id"], state["burst_age_s"], state["burst_peak_db"], state["burst_spike_count"], state["burst_subtle_count"],
            state["voice_ratio"], int(state["voice_active"]),
            state["novelty_hot_frac"], int(state["new_sound"]),
            state["hf_z"], int(state["hf_appears"]),
            state["sound_doa_deg"], state["sound_tdoa_us"], state["sound_conf"],
            state["wifi_mode"], int(state["csi_ok"]), state["csi_rate_hz"], state["csi_motion"],
            int(state["rf_motion"]),
            state["ble_rate"], int(state["ble_close"]), state["ble_mac"], state["ble_rssi_avg"], state["ble_trend"], state["ble_trend_delta"],
            state["distance"],
            ";".join(cross)
        ])

def log_discovery_row(event: str, mac: str, rssi, state: dict, sig: str, sig_count: int,
                      close_start_ts=None, close_end_ts=None, close_duration_s=None,
                      close_start_avg=None, close_end_avg=None, close_net_delta=None,
                      close_overall_trend="stable", drop_reason=""):
    with open(DISCOVERY_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            event,
            mac,
            "" if rssi is None else rssi,
            state["ble_rssi_avg"],
            state["ble_trend"],
            state["ble_trend_delta"],
            state["gesture"],
            state["distance"],
            state["audio_db"],
            state["voice_ratio"],
            int(state["voice_active"]),
            int(state["new_sound"]),
            state["novelty_hot_frac"],
            int(state["hf_appears"]),
            state["hf_z"],
            int(state["audio_burst"]),
            state["burst_id"],
            state["burst_peak_db"],
            state.get("sound_doa_deg",""),
            state.get("sound_conf",""),
            state.get("wifi_mode",""),
            int(state.get("csi_ok", False)),
            state.get("csi_rate_hz",""),
            state.get("csi_motion",""),
            sig,
            sig_count,
            "" if close_start_ts is None else f"{close_start_ts:.3f}",
            "" if close_end_ts is None else f"{close_end_ts:.3f}",
            "" if close_duration_s is None else f"{close_duration_s:.3f}",
            "" if close_start_avg is None else round(float(close_start_avg), 1),
            "" if close_end_avg is None else round(float(close_end_avg), 1),
            "" if close_net_delta is None else round(float(close_net_delta), 1),
            close_overall_trend,
            drop_reason
        ])

# ======================
# BLE event handlers
# ======================
recent_events = deque(maxlen=14)

def handle_ble_close_events(state):
    now = time.time()
    while ble_close_events:
        ev = ble_close_events.popleft()
        if now - ev["ts"] > 6.0:
            continue
        mac = ev["mac"]
        rssi = ev["rssi"]
        sig, sig_count = discover_ble_signature(mac, state)
        log_discovery_row("ble_close", mac, rssi, state, sig, sig_count, close_start_ts=ble_close_start.get(mac, ev["ts"]))
        recent_events.appendleft(
            f"CLOSE mac:{mac} rssi:{rssi} ble:{state['ble_trend']} "
            f"gest:{state['gesture']} dist:{state['distance']} "
            f"doa:{state.get('sound_doa_deg','')}({state.get('sound_conf','')}) "
            f"csi:{state.get('csi_motion','')} "
            f"voice:{int(state['voice_active'])} new:{int(state['new_sound'])} hf:{int(state['hf_appears'])} "
            f"burst:{int(state['audio_burst'])} ({sig_count}x)"
        )

def handle_ble_drop_events(state):
    now = time.time()
    while ble_drop_events:
        ev = ble_drop_events.popleft()
        if now - ev["ts"] > 12.0:
            continue
        mac = ev["mac"]
        rssi = ev.get("rssi", None)
        reason = ev.get("reason", "unknown")
        duration_s = ev.get("duration_s", None)

        sig, sig_count = discover_ble_signature(mac, state)
        log_discovery_row(
            "ble_drop", mac, rssi, state, sig, sig_count,
            close_start_ts=ev.get("close_start_ts", None),
            close_end_ts=ev.get("close_end_ts", ev["ts"]),
            close_duration_s=duration_s,
            close_start_avg=ev.get("close_start_avg", None),
            close_end_avg=ev.get("close_end_avg", None),
            close_net_delta=ev.get("close_net_delta", None),
            close_overall_trend=ev.get("close_overall_trend", "stable"),
            drop_reason=reason
        )

        dur_txt = f"{duration_s:.1f}s" if duration_s is not None else "?"
        recent_events.appendleft(
            f"DROP  mac:{mac} dur:{dur_txt} reason:{reason} overall:{ev.get('close_overall_trend','stable')} "
            f"gest:{state['gesture']} dist:{state['distance']} "
            f"doa:{state.get('sound_doa_deg','')}({state.get('sound_conf','')}) "
            f"csi:{state.get('csi_motion','')} "
            f"voice:{int(state['voice_active'])} new:{int(state['new_sound'])} hf:{int(state['hf_appears'])} "
            f"burst:{int(state['audio_burst'])} ({sig_count}x)"
        )

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cross-Layer Dashboard — CSI + Sound DOA + Audio Fingerprints (Top 20)")
        self.label = QLabel("Starting…")
        self.label.setStyleSheet("font-family: monospace;")
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def _top20_fingerprints_lines(self):
        with fp_lock:
            items = [(h, c) for h, c in fp_counts.items()]
            items.sort(key=lambda x: x[1], reverse=True)
            top = items[:20]

            lines = []
            now = time.time()
            for h, c in top:
                age_s = now - fp_last_seen.get(h, now)
                peak = fp_last_peakhash.get(h, "")
                dbv = fp_last_db.get(h, -999.0)
                ctx = fp_last_ctx.get(h, {})
                ble = ctx.get("ble_mac", "")
                gesture = ctx.get("gesture", "")
                flags = f"v{ctx.get('voice',0)} n{ctx.get('new',0)} h{ctx.get('hf',0)}"
                lines.append(
                    f"• {h}  x{c:<4}  last:{age_s:>5.1f}s  dB:{dbv:>6.1f}  peak:{peak}  "
                    f"gest:{gesture}  ble:{ble[-8:] if ble else ''}  {flags}"
                )
            return lines

    def update_view(self):
        check_ble_timeouts()

        state = build_state()
        with state_lock:
            latest_state.clear()
            latest_state.update(state)

        cross = detect_cross_layers(state)
        handle_ble_close_events(state)
        handle_ble_drop_events(state)
        log_csv(state, cross)

        generic = discovered_patterns()[-6:]
        ble_sigs = discovered_ble_signatures()
        evt_lines = list(recent_events)[:6]

        burst_lines = []
        for b in list(recent_bursts)[:4]:
            burst_lines.append(
                f"• burst#{b['burst_id']} dur:{b['duration_s']:.1f}s peak:{b['peak_db']:.1f}dB "
                f"spk:{b['spike_count']} sub:{b['subtle_count']}"
            )

        sig_lines = [f"• ({cnt}x) {sig[:120]}{'...' if len(sig) > 120 else ''}" for sig, cnt in ble_sigs]

        fp_lines = self._top20_fingerprints_lines()
        if not fp_lines:
            fp_lines = ["• (none yet)"]

        doa_txt = "n/a" if state.get("sound_doa_deg","") == "" else f"{state['sound_doa_deg']}° (conf {state['sound_conf']})"

        self.label.setText(
            f"Run logs:\n"
            f"  {LOG_FILE}\n"
            f"  {DISCOVERY_FILE}\n"
            f"  {FPRINT_FILE}\n\n"
            f"Wi-Fi mode      : {state.get('wifi_mode','')}\n"
            f"Mic device      : {MIC_DEVICE if MIC_DEVICE is not None else 'default/unknown'}  fs:{AUDIO_FS}  ch:{AUDIO_CHANNELS}\n"
            f"CSI data        : {int(state.get('csi_ok', False))}  rate:{state.get('csi_rate_hz','')} Hz  motion:{state.get('csi_motion','')}\n"
            f"Gesture         : {state['gesture']}\n"
            f"Energy          : {state['energy']}\n"
            f"Audio dB        : {state['audio_db']}\n"
            f"Sound DOA       : {doa_txt}\n"
            f"Voice           : {int(state['voice_active'])} (ratio={state['voice_ratio']})  VAD={'on' if HAVE_VAD else 'fallback'}\n"
            f"New sound       : {int(state['new_sound'])} (hot={state['novelty_hot_frac']})\n"
            f"HF appears      : {int(state['hf_appears'])} (z={state['hf_z']}) band={HF_BAND[0]:.0f}-{HF_BAND[1]:.0f}Hz\n"
            f"Burst           : {int(state['audio_burst'])} id:{state['burst_id']} peak:{state['burst_peak_db']}\n"
            f"BLE closest     : {state['ble_mac'] if state['ble_mac'] else 'none'}\n"
            f"BLE rssi(avg)   : {state['ble_rssi_avg']}  close:{int(state['ble_close'])}\n"
            f"BLE trend       : {state['ble_trend']}  delta:{state['ble_trend_delta']}\n"
            f"Sound distance  : {state['distance']}\n\n"
            f"Cross-Layers:\n"
            + ("\n".join(f"• {c}" for c in cross) if cross else "• (none)") +
            "\n\nRecent BLE events:\n"
            + ("\n".join(f"• {e}" for e in evt_lines) if evt_lines else "• (none yet)") +
            "\n\nRecent Audio Bursts:\n"
            + ("\n".join(burst_lines) if burst_lines else "• (none yet)") +
            "\n\nDiscovered BLE signatures:\n"
            + ("\n".join(sig_lines) if sig_lines else "• (none yet)") +
            "\n\nTop 20 Recurring Audio Fingerprints:\n"
            + "\n".join(fp_lines) +
            "\n\nGeneric Auto-Discovered:\n"
            + ("\n".join(f"• {d}" for d in generic) if generic else "• (none yet)")
        )

# ======================
# MAIN
# ======================
def main():
    if getattr(ARGS, "list_mics", False):
        print_mics()
        return

    ensure_logs()
    if MIC_NOTE:
        print(f"🎤 {MIC_NOTE}")

    threading.Thread(target=audio_loop, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()

    if ARGS.wifi_mode == "udp":
        threading.Thread(target=csi_loop_udp, daemon=True).start()
    elif ARGS.wifi_mode == "file":
        if not ARGS.csi_file:
            print("❌ --csi-file is required when --wifi-mode file")
        else:
            threading.Thread(target=lambda: csi_loop_file(ARGS.csi_file), daemon=True).start()
    else:
        threading.Thread(target=wifi_rssi_loop, daemon=True).start()

    app = QApplication(sys.argv)
    gui = Dashboard()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(int(ARGS.gui_refresh_ms))

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
