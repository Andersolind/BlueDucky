#!/usr/bin/env python3
"""
Cross-Layer Dashboard (Linux) + Audio Fingerprints + MAC Identity Anomalies
+ Gesture↔Event Cross-Correlation Learning
+ Online Behavior Clustering (fallback anomaly z)
+ Offline ML Anomaly Model Integration (IsolationForest, optional)
+ ✅ Sleeping gesture (state-machine based)

DATA QUALITY REFACTOR (v2):
- Adds run_meta_<run_id>.json (hardware + params + versions + thresholds)
- Standardizes timestamps: iso_ts, t_rel_s, tick in ALL logs
- Logs state at 1 Hz (configurable) + ALWAYS logs transitions to events_<run_id>.csv
- Baseline-calibrates "always-on" features (rf_motion, sub5hz) using warmup percentiles
- Throttles MAC anomaly logging (cooldown) to stop repeated spam
- Adds data_health_<run_id>.json periodic snapshots to catch stuck features early
- Makes fingerprints more repeatable (coarser quantization + peak hash + similarity)

Privacy note:
- Observes RF/BLE activity + audio features (not raw audio).
- Use only on devices/networks/areas you own or have permission to monitor.
- MACs are masked by default (set LOG_RAW_MAC=True only if you truly need it).

Deps:
  pip install numpy sounddevice bleak PyQt5
Optional voice:
  pip install webrtcvad-wheels
Optional ML inference:
  pip install scikit-learn joblib
"""

import sys, time, threading, asyncio, subprocess, os, csv, warnings, hashlib, json, platform
import numpy as np
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from threading import Lock

# ======================
# SAFETY (Linux)
# ======================
if hasattr(os, "geteuid") and os.geteuid() == 0:
    print("❌ Do NOT run with sudo")
    sys.exit(1)

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning
)

# ======================
# CONFIG
# ======================
TICK_S = 0.5
STATE_LOG_EVERY_S = 1.0          # 1 Hz state sampling; transitions always logged
HEALTH_SNAPSHOT_EVERY_S = 60.0   # write data_health JSON periodically
BASELINE_WARMUP_S = 120.0        # calibrate thresholds from first N seconds

LOG_RAW_MAC = False              # default masked for privacy
MAC_SALT = "local-only-salt-change-me"  # change if you want different hashing

MAC_EVENT_COOLDOWN_S = 30.0      # throttle repeated MAC anomaly rows
DISCOVERY_THRESHOLD = 10
BLE_SIG_THRESHOLD = 6

# ======================
# TIME + RUN IDS
# ======================
def iso_ts() -> str:
    # ISO 8601 with local timezone offset
    return datetime.now().astimezone().isoformat(timespec="milliseconds")

RUN_START_TS = time.time()

def t_rel_s(now_ts: float) -> float:
    return float(now_ts - RUN_START_TS)

OUT_DIR = Path("logs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def _next_run_id(counter_path: Path) -> str:
    # simple counter file: increments per run
    try:
        if counter_path.exists():
            n = int(counter_path.read_text().strip() or "0")
        else:
            n = 0
    except Exception:
        n = 0
    n += 1
    try:
        counter_path.write_text(str(n))
    except Exception:
        pass
    return f"run{n:04d}"

RUN_ID = _next_run_id(OUT_DIR / "run_counter.txt")
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")

# ======================
# PRIVACY HELPERS
# ======================
def mac_hash(mac: str) -> str:
    mac = (mac or "").lower().strip()
    if not mac:
        return ""
    return hashlib.sha1((MAC_SALT + mac).encode("utf-8")).hexdigest()[:12]

def mac_tail(mac: str) -> str:
    mac = (mac or "").lower().strip()
    return mac[-8:] if mac else ""

def mac_for_log(mac: str) -> str:
    if LOG_RAW_MAC:
        return (mac or "")
    if not mac:
        return ""
    return f"{mac_tail(mac)}|{mac_hash(mac)}"

# ======================
# OUTPUT FILES (per run_id)
# ======================
LOG_FILE        = OUT_DIR / f"{RUN_ID}_state_{RUN_TS}.csv"
DISCOVERY_FILE  = OUT_DIR / f"{RUN_ID}_discoveries_{RUN_TS}.csv"
FPRINT_FILE     = OUT_DIR / f"{RUN_ID}_audio_fingerprints_{RUN_TS}.csv"
MAC_ID_FILE     = OUT_DIR / f"{RUN_ID}_mac_identity_{RUN_TS}.csv"
CORR_FILE       = OUT_DIR / f"{RUN_ID}_gesture_event_corr_{RUN_TS}.csv"
FEAT_FILE       = OUT_DIR / f"{RUN_ID}_ml_features_{RUN_TS}.csv"
MODEL_SNAPSHOT  = OUT_DIR / f"{RUN_ID}_behavior_model_{RUN_TS}.json"
ANOM_FILE       = OUT_DIR / f"{RUN_ID}_anomaly_events_{RUN_TS}.csv"
EVENTS_FILE     = OUT_DIR / f"{RUN_ID}_events_{RUN_TS}.csv"           # NEW: transitions
RUN_META_FILE   = OUT_DIR / f"{RUN_ID}_run_meta_{RUN_TS}.json"        # NEW: run metadata
HEALTH_FILE     = OUT_DIR / f"{RUN_ID}_data_health_{RUN_TS}.json"     # NEW: data health snapshots

# ======================
# Optional ML model paths (trained offline)
# ======================
MODEL_DIR = Path("models")
MODEL_JOBLIB = MODEL_DIR / "anomaly_model.joblib"
MODEL_META   = MODEL_DIR / "anomaly_model_meta.json"

# ======================
# SHARED STATE
# ======================
state_lock = Lock()
latest_state = {}

# ======================
# BASELINE CALIBRATION (fix "always-on" flags)
# ======================
class BaselineCalibrator:
    """
    Collects warmup distributions for key metrics, then produces stable thresholds:
    - rf_motion_energy_thr: p95(energy) during warmup
    - sub5hz_ratio_thr: p95(sub5hz_ratio) during warmup
    """
    def __init__(self, warmup_s: float):
        self.warmup_s = float(warmup_s)
        self.ready = False
        self.energy = []
        self.sub5hz_ratio = []
        self.audio_db = []
        self._ready_ts = None
        self.rf_motion_energy_thr = 1.2
        self.sub5hz_ratio_thr = 0.35
        self.audio_spike_db_thr = 6.0
        self.audio_subtle_db_thr = 2.0

    def update(self, now_ts: float, *, energy: float, sub5hz_ratio: float, audio_db: float):
        if self.ready:
            return

        if t_rel_s(now_ts) <= self.warmup_s:
            self.energy.append(float(energy))
            self.sub5hz_ratio.append(float(sub5hz_ratio))
            self.audio_db.append(float(audio_db))
            return

        # finalize
        if len(self.energy) >= 30:
            e = np.array(self.energy, dtype=np.float32)
            self.rf_motion_energy_thr = float(np.percentile(e, 95))
        if len(self.sub5hz_ratio) >= 30:
            s = np.array(self.sub5hz_ratio, dtype=np.float32)
            self.sub5hz_ratio_thr = float(np.percentile(s, 95))
        if len(self.audio_db) >= 30:
            a = np.array(self.audio_db, dtype=np.float32)
            # robust-ish spike thresholds: based on warmup variability
            med = float(np.median(a))
            mad = float(np.median(np.abs(a - med)) + 1e-6)
            # Convert MAD-ish to a threshold: keep your semantics but adapt to room
            self.audio_spike_db_thr = max(4.5, 3.0 * mad)
            self.audio_subtle_db_thr = max(1.5, 1.5 * mad)

        self.ready = True
        self._ready_ts = now_ts

    def to_dict(self):
        return {
            "ready": self.ready,
            "warmup_s": self.warmup_s,
            "rf_motion_energy_thr": self.rf_motion_energy_thr,
            "sub5hz_ratio_thr": self.sub5hz_ratio_thr,
            "audio_spike_db_thr": self.audio_spike_db_thr,
            "audio_subtle_db_thr": self.audio_subtle_db_thr,
            "ready_at_rel_s": None if self._ready_ts is None else round(t_rel_s(self._ready_ts), 2),
        }

CAL = BaselineCalibrator(BASELINE_WARMUP_S)

# ======================
# AUDIO
# ======================
import sounddevice as sd

AUDIO_FS = 16000
AUDIO_WINDOW = 0.1
AUDIO_SAMPLES = int(AUDIO_FS * AUDIO_WINDOW)

HF_BAND = (4000, 7000)

try:
    import webrtcvad
    HAVE_VAD = True
    VAD = webrtcvad.Vad(2)
except Exception:
    HAVE_VAD = False
    VAD = None

audio_db = -100.0
audio_db_history = deque(maxlen=240)    # longer history for stability
audio_env = deque(maxlen=600)

voice_ratio_hist = deque(maxlen=12)
voice_ratio = 0.0
voice_active = False

NFFT = 1024
NOVELTY_ALPHA = 0.02
NOVELTY_BIN_Z = 3.5
NOVELTY_HOT_FRAC = 0.10
NOVELTY_MIN_DB = -55.0
bg_spec = None
novelty_hot_frac = 0.0
new_sound_appears = False

HF_MIN_DB = -55.0
hf_hist = deque(maxlen=60)
hf_z = 0.0
hf_appears = False

# Bursts
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

# Fingerprints
fp_lock = Lock()
fp_counts = defaultdict(int)
fp_last_seen = {}
fp_last_db = {}
fp_last_peakhash = {}
fp_last_ctx = {}

FP_SECONDS = 1.0
fp_chunks = []
last_fp_bands = None
last_fp_hash = ""
last_peak_hash = ""

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

def audio_active_fn() -> bool:
    return audio_db > -40

def _baseline_db():
    if len(audio_db_history) < 12:
        return float(np.mean(audio_db_history)) if audio_db_history else -100.0
    # robust baseline: median
    return float(np.median(np.array(audio_db_history, dtype=np.float32)))

def detect_audio_spike() -> bool:
    if len(audio_db_history) < 12:
        return False
    base = _baseline_db()
    return (audio_db_history[-1] - base) > float(CAL.audio_spike_db_thr)

def detect_subtle_sound() -> bool:
    if len(audio_db_history) < 12:
        return False
    base = _baseline_db()
    delta = audio_db_history[-1] - base
    return (delta > float(CAL.audio_subtle_db_thr)) and (delta <= float(CAL.audio_spike_db_thr))

def sub5hz_ratio_value() -> float:
    """
    Returns envelope modulation ratio in ~0.3–5 Hz (proxy, not true infrasonics).
    We return the ratio so it can be calibrated, instead of hard boolean.
    """
    if len(audio_env) < 80:
        return 0.0
    env = np.array(audio_env, dtype=np.float32)
    env = env - float(np.mean(env))
    fft = np.abs(np.fft.rfft(env))
    freqs = np.fft.rfftfreq(len(env), d=AUDIO_WINDOW)
    band = fft[(freqs >= 0.3) & (freqs <= 5.0)]
    if len(band) == 0:
        return 0.0
    ratio = float(np.mean(band) / (np.mean(fft) + 1e-6))
    return ratio

def detect_sub_5hz_audio() -> bool:
    # calibrated threshold (warmup p95), fallback to old constant until ready
    ratio = sub5hz_ratio_value()
    thr = float(CAL.sub5hz_ratio_thr) if CAL.ready else 0.35
    return ratio > thr

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
        return

    if burst_active and hit:
        burst_last_hit_ts = now_ts
        burst_peak_db = max(burst_peak_db, float(audio_db))
        if is_spike: burst_spike_count += 1
        if is_subtle: burst_subtle_count += 1
        return

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

            if dur >= BURST_MIN_S:
                recent_bursts.appendleft(ended)

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
        frame_len = int(AUDIO_FS * 0.02)
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
    return float(np.clip(speech_e / total_e, 0.0, 1.0))

def _cosine_sim(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return float(np.dot(a, b) / ((np.linalg.norm(a) + 1e-9) * (np.linalg.norm(b) + 1e-9)))

def audio_fingerprint_band_energy(x, fs, n_bands=16, fmin=80, fmax=None):
    """
    More repeatable fingerprint:
    - normalize
    - coarser quantization (0..31) instead of 0..255
    - small floor to reduce noise-driven uniqueness
    """
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

    # floor + renorm
    floor = float(np.median(bands)) * 0.50
    bands = np.where(bands < floor, 0.0, bands)
    bands = bands / (float(np.sum(bands)) + 1e-9)

    q = np.clip(np.round(bands * 31.0), 0, 31).astype(np.uint8)
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
    # slightly coarser bins (20 Hz) improves repeatability
    qfreq = np.sort(np.round(top_freqs / 20.0).astype(np.int32))
    peak_str = ",".join(map(str, qfreq.tolist()))
    peak_hash = hashlib.sha1(peak_str.encode("utf-8")).hexdigest()[:16]
    return peak_hash, qfreq.tolist()

def log_fingerprint_row(now_ts, tick, db, fp_hash, peak_hash, fp_change, bands, ctx):
    with open(FPRINT_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            iso_ts(), f"{t_rel_s(now_ts):.3f}", tick,
            round(db, 1), fp_hash, peak_hash, round(fp_change, 3),
            ctx.get("gesture", ""),
            ctx.get("ble_mac", ""),
            ctx.get("ble_trend", ""),
            ctx.get("distance", ""),
            int(ctx.get("voice_active", False)),
            int(ctx.get("new_sound", False)),
            int(ctx.get("hf_appears", False)),
            int(ctx.get("audio_burst", False)),
            ctx.get("burst_id", ""),
            ctx.get("burst_peak_db", ""),
            ";".join(str(int(round(b * 1000))) for b in bands)
        ])

def audio_loop():
    global audio_db, voice_ratio, voice_active
    global bg_spec, novelty_hot_frac, new_sound_appears
    global hf_z, hf_appears
    global fp_chunks, last_fp_bands, last_fp_hash, last_peak_hash

    need_chunks = max(1, int(round(FP_SECONDS / AUDIO_WINDOW)))

    local_tick = 0
    while True:
        now_ts = time.time()
        audio = sd.rec(AUDIO_SAMPLES, samplerate=AUDIO_FS, channels=1, dtype="float32", blocking=True).reshape(-1)

        db = _rms_db(audio)
        audio_db = db
        audio_db_history.append(db)

        rms = float(np.sqrt(np.mean(audio ** 2) + 1e-12))
        audio_env.append(rms)

        vr = _voice_ratio_from_window(audio)
        voice_ratio_hist.append(vr)
        voice_ratio = float(np.mean(voice_ratio_hist)) if len(voice_ratio_hist) else 0.0
        voice_active = voice_ratio >= 0.55

        # novelty detector
        if db >= NOVELTY_MIN_DB:
            mag = _rfft_mag(audio, NFFT)
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

        # HF appears
        if db >= HF_MIN_DB and bg_spec is not None:
            mag = _rfft_mag(audio, NFFT)
            hf_e = _band_energy(mag, AUDIO_FS, NFFT, HF_BAND[0], HF_BAND[1])
            hf_hist.append(hf_e)
            base = float(np.median(hf_hist)) if len(hf_hist) >= 10 else hf_e
            hf_z = float((hf_e - base) / (base + 1e-6))
            hf_appears = hf_z >= 5.0
        else:
            hf_z = 0.0
            hf_appears = False

        update_audio_burst(now_ts, detect_audio_spike(), detect_subtle_sound())

        # fingerprints
        fp_chunks.append(audio.copy())
        if len(fp_chunks) >= need_chunks:
            seg = np.concatenate(fp_chunks, axis=0)
            fp_chunks.clear()

            bands, fp_hash = audio_fingerprint_band_energy(seg, AUDIO_FS, n_bands=16, fmin=80)
            peak_hash, _ = audio_fingerprint_peaks(seg, AUDIO_FS, nfft=2048, top_k=12, fmin=80)

            fp_change = 0.0
            if last_fp_bands is not None:
                fp_change = 1.0 - _cosine_sim(bands, last_fp_bands)
            last_fp_bands = bands
            last_fp_hash = fp_hash
            last_peak_hash = peak_hash

            with state_lock:
                ctx = dict(latest_state) if latest_state else {}

            log_fingerprint_row(now_ts, local_tick, db, fp_hash, peak_hash, fp_change, bands, ctx)

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

        local_tick += 1

# ======================
# BLE + MAC IDENTITY
# ======================
from bleak import BleakScanner

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

mac_profiles = defaultdict(dict)   # mac -> adv_fp -> stats
mac_last_advfp = {}
mac_last_rssi = {}
mac_suspicion_counts = defaultdict(int)
mac_suspicion_last_reason = {}
mac_suspicion_last_ts = {}
mac_lock = Lock()

PROFILE_SWITCH_WINDOW_S = 120.0
MAX_PROFILES_BEFORE_SUS = 2
RSSI_TELEPORT_DB = 25

# cooldown to stop repeated identical rows
mac_event_last_logged = {}
mac_event_lock = Lock()

def _cooldown_ok(key: tuple, now: float) -> bool:
    with mac_event_lock:
        last = mac_event_last_logged.get(key, 0.0)
        if now - last < MAC_EVENT_COOLDOWN_S:
            return False
        mac_event_last_logged[key] = now
        return True

def _get_rssi(device, adv):
    try:
        if adv is not None and hasattr(adv, "rssi") and adv.rssi is not None:
            return int(adv.rssi)
    except:
        pass
    try:
        if device is not None and hasattr(device, "rssi") and device.rssi is not None:
            return int(device.rssi)
    except:
        pass
    return None

def adv_fingerprint(device, adv):
    mfg = {}
    try:
        if getattr(adv, "manufacturer_data", None):
            for k, v in adv.manufacturer_data.items():
                mfg[str(k)] = bytes(v).hex()
    except:
        pass
    svc_data = {}
    try:
        if getattr(adv, "service_data", None):
            for k, v in adv.service_data.items():
                svc_data[str(k)] = bytes(v).hex() if isinstance(v, (bytes, bytearray)) else str(v)
    except:
        pass

    payload = {
        "name": getattr(adv, "local_name", None) or getattr(device, "name", None) or "",
        "svc": sorted(list(getattr(adv, "service_uuids", None) or [])),
        "mfg": mfg,
        "svc_data": svc_data,
        "tx": getattr(adv, "tx_power", None),
        "conn": getattr(adv, "connectable", None),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]

def mark_mac_suspicious(mac: str, reason: str):
    with mac_lock:
        mac_suspicion_counts[mac] += 1
        mac_suspicion_last_reason[mac] = reason
        mac_suspicion_last_ts[mac] = time.time()

def log_macid_event(now_ts, tick, mac, event, rssi, adv_fp, prev_fp, reason, state, profiles_seen):
    # throttle identical spam
    key = (mac, event, reason)
    if not _cooldown_ok(key, now_ts):
        return

    with open(MAC_ID_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            iso_ts(), f"{t_rel_s(now_ts):.3f}", tick,
            mac_for_log(mac),
            event,
            "" if rssi is None else rssi,
            adv_fp,
            prev_fp or "",
            profiles_seen,
            reason,
            state.get("gesture",""),
            state.get("distance",""),
            int(state.get("voice_active", False)),
            int(state.get("new_sound", False)),
            int(state.get("audio_burst", False)),
            state.get("audio_fp_hash","") or ""
        ])

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
    return (avg is not None) and (avg >= BLE_CLOSE_RSSI)

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

    adv_fp = adv_fingerprint(device, adv)
    prev_fp = mac_last_advfp.get(mac)
    prev_rssi = mac_last_rssi.get(mac)

    with mac_lock:
        prof = mac_profiles[mac].get(adv_fp)
        if prof is None:
            mac_profiles[mac][adv_fp] = {"first_seen": now, "last_seen": now, "count": 1, "last_rssi": rssi}
        else:
            prof["last_seen"] = now
            prof["count"] += 1
            prof["last_rssi"] = rssi

        mac_last_advfp[mac] = adv_fp
        mac_last_rssi[mac] = rssi
        profiles_seen = len(mac_profiles[mac])

    with state_lock:
        st = dict(latest_state) if latest_state else {}

    # MAC identity mismatch checks (THROTTLED)
    if prev_fp and prev_fp != adv_fp:
        old_last = mac_profiles[mac].get(prev_fp, {}).get("last_seen", 0)
        if (now - old_last) <= PROFILE_SWITCH_WINDOW_S:
            reason = f"profile_switched_within_{int(PROFILE_SWITCH_WINDOW_S)}s"
            log_macid_event(now, st.get("tick", 0), mac, "possible_clone_identity_mismatch", rssi, adv_fp, prev_fp, reason, st, profiles_seen)
            mark_mac_suspicious(mac, reason)

    if profiles_seen >= (MAX_PROFILES_BEFORE_SUS + 1):
        reason = f"multiple_adv_profiles={profiles_seen}"
        log_macid_event(now, st.get("tick", 0), mac, "possible_clone_identity_mismatch", rssi, adv_fp, prev_fp, reason, st, profiles_seen)
        mark_mac_suspicious(mac, reason)

    if prev_rssi is not None and abs(rssi - prev_rssi) >= RSSI_TELEPORT_DB:
        reason = f"rssi_jump_{abs(rssi - prev_rssi)}dB"
        log_macid_event(now, st.get("tick", 0), mac, "suspicious_rssi_teleport", rssi, adv_fp, prev_fp, reason, st, profiles_seen)
        mark_mac_suspicious(mac, reason)

    # Close / drop logic
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

        stc = ble_close_stats.get(mac, {})
        start_avg = stc.get("start_avg", None)
        last_avg = stc.get("last_avg", None)
        net_delta = (last_avg - start_avg) if (start_avg is not None and last_avg is not None) else None
        overall = "stable"
        if net_delta is not None:
            if net_delta >= BLE_TREND_DB: overall = "approaching"
            elif net_delta <= -BLE_TREND_DB: overall = "receding"

        ble_is_close[mac] = False
        ble_close_start.pop(mac, None)
        ble_close_stats.pop(mac, None)

        ble_drop_events.append({
            "ts": now, "mac": mac, "rssi": rssi, "reason": "rssi_fell",
            "duration_s": duration, "close_start_ts": start_ts, "close_end_ts": now,
            "close_start_avg": start_avg, "close_end_avg": last_avg, "close_net_delta": net_delta,
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

        stc = ble_close_stats.get(mac, {})
        start_avg = stc.get("start_avg", None)
        last_avg = stc.get("last_avg", None)
        net_delta = (last_avg - start_avg) if (start_avg is not None and last_avg is not None) else None
        overall = "stable"
        if net_delta is not None:
            if net_delta >= BLE_TREND_DB: overall = "approaching"
            elif net_delta <= -BLE_TREND_DB: overall = "receding"

        ble_is_close[mac] = False
        ble_close_start.pop(mac, None)
        ble_close_stats.pop(mac, None)

        ble_drop_events.append({
            "ts": now, "mac": mac, "rssi": None, "reason": "timeout",
            "duration_s": duration, "close_start_ts": start_ts, "close_end_ts": now,
            "close_start_avg": start_avg, "close_end_avg": last_avg, "close_net_delta": net_delta,
            "close_overall_trend": overall,
        })

# ======================
# WIFI (nmcli)
# ======================
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
    except:
        pass
    return None

def wifi_loop():
    while True:
        rssi = read_wifi_rssi()
        if rssi is not None:
            wifi_rssi.append(rssi)
        time.sleep(1)

# ======================
# SLEEPING + GESTURE
# ======================
GESTURE_LIST = ["sleeping", "idle", "presence_nearby", "listening", "talking", "moving", "unknown", "no-data"]

SLEEP_MIN_S = 8 * 60
SLEEP_WIFI_STD_MAX = 0.65
SLEEP_ENERGY_MAX = 1.2
SLEEP_AUDIO_DB_MAX = -55.0
SLEEP_WAKE_WIFI_STD = 1.5
SLEEP_WAKE_ENERGY = 2.0
SLEEP_WAKE_BLE_DELTA = 6.0

class SleepDetector:
    def __init__(self):
        self.sleeping = False
        self.quiet_start_ts = None
        self.sleep_start_ts = None
        self.last_reason = ""

    def update(self, now_ts: float, *, wifi_std: float, energy: float,
               audio_db: float, voice_active: bool, new_sound: bool,
               hf_appears: bool, audio_burst: bool,
               ble_trend: str, ble_trend_delta: float) -> bool:

        wake = (
            voice_active or new_sound or hf_appears or audio_burst or
            (wifi_std >= SLEEP_WAKE_WIFI_STD) or
            (energy >= SLEEP_WAKE_ENERGY) or
            (ble_trend in ("approaching", "receding") and abs(ble_trend_delta) >= SLEEP_WAKE_BLE_DELTA)
        )

        if self.sleeping and wake:
            self.sleeping = False
            self.quiet_start_ts = None
            self.sleep_start_ts = None
            self.last_reason = "wake_event"
            return self.sleeping

        quiet_and_still = (
            (audio_db <= SLEEP_AUDIO_DB_MAX) and
            (wifi_std <= SLEEP_WIFI_STD_MAX) and
            (energy <= SLEEP_ENERGY_MAX) and
            (not voice_active) and (not new_sound) and (not hf_appears) and (not audio_burst)
        )

        if not self.sleeping:
            if quiet_and_still:
                if self.quiet_start_ts is None:
                    self.quiet_start_ts = now_ts
                    self.last_reason = "quiet_start"
                elif (now_ts - self.quiet_start_ts) >= SLEEP_MIN_S:
                    self.sleeping = True
                    self.sleep_start_ts = now_ts
                    self.last_reason = "sleep_confirmed"
            else:
                self.quiet_start_ts = None
                self.last_reason = "not_quiet"

        return self.sleeping

    def age_s(self, now_ts: float) -> float:
        if not self.sleeping or self.sleep_start_ts is None:
            return 0.0
        return float(now_ts - self.sleep_start_ts)

sleep_detector = SleepDetector()

def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data", 0.0, 0.0

    sig = np.array(list(wifi_rssi)[-40:], dtype=np.float32)
    short = sig[-10:]
    short_std = float(np.std(short))

    rate = ble_rate()
    energy = float(short_std + rate * 0.3)

    if short_std < 0.8 and rate == 0:
        return "idle", energy, short_std
    if short_std < 1.0 and detect_sub_5hz_audio():
        return "presence_nearby", energy, short_std
    if short_std < 1.2 and audio_active_fn():
        return "listening", energy, short_std
    if short_std > 1.2 and audio_active_fn():
        return "talking", energy, short_std
    if short_std > 2.0:
        return "moving", energy, short_std
    return "unknown", energy, short_std

def infer_sound_distance():
    if len(audio_db_history) < 8 or len(wifi_rssi) < 20:
        return "unknown"
    da = float(audio_db_history[-1] - audio_db_history[-8])
    rf_now = float(np.mean(list(wifi_rssi)[-10:]))
    rf_prev = float(np.mean(list(wifi_rssi)[-20:-10]))
    drf = rf_now - rf_prev
    if da > 3 and drf > 1:
        return "approaching"
    if da < -3 and drf < -1:
        return "receding"
    return "stable"

def build_state(tick: int):
    now_ts = time.time()
    gesture, energy, wifi_std = classify_gesture()
    mac, avg_rssi, ble_close, ble_tr, ble_tr_delta = get_closest_ble()
    binfo = burst_snapshot(now_ts)

    # update calibrator during warmup
    CAL.update(
        now_ts,
        energy=float(energy),
        sub5hz_ratio=float(sub5hz_ratio_value()),
        audio_db=float(audio_db)
    )

    # rf_motion calibrated to avoid "always-on"
    rf_thr = float(CAL.rf_motion_energy_thr) if CAL.ready else 1.2
    rf_motion = bool(energy > rf_thr)

    is_sleeping = sleep_detector.update(
        now_ts,
        wifi_std=float(wifi_std),
        energy=float(energy),
        audio_db=float(audio_db),
        voice_active=bool(voice_active),
        new_sound=bool(new_sound_appears),
        hf_appears=bool(hf_appears),
        audio_burst=bool(binfo["audio_burst"]),
        ble_trend=str(ble_tr),
        ble_trend_delta=float(ble_tr_delta),
    )
    if is_sleeping:
        gesture = "sleeping"

    return {
        "iso_ts": iso_ts(),
        "t_rel_s": round(t_rel_s(now_ts), 3),
        "tick": int(tick),
        "ts": now_ts,

        "gesture": gesture,
        "energy": round(float(energy), 2),
        "wifi_std": round(float(wifi_std), 3),
        "sleep_age_s": round(sleep_detector.age_s(now_ts), 1) if is_sleeping else 0.0,

        "audio_db": round(float(audio_db), 1),
        "audio_active": bool(audio_active_fn()),
        "audio_spike": bool(detect_audio_spike()),
        "audio_subtle": bool(detect_subtle_sound()),
        "audio_sub5hz": bool(detect_sub_5hz_audio()),
        "sub5hz_ratio": round(float(sub5hz_ratio_value()), 4),

        "audio_burst": bool(binfo["audio_burst"]),
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

        "ble_rate": int(ble_rate()),
        "ble_close": bool(ble_close),
        "ble_mac": mac_for_log(mac or ""),
        "ble_rssi_avg": round(avg_rssi, 1) if avg_rssi is not None else "",
        "ble_trend": str(ble_tr),
        "ble_trend_delta": round(float(ble_tr_delta), 1),

        "rf_motion": bool(rf_motion),
        "rf_motion_thr": round(float(rf_thr), 3),
        "distance": infer_sound_distance(),

        "audio_fp_hash": last_fp_hash or "",
        "audio_peak_hash": last_peak_hash or "",
    }

# ======================
# CROSS-LAYER RULES + DISCOVERY
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
}

pattern_counts = defaultdict(int)
ble_sig_counts = defaultdict(int)

def auto_discover(state):
    active_keys = [k for k, v in state.items() if isinstance(v, bool) and v]
    for i in range(len(active_keys)):
        for j in range(i + 1, len(active_keys)):
            pattern_counts[f"{active_keys[i]}+{active_keys[j]}"] += 1

def discovered_patterns():
    return [k for k, v in pattern_counts.items() if v >= DISCOVERY_THRESHOLD]

def discover_ble_signature(mac: str, state: dict):
    mac_show = mac_for_log(mac)
    sig = (
        f"mac:{mac_show}|ble:{state['ble_trend']}({state['ble_trend_delta']})|dist:{state['distance']}|"
        f"gesture:{state['gesture']}|voice:{int(state['voice_active'])}|new:{int(state['new_sound'])}|"
        f"hf:{int(state['hf_appears'])}|burst:{int(state['audio_burst'])}"
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
        except:
            pass
    auto_discover(state)
    return active

# ======================
# Correlation (unchanged logic, better timestamps)
# ======================
HIST_S = 60.0
MAX_LAG_S = 6.0
CORR_MIN_SCORE = 0.25
CORR_REPEAT_THRESH = 8

state_hist = deque(maxlen=int(HIST_S / TICK_S) + 5)
corr_counts = defaultdict(int)
EVENT_KEYS = ["audio_burst", "new_sound", "voice_active", "ble_close", "hf_appears"]

def _corr_best_lag(x: np.ndarray, y: np.ndarray, max_lag: int):
    x = x.astype(np.float32)
    y = y.astype(np.float32)
    if x.sum() < 2 or y.sum() < 2:
        return 0, 0.0
    x = x - x.mean()
    y = y - y.mean()
    best_lag, best = 0, -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            xs = x[-lag:]
            ys = y[:len(xs)]
        elif lag > 0:
            xs = x[:-lag]
            ys = y[lag:]
        else:
            xs = x
            ys = y
        if len(xs) < 10:
            continue
        score = float(np.dot(xs, ys) / ((np.linalg.norm(xs)+1e-9) * (np.linalg.norm(ys)+1e-9)))
        if score > best:
            best = score
            best_lag = lag
    return best_lag, best

def compute_gesture_event_correlations():
    if len(state_hist) < int(10 / TICK_S):
        return []
    gestures = [s.get("gesture", "unknown") for s in state_hist]
    max_lag_steps = int(MAX_LAG_S / TICK_S)

    results = []
    for g in GESTURE_LIST:
        x = np.array([1 if gg == g else 0 for gg in gestures], dtype=np.int32)
        for ek in EVENT_KEYS:
            y = np.array([1 if bool(s.get(ek, False)) else 0 for s in state_hist], dtype=np.int32)
            lag, score = _corr_best_lag(x, y, max_lag_steps)
            lag_s = lag * TICK_S
            if score >= CORR_MIN_SCORE:
                results.append({"gesture": g, "event": ek, "lag_s": lag_s, "score": float(score)})

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:12]

def log_corr_rows(corrs):
    with open(CORR_FILE, "a", newline="") as f:
        w = csv.writer(f)
        for r in corrs[:8]:
            w.writerow([iso_ts(), r["gesture"], r["event"], f"{r['lag_s']:.2f}", f"{r['score']:.3f}"])
            key = (r["gesture"], r["event"], int(round(r["lag_s"]/TICK_S)))
            corr_counts[key] += 1

def learned_corr_rules():
    items = [(*k, v) for k, v in corr_counts.items() if v >= CORR_REPEAT_THRESH]
    items.sort(key=lambda t: t[-1], reverse=True)
    out = []
    for gesture, event, lag_steps, cnt in items[:8]:
        out.append(f"{gesture} ↔ {event} lag={lag_steps*TICK_S:+.1f}s  (x{cnt})")
    return out

# ======================
# ML features (same, plus better columns)
# ======================
def safe_float(x, default=0.0):
    try:
        if x == "" or x is None:
            return float(default)
        return float(x)
    except:
        return float(default)

FEATURE_COLUMNS = [
    "audio_db","voice_ratio","novelty_hot_frac","hf_z",
    "energy","ble_rate","ble_close","ble_rssi_avg","ble_trend_delta",
    "audio_spike","audio_subtle","audio_sub5hz","audio_burst","new_sound","voice_active","hf_appears",
    "rf_motion",
    "sub5hz_ratio",
]

def feature_dict_for_ml(state: dict) -> dict:
    d = {
        "audio_db": safe_float(state.get("audio_db", -100.0)),
        "voice_ratio": safe_float(state.get("voice_ratio", 0.0)),
        "novelty_hot_frac": safe_float(state.get("novelty_hot_frac", 0.0)),
        "hf_z": safe_float(state.get("hf_z", 0.0)),
        "energy": safe_float(state.get("energy", 0.0)),
        "ble_rate": safe_float(state.get("ble_rate", 0.0)),
        "ble_close": 1.0 if state.get("ble_close", False) else 0.0,
        "ble_rssi_avg": safe_float(state.get("ble_rssi_avg", 0.0)),
        "ble_trend_delta": safe_float(state.get("ble_trend_delta", 0.0)),
        "audio_spike": 1.0 if state.get("audio_spike", False) else 0.0,
        "audio_subtle": 1.0 if state.get("audio_subtle", False) else 0.0,
        "audio_sub5hz": 1.0 if state.get("audio_sub5hz", False) else 0.0,
        "audio_burst": 1.0 if state.get("audio_burst", False) else 0.0,
        "new_sound": 1.0 if state.get("new_sound", False) else 0.0,
        "voice_active": 1.0 if state.get("voice_active", False) else 0.0,
        "hf_appears": 1.0 if state.get("hf_appears", False) else 0.0,
        "rf_motion": 1.0 if state.get("rf_motion", False) else 0.0,
        "sub5hz_ratio": safe_float(state.get("sub5hz_ratio", 0.0)),
    }
    gest = state.get("gesture", "unknown")
    for g in GESTURE_LIST:
        d[f"g_{g}"] = 1.0 if gest == g else 0.0
    return d

def feature_vector_for_online_model(state: dict) -> np.ndarray:
    d = feature_dict_for_ml(state)
    base = [d[c] for c in FEATURE_COLUMNS]
    onehot = [d[f"g_{g}"] for g in GESTURE_LIST]
    return np.array(base + onehot, dtype=np.float32)

class OnlineKMeans:
    def __init__(self, k=8, lr=0.05):
        self.k = int(k)
        self.lr = float(lr)
        self.centroids = None
        self.counts = None
        self.ready = False
        self.dist_mu = 0.0
        self.dist_var = 1.0
        self.dist_alpha = 0.02

    def _init(self, X):
        if len(X) < self.k:
            return
        self.centroids = np.stack(X[:self.k], axis=0).copy()
        self.counts = np.ones(self.k, dtype=np.int32)
        self.ready = True

    def partial_fit(self, x: np.ndarray):
        if not self.ready:
            return None, None
        d = np.linalg.norm(self.centroids - x[None, :], axis=1)
        j = int(np.argmin(d))
        dist = float(d[j])

        eta = self.lr
        self.centroids[j] = (1.0 - eta) * self.centroids[j] + eta * x
        self.counts[j] += 1

        mu = self.dist_mu
        var = self.dist_var
        a = self.dist_alpha
        mu2 = (1.0 - a) * mu + a * dist
        var2 = (1.0 - a) * var + a * ((dist - mu2) ** 2)
        self.dist_mu, self.dist_var = float(mu2), float(max(var2, 1e-6))

        z = (dist - self.dist_mu) / (np.sqrt(self.dist_var) + 1e-9)
        return j, float(z)

    def score_only(self, x: np.ndarray):
        if not self.ready or self.centroids is None:
            return None, None
        d = np.linalg.norm(self.centroids - x[None, :], axis=1)
        j = int(np.argmin(d))
        dist = float(d[j])
        z = (dist - self.dist_mu) / (np.sqrt(self.dist_var) + 1e-9)
        return j, float(z)

    def to_json(self):
        if not self.ready:
            return {"ready": False}
        return {
            "ready": True,
            "k": self.k,
            "lr": self.lr,
            "centroids": self.centroids.tolist(),
            "counts": self.counts.tolist(),
            "dist_mu": self.dist_mu,
            "dist_var": self.dist_var
        }

model_lock = Lock()
online_model = OnlineKMeans(k=8, lr=0.05)
online_warmup = []

# ======================
# Offline anomaly scorer (optional)
# ======================
class OfflineAnomalyScorer:
    def __init__(self, model_path: Path, meta_path: Path):
        from joblib import load
        self.model = load(str(model_path))
        meta = json.loads(meta_path.read_text())
        self.feature_cols = list(meta["feature_cols"])
        self.threshold = float(meta["threshold"])
        self.contamination = float(meta.get("contamination", 0.01))

    def vector_from_dict(self, feat_dict: dict) -> np.ndarray:
        return np.array([float(feat_dict.get(c, 0.0)) for c in self.feature_cols], dtype=np.float32)

    def score_vec(self, x: np.ndarray):
        x = np.asarray(x, dtype=np.float32).reshape(1, -1)
        normality = float(self.model.decision_function(x)[0])
        anomaly_score = -normality
        is_anom = anomaly_score >= self.threshold
        return anomaly_score, is_anom

OFFLINE_SCORER = None
OFFLINE_MODEL_ERR = ""

def try_load_offline_model():
    global OFFLINE_SCORER, OFFLINE_MODEL_ERR
    OFFLINE_SCORER = None
    OFFLINE_MODEL_ERR = ""
    if not (MODEL_JOBLIB.exists() and MODEL_META.exists()):
        OFFLINE_MODEL_ERR = "no_model_files"
        return
    try:
        OFFLINE_SCORER = OfflineAnomalyScorer(MODEL_JOBLIB, MODEL_META)
    except Exception as e:
        OFFLINE_SCORER = None
        OFFLINE_MODEL_ERR = f"load_failed:{type(e).__name__}"

# ======================
# LOGGING (headers include iso_ts,t_rel_s,tick everywhere)
# ======================
def ensure_logs():
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "iso_ts","t_rel_s","tick",
                "gesture","energy","wifi_std","sleep_age_s",
                "audio_db","audio_active","audio_spike","audio_subtle","audio_sub5hz","sub5hz_ratio",
                "audio_burst","burst_id","burst_age_s","burst_peak_db","burst_spike_count","burst_subtle_count",
                "voice_ratio","voice_active","novelty_hot_frac","new_sound","hf_z","hf_appears",
                "rf_motion","rf_motion_thr",
                "ble_rate","ble_close","ble_mac","ble_rssi_avg","ble_trend","ble_trend_delta","distance",
                "audio_fp_hash","audio_peak_hash",
                "cross_layers"
            ])

    if not DISCOVERY_FILE.exists():
        with open(DISCOVERY_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "iso_ts","t_rel_s","tick",
                "event","ble_mac","ble_rssi","ble_rssi_avg","ble_trend","ble_trend_delta",
                "gesture","distance","audio_db","voice_ratio","voice_active","new_sound","novelty_hot_frac",
                "hf_appears","hf_z","audio_burst","burst_id","burst_peak_db",
                "signature","signature_count",
                "close_start_ts","close_end_ts","close_duration_s",
                "close_start_avg","close_end_avg","close_net_delta","close_overall_trend","drop_reason"
            ])

    if not FPRINT_FILE.exists():
        with open(FPRINT_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "iso_ts","t_rel_s","tick",
                "audio_db","fp_hash","peak_hash","fp_change",
                "gesture","ble_mac","ble_trend","distance",
                "voice_active","new_sound","hf_appears","audio_burst","burst_id","burst_peak_db",
                "bands_16"
            ])

    if not MAC_ID_FILE.exists():
        with open(MAC_ID_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "iso_ts","t_rel_s","tick",
                "mac","event","rssi","adv_fp","prev_adv_fp","profiles_seen","reason",
                "gesture","distance","voice_active","new_sound","audio_burst","audio_fp_hash"
            ])

    if not CORR_FILE.exists():
        with open(CORR_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["iso_ts","gesture","event","best_lag_s","score"])

    if not FEAT_FILE.exists():
        cols = ["iso_ts","t_rel_s","tick"] + FEATURE_COLUMNS + [f"g_{g}" for g in GESTURE_LIST] + ["ble_mac","distance","audio_fp_hash","audio_peak_hash"]
        with open(FEAT_FILE, "w", newline="") as f:
            csv.writer(f).writerow(cols)

    if not ANOM_FILE.exists():
        with open(ANOM_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "iso_ts","t_rel_s","tick",
                "mode","anomaly_score","threshold","is_anomaly",
                "gesture","distance",
                "ble_mac","ble_trend","ble_rssi_avg",
                "audio_db","voice_ratio",
                "new_sound","hf_appears","audio_burst",
                "audio_fp_hash","audio_peak_hash"
            ])

    if not EVENTS_FILE.exists():
        with open(EVENTS_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "iso_ts","t_rel_s","tick",
                "event","value","details"
            ])

def log_state_row(state: dict, cross: list):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            state["iso_ts"], state["t_rel_s"], state["tick"],
            state["gesture"], state["energy"], state["wifi_std"], state["sleep_age_s"],
            state["audio_db"], int(state["audio_active"]), int(state["audio_spike"]), int(state["audio_subtle"]), int(state["audio_sub5hz"]), state["sub5hz_ratio"],
            int(state["audio_burst"]), state["burst_id"], state["burst_age_s"], state["burst_peak_db"],
            state["burst_spike_count"], state["burst_subtle_count"],
            state["voice_ratio"], int(state["voice_active"]),
            state["novelty_hot_frac"], int(state["new_sound"]),
            state["hf_z"], int(state["hf_appears"]),
            int(state["rf_motion"]), state["rf_motion_thr"],
            state["ble_rate"], int(state["ble_close"]),
            state["ble_mac"], state["ble_rssi_avg"], state["ble_trend"], state["ble_trend_delta"], state["distance"],
            state.get("audio_fp_hash",""),
            state.get("audio_peak_hash",""),
            ";".join(cross)
        ])

def log_feature_row(state: dict, feat_dict: dict):
    row = [state["iso_ts"], state["t_rel_s"], state["tick"]]
    row += [feat_dict[c] for c in FEATURE_COLUMNS]
    row += [feat_dict[f"g_{g}"] for g in GESTURE_LIST]
    row += [state.get("ble_mac",""), state.get("distance",""), state.get("audio_fp_hash",""), state.get("audio_peak_hash","")]
    with open(FEAT_FILE, "a", newline="") as f:
        csv.writer(f).writerow(row)

def log_discovery_row(state: dict, event: str, mac: str, rssi, sig: str, sig_count: int,
                      close_start_ts=None, close_end_ts=None, close_duration_s=None,
                      close_start_avg=None, close_end_avg=None, close_net_delta=None,
                      close_overall_trend="stable", drop_reason=""):
    with open(DISCOVERY_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            state["iso_ts"], state["t_rel_s"], state["tick"],
            event, mac_for_log(mac), "" if rssi is None else rssi,
            state["ble_rssi_avg"], state["ble_trend"], state["ble_trend_delta"],
            state["gesture"], state["distance"], state["audio_db"], state["voice_ratio"], int(state["voice_active"]),
            int(state["new_sound"]), state["novelty_hot_frac"], int(state["hf_appears"]), state["hf_z"],
            int(state["audio_burst"]), state["burst_id"], state["burst_peak_db"],
            sig, sig_count,
            "" if close_start_ts is None else f"{close_start_ts:.3f}",
            "" if close_end_ts is None else f"{close_end_ts:.3f}",
            "" if close_duration_s is None else f"{close_duration_s:.3f}",
            "" if close_start_avg is None else round(float(close_start_avg), 1),
            "" if close_end_avg is None else round(float(close_end_avg), 1),
            "" if close_net_delta is None else round(float(close_net_delta), 1),
            close_overall_trend, drop_reason
        ])

def log_event(state: dict, name: str, value, details: str = ""):
    with open(EVENTS_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            state["iso_ts"], state["t_rel_s"], state["tick"],
            name, value, details
        ])

def save_online_model_snapshot():
    try:
        with model_lock:
            data = online_model.to_json()
        MODEL_SNAPSHOT.write_text(json.dumps(data, indent=2))
    except:
        pass

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
        log_discovery_row(state, "ble_close", mac, rssi, sig, sig_count, close_start_ts=ble_close_start.get(mac, ev["ts"]))
        recent_events.appendleft(f"CLOSE mac:{mac_tail(mac)} rssi:{rssi} ble:{state['ble_trend']} gest:{state['gesture']} ({sig_count}x)")

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

        close_start_ts = ev.get("close_start_ts", None)
        close_end_ts = ev.get("close_end_ts", ev["ts"])
        close_start_avg = ev.get("close_start_avg", None)
        close_end_avg = ev.get("close_end_avg", None)
        close_net_delta = ev.get("close_net_delta", None)
        close_overall_trend = ev.get("close_overall_trend", "stable")

        sig, sig_count = discover_ble_signature(mac, state)
        log_discovery_row(
            state, "ble_drop", mac, rssi, sig, sig_count,
            close_start_ts=close_start_ts, close_end_ts=close_end_ts, close_duration_s=duration_s,
            close_start_avg=close_start_avg, close_end_avg=close_end_avg, close_net_delta=close_net_delta,
            close_overall_trend=close_overall_trend, drop_reason=reason
        )
        dur_txt = f"{duration_s:.1f}s" if duration_s is not None else "?"
        recent_events.appendleft(f"DROP mac:{mac_tail(mac)} dur:{dur_txt} reason:{reason} ({sig_count}x)")

# ======================
# TRANSITION LOGGER (key for clean data)
# ======================
class TransitionTracker:
    def __init__(self):
        self.prev = None

    def diff(self, state: dict):
        if self.prev is None:
            self.prev = dict(state)
            return

        # gesture changes
        if state.get("gesture") != self.prev.get("gesture"):
            log_event(state, "gesture_change", state.get("gesture"), f"from={self.prev.get('gesture')}")

        # boolean transitions
        for k in ["audio_burst","ble_close","voice_active","new_sound","hf_appears","rf_motion"]:
            if bool(state.get(k)) != bool(self.prev.get(k)):
                log_event(state, f"{k}_toggle", int(bool(state.get(k))), f"from={int(bool(self.prev.get(k)))}")

        # sleeping start/end via gesture label (more reliable)
        was_sleep = (self.prev.get("gesture") == "sleeping")
        is_sleep = (state.get("gesture") == "sleeping")
        if is_sleep != was_sleep:
            log_event(state, "sleeping_toggle", int(is_sleep), "")

        self.prev = dict(state)

TRANS = TransitionTracker()

# ======================
# DATA HEALTH SNAPSHOT
# ======================
class HealthTracker:
    def __init__(self):
        self.count = 0
        self.true_counts = defaultdict(int)
        self.last_write = 0.0

    def update(self, state: dict):
        self.count += 1
        for k in ["audio_sub5hz","rf_motion","ble_close","audio_burst","new_sound","voice_active","hf_appears"]:
            if bool(state.get(k)):
                self.true_counts[k] += 1

    def maybe_write(self, now_ts: float):
        if now_ts - self.last_write < HEALTH_SNAPSHOT_EVERY_S:
            return
        self.last_write = now_ts
        n = max(self.count, 1)
        frac = {k: round(self.true_counts[k] / n, 4) for k in self.true_counts.keys()}
        data = {
            "run_id": RUN_ID,
            "run_ts": RUN_TS,
            "samples": n,
            "tick_s": TICK_S,
            "state_log_every_s": STATE_LOG_EVERY_S,
            "baseline": CAL.to_dict(),
            "fractions_true": frac,
            "note": "If any fraction is ~0.99+ or ~0.00, feature may be stuck (check calibration/thresholds).",
        }
        try:
            HEALTH_FILE.write_text(json.dumps(data, indent=2))
        except:
            pass

HEALTH = HealthTracker()

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cross-Layer Dashboard (Refactor v2: clean logs + transitions)")
        self.label = QLabel("Starting…")
        self.label.setStyleSheet("font-family: monospace;")
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

        self.last_model_save = 0.0
        self.last_state_log = 0.0

        self.cluster_id = None
        self.anomaly_z = None

        self.last_corrs = []
        self.ml_mode = "fallback"
        self.ml_score = 0.0
        self.ml_thr = 3.0
        self.ml_is_anom = False

        self.tick = 0

    def update_view(self):
        check_ble_timeouts()

        state = build_state(self.tick)

        with state_lock:
            latest_state.clear()
            latest_state.update(state)

        state_hist.append(state)
        cross = detect_cross_layers(state)

        handle_ble_close_events(state)
        handle_ble_drop_events(state)

        # transitions always logged
        TRANS.diff(state)

        # reduced spam state logging: 1 Hz OR if something important changed
        now_ts = state["ts"]
        important = (
            state.get("audio_burst") or state.get("new_sound") or state.get("hf_appears") or
            state.get("voice_active") or state.get("ble_close")
        )
        if (now_ts - self.last_state_log) >= STATE_LOG_EVERY_S or important:
            log_state_row(state, cross)
            self.last_state_log = now_ts

        # correlations (~1 Hz)
        if int(time.time()) % 1 == 0:
            self.last_corrs = compute_gesture_event_correlations()
            if self.last_corrs:
                log_corr_rows(self.last_corrs)

        learned = learned_corr_rules()

        # online clustering + fallback anomaly z
        x_online = feature_vector_for_online_model(state)
        with model_lock:
            if not online_model.ready:
                online_warmup.append(x_online.copy())
                if len(online_warmup) >= online_model.k:
                    online_model._init(online_warmup)
            cid, az = online_model.score_only(x_online)
            if online_model.ready:
                cid, az = online_model.partial_fit(x_online)
            self.cluster_id = cid
            self.anomaly_z = az

        feat_dict = feature_dict_for_ml(state)
        log_feature_row(state, feat_dict)

        # save model snapshot occasionally
        if time.time() - self.last_model_save > 20.0:
            save_online_model_snapshot()
            self.last_model_save = time.time()

        # Offline anomaly scoring (if present), else fallback
        if OFFLINE_SCORER is not None:
            self.ml_mode = "offline"
            v = OFFLINE_SCORER.vector_from_dict(feat_dict)
            score, is_anom = OFFLINE_SCORER.score_vec(v)
            self.ml_score = float(score)
            self.ml_thr = float(OFFLINE_SCORER.threshold)
            self.ml_is_anom = bool(is_anom)
        else:
            self.ml_mode = "fallback"
            self.ml_score = float(self.anomaly_z) if self.anomaly_z is not None else 0.0
            self.ml_thr = 3.0
            self.ml_is_anom = (self.anomaly_z is not None) and (self.anomaly_z > 3.0)

        if self.ml_is_anom:
            with open(ANOM_FILE, "a", newline="") as f:
                csv.writer(f).writerow([
                    state["iso_ts"], state["t_rel_s"], state["tick"],
                    self.ml_mode,
                    f"{self.ml_score:.6f}",
                    f"{self.ml_thr:.6f}",
                    1,
                    state.get("gesture",""),
                    state.get("distance",""),
                    state.get("ble_mac",""),
                    state.get("ble_trend",""),
                    state.get("ble_rssi_avg",""),
                    state.get("audio_db",""),
                    state.get("voice_ratio",""),
                    int(state.get("new_sound", False)),
                    int(state.get("hf_appears", False)),
                    int(state.get("audio_burst", False)),
                    state.get("audio_fp_hash",""),
                    state.get("audio_peak_hash",""),
                ])
            log_event(state, "ml_anomaly", 1, f"mode={self.ml_mode} score={self.ml_score:.3f} thr={self.ml_thr:.3f}")

        # data health snapshots
        HEALTH.update(state)
        HEALTH.maybe_write(now_ts)

        # display
        cid_txt = "?" if self.cluster_id is None else str(self.cluster_id)
        az_txt = "?" if self.anomaly_z is None else f"{self.anomaly_z:+.2f}"
        offline_status = "loaded" if OFFLINE_SCORER is not None else f"off({OFFLINE_MODEL_ERR})"

        ble_sigs = discovered_ble_signatures()
        sig_lines = [f"• ({cnt}x) {sig[:120]}{'...' if len(sig) > 120 else ''}" for sig, cnt in ble_sigs]
        generic = discovered_patterns()[-6:]
        evt_lines = list(recent_events)[:6]

        self.label.setText(
            f"Run ID        : {RUN_ID}\n"
            f"Logs:\n"
            f"  {LOG_FILE}\n  {EVENTS_FILE}\n  {DISCOVERY_FILE}\n  {FPRINT_FILE}\n  {MAC_ID_FILE}\n"
            f"  {CORR_FILE}\n  {FEAT_FILE}\n  {MODEL_SNAPSHOT}\n  {ANOM_FILE}\n  {HEALTH_FILE}\n\n"
            f"Offline model : {offline_status}\n"
            f"MAC logging   : {'RAW' if LOG_RAW_MAC else 'MASKED'}\n"
            f"Baseline cal  : ready={int(CAL.ready)} rf_thr={CAL.rf_motion_energy_thr:.3f} sub5hz_thr={CAL.sub5hz_ratio_thr:.4f}\n\n"
            f"Gesture        : {state['gesture']} (sleep_age={state['sleep_age_s']:.1f}s)\n"
            f"Energy         : {state['energy']} wifi_std={state['wifi_std']} rf_motion={int(state['rf_motion'])} thr={state['rf_motion_thr']}\n"
            f"Audio dB       : {state['audio_db']}  sub5hz={int(state['audio_sub5hz'])} ratio={state['sub5hz_ratio']}\n"
            f"Voice          : {int(state['voice_active'])} (ratio={state['voice_ratio']})  VAD={'on' if HAVE_VAD else 'fallback'}\n"
            f"New sound      : {int(state['new_sound'])} (hot={state['novelty_hot_frac']})\n"
            f"HF appears     : {int(state['hf_appears'])} (z={state['hf_z']}) band={HF_BAND[0]}-{HF_BAND[1]}Hz\n"
            f"Burst          : {int(state['audio_burst'])} id:{state['burst_id']} peak:{state['burst_peak_db']}\n"
            f"BLE closest    : {state['ble_mac'] if state['ble_mac'] else 'none'}\n"
            f"BLE rssi(avg)  : {state['ble_rssi_avg']} close:{int(state['ble_close'])} trend:{state['ble_trend']} d:{state['ble_trend_delta']}\n"
            f"Distance       : {state['distance']}\n\n"
            f"Online behavior: cluster={cid_txt} anomaly_z={az_txt}\n"
            f"Anomaly (ML)   : mode={self.ml_mode} score={self.ml_score:.3f} thr={self.ml_thr:.3f} is_anom={int(self.ml_is_anom)}\n\n"
            f"Recent BLE events:\n" + ("\n".join(f"• {e}" for e in evt_lines) if evt_lines else "• (none)") +
            "\n\nDiscovered BLE signatures:\n" + ("\n".join(sig_lines) if sig_lines else "• (none yet)") +
            "\n\nGeneric auto-discovered:\n" + ("\n".join(f"• {d}" for d in generic) if generic else "• (none yet)") +
            "\n\nLearned corr rules:\n" + ("\n".join(f"• {r}" for r in learned) if learned else "• (none yet)")
        )

        self.tick += 1

# ======================
# RUN META (write once)
# ======================
def write_run_meta():
    meta = {
        "run_id": RUN_ID,
        "run_ts": RUN_TS,
        "started_iso": iso_ts(),
        "tick_s": TICK_S,
        "state_log_every_s": STATE_LOG_EVERY_S,
        "baseline_warmup_s": BASELINE_WARMUP_S,
        "privacy": {"log_raw_mac": LOG_RAW_MAC, "mac_salt_set": bool(MAC_SALT)},
        "audio": {"fs": AUDIO_FS, "window_s": AUDIO_WINDOW, "nfft": NFFT, "hf_band_hz": HF_BAND},
        "ble": {"close_rssi": BLE_CLOSE_RSSI, "trend_window": BLE_TREND_WINDOW, "trend_db": BLE_TREND_DB, "drop_timeout_s": BLE_DROP_TIMEOUT},
        "sleep": {
            "min_s": SLEEP_MIN_S, "wifi_std_max": SLEEP_WIFI_STD_MAX, "energy_max": SLEEP_ENERGY_MAX,
            "audio_db_max": SLEEP_AUDIO_DB_MAX
        },
        "platform": {
            "python": sys.version.split()[0],
            "os": platform.platform(),
            "machine": platform.machine(),
        },
        "versions": {},
    }
    # best-effort library versions
    for name, mod in [("numpy", np), ("sounddevice", sd)]:
        try:
            meta["versions"][name] = getattr(mod, "__version__", "unknown")
        except:
            meta["versions"][name] = "unknown"
    try:
        import bleak
        meta["versions"]["bleak"] = getattr(bleak, "__version__", "unknown")
    except:
        pass
    try:
        import PyQt5
        meta["versions"]["PyQt5"] = getattr(PyQt5, "__version__", "unknown")
    except:
        pass

    try:
        RUN_META_FILE.write_text(json.dumps(meta, indent=2))
    except:
        pass

# ======================
# MAIN
# ======================
def main():
    ensure_logs()
    write_run_meta()
    try_load_offline_model()

    threading.Thread(target=audio_loop, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()
    threading.Thread(target=wifi_loop, daemon=True).start()

    app = QApplication(sys.argv)
    gui = Dashboard()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(int(TICK_S * 1000))

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
