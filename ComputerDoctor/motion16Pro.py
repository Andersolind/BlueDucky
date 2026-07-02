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
# AUDIO (LEVEL + SUB-5HZ ENVELOPE + SUBTLE SOUND)
# ======================
import sounddevice as sd

AUDIO_FS = 16000
AUDIO_WINDOW = 0.1  # seconds

audio_db = -100.0
audio_db_history = deque(maxlen=80)   # ~8 seconds
audio_env = deque(maxlen=250)         # ~25 seconds

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
    if len(audio_db_history) < 10:
        return False
    baseline = float(np.mean(list(audio_db_history)[:-1]))
    return (audio_db_history[-1] - baseline) > 6.0

def detect_subtle_sound():
    """
    Subtle: small lift above baseline (quiet clicks / soft ramps), not a big spike.
    """
    if len(audio_db_history) < 10:
        return False
    baseline = float(np.mean(list(audio_db_history)[:-1]))
    delta = audio_db_history[-1] - baseline
    return (delta > 2.0) and (delta <= 6.0)

def detect_sub_5hz_audio():
    """
    Detects <5 Hz amplitude modulation in the audio envelope (slow rhythmic changes).
    """
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

# ======================
# BLE (PROXIMITY + EVENTS)
# ======================
from bleak import BleakScanner

ble_packets = deque(maxlen=200)
ble_seen_time = {}
ble_rssi_hist = defaultdict(lambda: deque(maxlen=25))   # mac -> [(t, rssi), ...]
ble_is_close = {}                                      # mac -> bool (last state)
ble_close_events = deque(maxlen=50)                    # recent proximity triggers

# Proximity tuning
BLE_CLOSE_RSSI = -55          # tune: -60 (looser) to -45 (stricter)
BLE_RISE_DB = 6               # rising amount vs older samples suggests approaching
BLE_MIN_SAMPLES = 8

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

def ble_proximity_flags(mac: str):
    hist = ble_rssi_hist.get(mac)
    if not hist or len(hist) < BLE_MIN_SAMPLES:
        return (False, False)

    rssi_vals = np.array([r for _, r in list(hist)], dtype=np.float32)

    recent = rssi_vals[-5:]
    older = rssi_vals[:max(3, len(rssi_vals) - 5)]

    recent_avg = float(np.mean(recent))
    older_avg = float(np.mean(older)) if len(older) else recent_avg

    is_close = recent_avg >= BLE_CLOSE_RSSI
    is_approaching = (recent_avg - older_avg) >= BLE_RISE_DB

    return (is_close, is_approaching)

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

    close_now, approach_now = ble_proximity_flags(mac)
    close_prev = ble_is_close.get(mac, False)

    # Transition into "close" => trigger a discovery event
    if close_now and not close_prev:
        ble_close_events.append({
            "ts": now,
            "mac": mac,
            "rssi": rssi,
            "approaching": approach_now
        })

    ble_is_close[mac] = close_now

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
        vals = np.array([r for _, r in list(hist)[-6:]], dtype=np.float32)
        avg = float(np.mean(vals))
        if best is None or avg > best[1]:
            close, appr = ble_proximity_flags(mac)
            best = (mac, avg, close, appr)
    if best is None:
        return (None, None, False, False)
    return best

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
# DISTANCE (RELATIVE)
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
def build_state():
    gesture, energy = classify_gesture()
    mac, avg_rssi, ble_close, ble_approach = get_closest_ble()

    return {
        "gesture": gesture,
        "energy": round(energy, 2),

        "audio_active": audio_active(),
        "audio_spike": detect_audio_spike(),
        "audio_subtle": detect_subtle_sound(),
        "audio_sub5hz": detect_sub_5hz_audio(),

        "ble_rate": ble_rate(),
        "ble_close": bool(ble_close),
        "ble_approach": bool(ble_approach),
        "ble_mac": mac or "",
        "ble_rssi_avg": round(avg_rssi, 1) if avg_rssi is not None else None,

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

    # BLE proximity cross-examined with subtle sound + distance
    "ble_close_subtle_sound": lambda s: s["ble_close"] and s["audio_subtle"],
    "ble_close_spike": lambda s: s["ble_close"] and s["audio_spike"],
    "ble_close_approaching_sound": lambda s: s["ble_close"] and s["distance"] == "approaching",
}

# ======================
# AUTO-DISCOVERY ENGINE
# ======================
pattern_counts = defaultdict(int)
DISCOVERY_THRESHOLD = 10

ble_audio_signature_counts = defaultdict(int)
BLE_DISCOVERY_THRESHOLD = 6

def auto_discover(state):
    active_keys = [k for k, v in state.items() if isinstance(v, bool) and v]
    for i in range(len(active_keys)):
        for j in range(i + 1, len(active_keys)):
            pattern_counts[f"{active_keys[i]}+{active_keys[j]}"] += 1

def discovered_patterns():
    return [k for k, v in pattern_counts.items() if v >= DISCOVERY_THRESHOLD]

def discover_ble_audio_signature(mac: str, state: dict):
    short_mac = mac[-5:] if mac else "unknown"
    sig = (
        f"mac..{short_mac}|"
        f"dist:{state['distance']}|"
        f"subtle:{int(state['audio_subtle'])}|"
        f"spike:{int(state['audio_spike'])}|"
        f"sub5:{int(state['audio_sub5hz'])}|"
        f"gesture:{state['gesture']}"
    )
    ble_audio_signature_counts[sig] += 1
    return sig, ble_audio_signature_counts[sig]

def discovered_ble_signatures():
    items = [(k, v) for k, v in ble_audio_signature_counts.items() if v >= BLE_DISCOVERY_THRESHOLD]
    items.sort(key=lambda kv: kv[1])
    return items[-8:]

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
# LOGGING (timestamped filenames already set)
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
                "rf_motion",
                "ble_rate",
                "ble_close",
                "ble_approach",
                "ble_mac",
                "ble_rssi_avg",
                "distance",
                "cross_layers"
            ])

    if not DISCOVERY_FILE.exists():
        with open(DISCOVERY_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp",
                "event",
                "ble_mac",
                "ble_rssi",
                "ble_approaching",
                "gesture",
                "distance",
                "audio_db",
                "audio_subtle",
                "audio_spike",
                "audio_sub5hz",
                "signature",
                "signature_count"
            ])

def log_csv(state, cross):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            state["gesture"],
            state["energy"],
            round(audio_db, 1),
            state["audio_active"],
            state["audio_spike"],
            state["audio_subtle"],
            state["audio_sub5hz"],
            state["rf_motion"],
            state["ble_rate"],
            state["ble_close"],
            state["ble_approach"],
            state["ble_mac"],
            state["ble_rssi_avg"],
            state["distance"],
            ";".join(cross)
        ])

def log_discovery(event, mac, rssi, approaching, state, sig, sig_count):
    with open(DISCOVERY_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            event,
            mac,
            rssi,
            approaching,
            state["gesture"],
            state["distance"],
            round(audio_db, 1),
            state["audio_subtle"],
            state["audio_spike"],
            state["audio_sub5hz"],
            sig,
            sig_count
        ])

# ======================
# BLE CLOSE EVENT HANDLER
# ======================
recent_discoveries = deque(maxlen=12)

def handle_ble_close_events(state):
    now = time.time()

    while ble_close_events:
        ev = ble_close_events.popleft()

        if now - ev["ts"] > 5.0:
            continue

        mac = ev["mac"]
        rssi = ev["rssi"]
        approaching = ev.get("approaching", False)

        sig, sig_count = discover_ble_audio_signature(mac, state)

        log_discovery(
            event="ble_close",
            mac=mac,
            rssi=rssi,
            approaching=approaching,
            state=state,
            sig=sig,
            sig_count=sig_count
        )

        recent_discoveries.appendleft({
            "mac": mac,
            "rssi": rssi,
            "approaching": approaching,
            "distance": state["distance"],
            "subtle": state["audio_subtle"],
            "spike": state["audio_spike"],
            "sub5": state["audio_sub5hz"],
            "gesture": state["gesture"],
            "sig": sig,
            "count": sig_count
        })

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cross-Layer Gesture + BLE Proximity + Audio Discovery (Linux)")

        self.label = QLabel("Starting…")
        self.label.setStyleSheet("font-family: monospace;")

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def update_view(self):
        state = build_state()
        cross = detect_cross_layers(state)

        handle_ble_close_events(state)
        log_csv(state, cross)

        discovered = discovered_patterns()[-6:]
        ble_sigs = discovered_ble_signatures()

        def fmt_mac(mac):
            return (mac[-8:] if mac else "unknown")

        discovery_lines = []
        for d in list(recent_discoveries)[:6]:
            discovery_lines.append(
                f"• mac..{fmt_mac(d['mac'])} rssi:{d['rssi']} "
                f"appr:{int(d['approaching'])} dist:{d['distance']} "
                f"subtle:{int(d['subtle'])} spike:{int(d['spike'])} sub5:{int(d['sub5'])} "
                f"({d['count']}x)"
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
            f"Audio dB       : {round(audio_db, 1)}\n"
            f"Audio active   : {state['audio_active']}\n"
            f"Audio subtle   : {state['audio_subtle']}\n"
            f"Audio spike    : {state['audio_spike']}\n"
            f"Sub-5Hz audio  : {state['audio_sub5hz']}\n"
            f"BLE rate       : {state['ble_rate']}\n"
            f"BLE closest    : {state['ble_mac'][-8:] if state['ble_mac'] else 'none'}\n"
            f"BLE rssi(avg)  : {state['ble_rssi_avg']}\n"
            f"BLE close      : {state['ble_close']}  (approach:{state['ble_approach']})\n"
            f"Sound distance : {state['distance']}\n\n"
            f"Cross-Layers:\n"
            + ("\n".join(f"• {c}" for c in cross) if cross else "• (none)") +
            "\n\nBLE→Audio Discoveries (latest):\n"
            + ("\n".join(discovery_lines) if discovery_lines else "• (none yet)") +
            "\n\nDiscovered BLE Signatures:\n"
            + ("\n".join(sig_lines) if sig_lines else "• (none yet)") +
            "\n\nGeneric Auto-Discovered:\n"
            + ("\n".join(f"• {d}" for d in discovered) if discovered else "• (none yet)")
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
    timer.start(500)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
