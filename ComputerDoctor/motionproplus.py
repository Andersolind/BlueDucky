import sys, time, threading, asyncio, subprocess, os, csv
import numpy as np
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

# ======================
# SAFETY (Linux)
# ======================
if os.geteuid() == 0:
    print("❌ Do NOT run with sudo")
    sys.exit(1)

# ======================
# OUTPUT FILES (timestamped per run)
# ======================
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = Path("logs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = OUT_DIR / f"crosslayer_activity_{RUN_TS}.csv"
DISCOVERY_FILE = OUT_DIR / f"ble_audio_discoveries_{RUN_TS}.csv"

# ======================
# AUDIO (LEVEL + SUB-5HZ ENVELOPE + BURSTS)
# ======================
import sounddevice as sd

AUDIO_FS = 16000
AUDIO_WINDOW = 0.1  # seconds
GUI_TICK_S = 0.5    # 500 ms

audio_db = -100.0
audio_db_history = deque(maxlen=120)  # ~12 sec
audio_env = deque(maxlen=300)         # ~30 sec envelope RMS

def audio_loop():
    global audio_db
    while True:
        audio = sd.rec(
            int(AUDIO_WINDOW * AUDIO_FS),
            samplerate=AUDIO_FS,
            channels=1,
            dtype="float32",
            blocking=True
        )

        rms = float(np.sqrt(np.mean(audio ** 2)))
        db = float(20 * np.log10(rms + 1e-6))

        audio_db = db
        audio_db_history.append(db)
        audio_env.append(rms)

def audio_active():
    return audio_db > -40

def detect_audio_spike():
    # Sudden increase
    if len(audio_db_history) < 10:
        return False
    baseline = float(np.mean(list(audio_db_history)[:-1]))
    return (audio_db_history[-1] - baseline) > 6.0

def detect_subtle_sound():
    # Small lift above baseline (quiet clicks / subtle ramps)
    if len(audio_db_history) < 10:
        return False
    baseline = float(np.mean(list(audio_db_history)[:-1]))
    delta = audio_db_history[-1] - baseline
    return (delta > 2.0) and (delta <= 6.0)

def detect_sub_5hz_audio():
    # Detect <5 Hz amplitude modulation in envelope (slow rhythmic changes)
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

# ---- Audio Burst State Machine ----
BURST_GAP_S = 1.0   # end burst if no bursty activity for this long
BURST_MIN_S = 0.4   # ignore extremely tiny bursts
burst_active = False
burst_id = 0
burst_start_ts = None
burst_last_hit_ts = None
burst_peak_db = -999.0
burst_spike_count = 0
burst_subtle_count = 0

recent_bursts = deque(maxlen=12)  # for GUI display

def update_audio_burst(now_ts: float, is_spike: bool, is_subtle: bool):
    """
    A burst = a cluster of subtle/spike events with short gaps.
    """
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
        return None  # no "end event" yet

    if burst_active and hit:
        burst_last_hit_ts = now_ts
        if audio_db > burst_peak_db:
            burst_peak_db = float(audio_db)
        if is_spike:
            burst_spike_count += 1
        if is_subtle:
            burst_subtle_count += 1
        return None

    # no hit — if burst was active, check for end
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

            # reset
            burst_active = False
            burst_start_ts = None
            burst_last_hit_ts = None
            burst_peak_db = -999.0
            burst_spike_count = 0
            burst_subtle_count = 0

            # ignore ultra tiny bursts
            if dur < BURST_MIN_S:
                return None

            recent_bursts.appendleft(ended)
            return ended

    return None

def audio_burst_snapshot(now_ts: float):
    """
    Return current burst state info for logging.
    """
    if not burst_active or burst_start_ts is None:
        return {
            "audio_burst": False,
            "burst_id": "",
            "burst_age_s": "",
            "burst_peak_db": "",
            "burst_spike_count": "",
            "burst_subtle_count": "",
        }
    age = float(now_ts - burst_start_ts)
    return {
        "audio_burst": True,
        "burst_id": burst_id,
        "burst_age_s": round(age, 2),
        "burst_peak_db": round(float(burst_peak_db), 1),
        "burst_spike_count": int(burst_spike_count),
        "burst_subtle_count": int(burst_subtle_count),
    }

# ======================
# BLE (PROXIMITY + CLOSE/DROP + TREND)
# ======================
from bleak import BleakScanner

ble_packets = deque(maxlen=250)
ble_seen_time = {}
ble_rssi_hist = defaultdict(lambda: deque(maxlen=35))  # mac -> [(t,rssi)]
ble_is_close = {}
ble_close_start = {}                                  # mac -> ts

ble_close_events = deque(maxlen=80)
ble_drop_events = deque(maxlen=80)

# Proximity tuning
BLE_CLOSE_RSSI = -55       # closer if >= this (less negative)
BLE_MIN_SAMPLES = 8

# Trend tuning (RSSI slope)
BLE_TREND_WINDOW = 12      # samples to compare
BLE_TREND_DB = 5           # delta threshold for approach/recede

# Drop tuning
BLE_DROP_TIMEOUT = 6.0     # seconds since last seen to consider dropped

# Track close-window RSSI evolution per MAC (so we can label "approaching vs receding" over the whole close)
ble_close_stats = {}       # mac -> dict(start_avg, last_avg, max_avg, min_avg, last_update_ts)

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

def ble_avg_rssi(mac: str, n: int = 6):
    hist = ble_rssi_hist.get(mac)
    if not hist or len(hist) < max(2, min(n, BLE_MIN_SAMPLES)):
        return None
    vals = [r for _, r in list(hist)[-n:]]
    return float(np.mean(vals)) if vals else None

def ble_trend(mac: str):
    """
    Returns one of: ("approaching"|"receding"|"stable"), plus (recent_avg, older_avg, delta)
    based on last BLE_TREND_WINDOW samples.
    """
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
    """
    Keep a rolling summary while the device is in close-state.
    """
    avg = ble_avg_rssi(mac, 6)
    if avg is None:
        return
    st = ble_close_stats.get(mac)
    if st is None:
        st = {
            "start_avg": avg,
            "last_avg": avg,
            "max_avg": avg,
            "min_avg": avg,
            "last_update_ts": now_ts,
        }
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

    # Transition into close
    if close_now and not close_prev:
        ble_is_close[mac] = True
        ble_close_start[mac] = now
        update_close_stats(mac, now)
        ble_close_events.append({
            "ts": now,
            "mac": mac,
            "rssi": rssi,
            "trend": trend_label,
            "trend_delta": delta,
            "recent_avg": recent_avg,
            "older_avg": older_avg,
        })
        return

    # While close, update stats
    if close_now and close_prev:
        update_close_stats(mac, now)
        return

    # Transition out of close (RSSI fell but still seen)
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
            "ts": now,
            "mac": mac,
            "rssi": rssi,
            "reason": "rssi_fell",
            "duration_s": duration,
            "close_start_ts": start_ts,
            "close_end_ts": now,
            "trend": trend_label,
            "trend_delta": delta,
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
            trend_label, recent_avg, older_avg, delta = ble_trend(mac)
            best = (mac, avg, close, trend_label, delta)
    if best is None:
        return (None, None, False, "stable", 0.0)
    return best

def check_ble_timeouts():
    """
    If a device was close but hasn't been seen recently, mark dropped with duration.
    """
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
            "ts": now,
            "mac": mac,
            "rssi": None,
            "reason": "timeout",
            "duration_s": duration,
            "close_start_ts": start_ts,
            "close_end_ts": now,
            "trend": "stable",
            "trend_delta": 0.0,
            "close_start_avg": start_avg,
            "close_end_avg": last_avg,
            "close_net_delta": net_delta,
            "close_overall_trend": overall,
        })

# ======================
# WIFI RSSI (Linux via nmcli)
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
# GESTURE (RF + BLE + AUDIO)
# ======================
def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data", 0.0

    sig = np.array(list(wifi_rssi)[-40:], dtype=np.float32)
    short = sig[-10:]

    short_std = float(np.std(short))
    rate = ble_rate()
    energy = float(short_std + rate * 0.3)

    if short_std < 0.8 and rate == 0:
        return "idle", energy

    if short_std < 1.0 and detect_sub_5hz_audio():
        return "presence_nearby", energy

    if short_std < 1.2 and audio_active():
        return "listening", energy

    if short_std > 1.2 and audio_active():
        return "talking", energy

    if short_std > 2.0:
        return "moving", energy

    return "unknown", energy

# ======================
# DISTANCE (RELATIVE, AUDIO+RF)
# ======================
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

# ======================
# STATE SNAPSHOT
# ======================
def build_state(now_ts: float):
    gesture, energy = classify_gesture()

    mac, avg_rssi, ble_close, ble_tr, ble_tr_delta = get_closest_ble()

    spike = detect_audio_spike()
    subtle = detect_subtle_sound()
    sub5 = detect_sub_5hz_audio()

    # update burst state machine (end events are returned but not required here)
    update_audio_burst(now_ts, spike, subtle)
    burst_info = audio_burst_snapshot(now_ts)

    return {
        "gesture": gesture,
        "energy": round(energy, 2),

        "audio_db": round(audio_db, 1),
        "audio_active": audio_active(),
        "audio_spike": spike,
        "audio_subtle": subtle,
        "audio_sub5hz": sub5,

        "audio_burst": burst_info["audio_burst"],
        "burst_id": burst_info["burst_id"],
        "burst_age_s": burst_info["burst_age_s"],
        "burst_peak_db": burst_info["burst_peak_db"],
        "burst_spike_count": burst_info["burst_spike_count"],
        "burst_subtle_count": burst_info["burst_subtle_count"],

        "ble_rate": ble_rate(),
        "ble_close": bool(ble_close),
        "ble_mac": mac or "",
        "ble_rssi_avg": round(avg_rssi, 1) if avg_rssi is not None else "",
        "ble_trend": ble_tr,
        "ble_trend_delta": round(float(ble_tr_delta), 1),

        "rf_motion": energy > 1.2,
        "distance": infer_sound_distance()
    }

# ======================
# CROSS-LAYER RULES
# ======================
KNOWN_RULES = {
    "walking_and_talking": lambda s: s["gesture"] == "moving" and s["audio_active"],
    "silent_motion": lambda s: s["rf_motion"] and not s["audio_active"],
    "audio_only": lambda s: s["audio_spike"] and not s["rf_motion"],
    "approaching_sound": lambda s: s["distance"] == "approaching" and s["rf_motion"],
    "low_freq_presence": lambda s: s["audio_sub5hz"] and not s["rf_motion"],

    # BLE + audio burst / subtle / distance
    "ble_close_audio_burst": lambda s: s["ble_close"] and s["audio_burst"],
    "ble_close_subtle_sound": lambda s: s["ble_close"] and s["audio_subtle"],
    "ble_close_spike": lambda s: s["ble_close"] and s["audio_spike"],
    "ble_close_approaching_sound": lambda s: s["ble_close"] and s["distance"] == "approaching",
    "ble_approaching": lambda s: s["ble_close"] and s["ble_trend"] == "approaching",
    "ble_receding": lambda s: s["ble_close"] and s["ble_trend"] == "receding",
}

# ======================
# AUTO-DISCOVERY ENGINE
# ======================
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
    """
    Signature you can mine for unknown patterns:
    - BLE trend + delta
    - distance
    - burst presence
    - spike/subtle/sub5
    - gesture
    """
    short_mac = mac[-5:] if mac else "unknown"
    sig = (
        f"mac..{short_mac}|"
        f"ble:{state['ble_trend']}({state['ble_trend_delta']})|"
        f"dist:{state['distance']}|"
        f"burst:{int(state['audio_burst'])}|"
        f"subtle:{int(state['audio_subtle'])}|"
        f"spike:{int(state['audio_spike'])}|"
        f"sub5:{int(state['audio_sub5hz'])}|"
        f"gesture:{state['gesture']}"
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
# LOGGING
# ======================
def ensure_logs():
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp",
                "gesture",
                "energy",
                "audio_db",
                "audio_active",
                "audio_spike",
                "audio_subtle",
                "audio_sub5hz",
                "audio_burst",
                "burst_id",
                "burst_age_s",
                "burst_peak_db",
                "burst_spike_count",
                "burst_subtle_count",
                "rf_motion",
                "ble_rate",
                "ble_close",
                "ble_mac",
                "ble_rssi_avg",
                "ble_trend",
                "ble_trend_delta",
                "distance",
                "cross_layers"
            ])

    if not DISCOVERY_FILE.exists():
        with open(DISCOVERY_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp",
                "event",  # ble_close / ble_drop
                "ble_mac",
                "ble_rssi",
                "ble_rssi_avg",
                "ble_trend",
                "ble_trend_delta",
                "gesture",
                "distance",
                "audio_db",
                "audio_burst",
                "burst_id",
                "burst_peak_db",
                "burst_spike_count",
                "burst_subtle_count",
                "audio_spike",
                "audio_subtle",
                "audio_sub5hz",
                "signature",
                "signature_count",
                "close_start_ts",
                "close_end_ts",
                "close_duration_s",
                "close_start_avg",
                "close_end_avg",
                "close_net_delta",
                "close_overall_trend",
                "drop_reason"
            ])

def log_csv(state, cross):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            state["gesture"],
            state["energy"],
            state["audio_db"],
            int(state["audio_active"]),
            int(state["audio_spike"]),
            int(state["audio_subtle"]),
            int(state["audio_sub5hz"]),
            int(state["audio_burst"]),
            state["burst_id"],
            state["burst_age_s"],
            state["burst_peak_db"],
            state["burst_spike_count"],
            state["burst_subtle_count"],
            int(state["rf_motion"]),
            state["ble_rate"],
            int(state["ble_close"]),
            state["ble_mac"],
            state["ble_rssi_avg"],
            state["ble_trend"],
            state["ble_trend_delta"],
            state["distance"],
            ";".join(cross)
        ])

def log_discovery_row(event: str, mac: str, rssi, rssi_avg, trend, trend_delta,
                      state: dict, sig: str, sig_count: int,
                      close_start_ts=None, close_end_ts=None, close_duration_s=None,
                      close_start_avg=None, close_end_avg=None, close_net_delta=None,
                      close_overall_trend="stable", drop_reason=""):
    with open(DISCOVERY_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            event,
            mac,
            "" if rssi is None else rssi,
            "" if rssi_avg is None else rssi_avg,
            trend,
            trend_delta,
            state["gesture"],
            state["distance"],
            state["audio_db"],
            int(state["audio_burst"]),
            state["burst_id"],
            state["burst_peak_db"],
            state["burst_spike_count"],
            state["burst_subtle_count"],
            int(state["audio_spike"]),
            int(state["audio_subtle"]),
            int(state["audio_sub5hz"]),
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
# BLE EVENT HANDLERS (CLOSE + DROP)
# ======================
recent_events = deque(maxlen=16)  # for GUI

def handle_ble_close_events(state):
    now = time.time()
    while ble_close_events:
        ev = ble_close_events.popleft()
        if now - ev["ts"] > 6.0:
            continue

        mac = ev["mac"]
        rssi = ev["rssi"]
        trend = ev.get("trend", "stable")
        trend_delta = round(float(ev.get("trend_delta", 0.0)), 1)

        sig, sig_count = discover_ble_signature(mac, state)

        log_discovery_row(
            event="ble_close",
            mac=mac,
            rssi=rssi,
            rssi_avg=state["ble_rssi_avg"],
            trend=trend,
            trend_delta=trend_delta,
            state=state,
            sig=sig,
            sig_count=sig_count,
            close_start_ts=ble_close_start.get(mac, ev["ts"]),
            close_end_ts=None,
            close_duration_s=None,
            close_start_avg=None,
            close_end_avg=None,
            close_net_delta=None,
            close_overall_trend="",
            drop_reason=""
        )

        recent_events.appendleft({
            "type": "CLOSE",
            "mac": mac,
            "rssi": rssi,
            "trend": trend,
            "dist": state["distance"],
            "gesture": state["gesture"],
            "burst": int(state["audio_burst"]),
            "spike": int(state["audio_spike"]),
            "subtle": int(state["audio_subtle"]),
            "count": sig_count
        })

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

        trend = ev.get("trend", "stable")
        trend_delta = round(float(ev.get("trend_delta", 0.0)), 1)

        close_start_ts = ev.get("close_start_ts", None)
        close_end_ts = ev.get("close_end_ts", ev["ts"])

        close_start_avg = ev.get("close_start_avg", None)
        close_end_avg = ev.get("close_end_avg", None)
        close_net_delta = ev.get("close_net_delta", None)
        close_overall_trend = ev.get("close_overall_trend", "stable")

        sig, sig_count = discover_ble_signature(mac, state)

        log_discovery_row(
            event="ble_drop",
            mac=mac,
            rssi=rssi,
            rssi_avg=state["ble_rssi_avg"],
            trend=trend,
            trend_delta=trend_delta,
            state=state,
            sig=sig,
            sig_count=sig_count,
            close_start_ts=close_start_ts,
            close_end_ts=close_end_ts,
            close_duration_s=duration_s,
            close_start_avg=close_start_avg,
            close_end_avg=close_end_avg,
            close_net_delta=close_net_delta,
            close_overall_trend=close_overall_trend,
            drop_reason=reason
        )

        dur_txt = f"{duration_s:.1f}s" if duration_s is not None else "?"
        recent_events.appendleft({
            "type": "DROP",
            "mac": mac,
            "rssi": rssi if rssi is not None else "",
            "trend": close_overall_trend,
            "dist": state["distance"],
            "gesture": state["gesture"],
            "burst": int(state["audio_burst"]),
            "spike": int(state["audio_spike"]),
            "subtle": int(state["audio_subtle"]),
            "count": sig_count,
            "dur": dur_txt,
            "reason": reason
        })

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE ↔ Audio (bursts) ↔ Gesture ↔ Distance Discovery (Linux)")

        self.label = QLabel("Starting…")
        self.label.setStyleSheet("font-family: monospace;")
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def update_view(self):
        # mark timeout drops
        check_ble_timeouts()

        now_ts = time.time()
        state = build_state(now_ts)
        cross = detect_cross_layers(state)

        handle_ble_close_events(state)
        handle_ble_drop_events(state)
        log_csv(state, cross)

        # for GUI: discovered BLE signatures + recent bursts/events
        ble_sigs = discovered_ble_signatures()
        generic = discovered_patterns()[-6:]

        def fmt_mac(m):
            return (m[-8:] if m else "none")

        evt_lines = []
        for e in list(recent_events)[:8]:
            if e["type"] == "CLOSE":
                evt_lines.append(
                    f"• CLOSE mac..{fmt_mac(e['mac'])} rssi:{e['rssi']} "
                    f"ble:{e['trend']} dist:{e['dist']} gest:{e['gesture']} "
                    f"burst:{e['burst']} spike:{e['spike']} subtle:{e['subtle']} ({e['count']}x)"
                )
            else:
                evt_lines.append(
                    f"• DROP  mac..{fmt_mac(e['mac'])} rssi:{e['rssi']} "
                    f"overall:{e['trend']} dur:{e.get('dur','?')} reason:{e.get('reason','')} "
                    f"dist:{e['dist']} gest:{e['gesture']} burst:{e['burst']} ({e['count']}x)"
                )

        burst_lines = []
        for b in list(recent_bursts)[:6]:
            burst_lines.append(
                f"• burst#{b['burst_id']} dur:{b['duration_s']:.1f}s peak:{b['peak_db']:.1f}dB "
                f"spk:{b['spike_count']} sub:{b['subtle_count']}"
            )

        sig_lines = []
        for sig, cnt in ble_sigs:
            sig_lines.append(f"• {sig}  ({cnt}x)")

        self.label.setText(
            f"Run logs:\n"
            f"  {LOG_FILE}\n"
            f"  {DISCOVERY_FILE}\n\n"
            f"Gesture        : {state['gesture']}\n"
            f"Energy         : {state['energy']}\n"
            f"Audio dB       : {state['audio_db']}\n"
            f"Audio burst    : {state['audio_burst']}  (id:{state['burst_id']} age:{state['burst_age_s']})\n"
            f"Audio flags    : subtle={int(state['audio_subtle'])} spike={int(state['audio_spike'])} sub5={int(state['audio_sub5hz'])}\n"
            f"BLE closest    : {fmt_mac(state['ble_mac'])}  avg_rssi:{state['ble_rssi_avg']}  close:{int(state['ble_close'])}\n"
            f"BLE trend      : {state['ble_trend']}  delta:{state['ble_trend_delta']}\n"
            f"Sound distance : {state['distance']}\n\n"
            f"Cross-Layers:\n"
            + ("\n".join(f"• {c}" for c in cross) if cross else "• (none)") +
            "\n\nRecent BLE CLOSE/DROP events:\n"
            + ("\n".join(evt_lines) if evt_lines else "• (none yet)") +
            "\n\nRecent Audio Bursts:\n"
            + ("\n".join(burst_lines) if burst_lines else "• (none yet)") +
            "\n\nDiscovered BLE↔Audio signatures:\n"
            + ("\n".join(sig_lines) if sig_lines else "• (none yet)") +
            "\n\nGeneric Auto-Discovered:\n"
            + ("\n".join(f"• {d}" for d in generic) if generic else "• (none yet)")
        )

# ======================
# MAIN
# ======================
def main():
    ensure_logs()

    threading.Thread(target=audio_loop, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()
    threading.Thread(target=wifi_loop, daemon=True).start()

    app = QApplication(sys.argv)
    gui = Dashboard()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(int(GUI_TICK_S * 1000))

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
