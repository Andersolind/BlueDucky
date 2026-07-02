import sys, time, threading, asyncio, subprocess, os, csv
import numpy as np
from collections import defaultdict, deque

# ======================
# SAFETY
# ======================
if os.geteuid() == 0:
    print("❌ Do NOT run with sudo")
    sys.exit(1)

# ======================
# AUDIO (LEVEL ONLY)
# ======================
import sounddevice as sd

AUDIO_FS = 16000
AUDIO_WINDOW = 0.1

audio_db = -100.0
audio_db_history = deque(maxlen=50)

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
        rms = np.sqrt(np.mean(audio ** 2))
        db = 20 * np.log10(rms + 1e-6)
        audio_db = db
        audio_db_history.append(db)

def audio_active():
    return audio_db > -40

def detect_audio_spike():
    if len(audio_db_history) < 6:
        return False
    baseline = np.mean(list(audio_db_history)[:-1])
    return audio_db_history[-1] - baseline > 6.0

# ======================
# BLE
# ======================
from bleak import BleakScanner

ble_packets = deque(maxlen=50)
ble_seen_time = {}

def detection_callback(device, adv):
    if adv.rssi is None:
        return
    ble_packets.append(time.time())
    ble_seen_time[device.address.lower()] = time.time()

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

def ble_rate():
    now = time.time()
    return sum(1 for t in ble_packets if now - t < 5)

# ======================
# WIFI RSSI
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
# GESTURE (RF + BLE)
# ======================
def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data", 0.0

    sig = np.array(list(wifi_rssi)[-40:])
    short = sig[-10:]

    short_std = np.std(short)
    rate = ble_rate()
    energy = short_std + rate * 0.3

    if short_std < 0.8 and rate == 0:
        return "idle", energy

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
    if len(audio_db_history) < 5 or len(wifi_rssi) < 20:
        return "unknown"

    da = audio_db_history[-1] - audio_db_history[-5]
    rf_now = np.mean(list(wifi_rssi)[-10:])
    rf_prev = np.mean(list(wifi_rssi)[-20:-10])
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
    return {
        "gesture": gesture,
        "energy": round(energy, 2),
        "audio_active": audio_active(),
        "audio_spike": detect_audio_spike(),
        "ble_rate": ble_rate(),
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
    "approaching_sound": lambda s: s["distance"] == "approaching" and s["rf_motion"]
}

# ======================
# AUTO-DISCOVERY ENGINE
# ======================
pattern_counts = defaultdict(int)
DISCOVERY_THRESHOLD = 12

def auto_discover(state):
    active_keys = [k for k, v in state.items() if isinstance(v, bool) and v]

    for i in range(len(active_keys)):
        for j in range(i + 1, len(active_keys)):
            key = f"{active_keys[i]}+{active_keys[j]}"
            pattern_counts[key] += 1

def discovered_patterns():
    return [
        k for k, v in pattern_counts.items()
        if v >= DISCOVERY_THRESHOLD
    ]

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
# CSV LOGGING
# ======================
LOG_FILE = "crosslayer_activity_log.csv"

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp",
            "gesture",
            "audio_active",
            "audio_spike",
            "rf_motion",
            "ble_rate",
            "distance",
            "cross_layers"
        ])

def log_csv(state, cross):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            state["gesture"],
            state["audio_active"],
            state["audio_spike"],
            state["rf_motion"],
            state["ble_rate"],
            state["distance"],
            ";".join(cross)
        ])

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cross-Layer Gesture & Audio Dashboard")

        self.label = QLabel("Starting…")
        self.label.setStyleSheet("font-family: monospace;")

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def update_view(self):
        state = build_state()
        cross = detect_cross_layers(state)
        log_csv(state, cross)

        discovered = discovered_patterns()[-5:]

        self.label.setText(
            f"Gesture       : {state['gesture']}\n"
            f"Energy        : {state['energy']}\n"
            f"Audio active  : {state['audio_active']}\n"
            f"Audio spike   : {state['audio_spike']}\n"
            f"BLE rate      : {state['ble_rate']}\n"
            f"Sound dist    : {state['distance']}\n\n"
            f"Cross-Layers:\n"
            + "\n".join(f"• {c}" for c in cross) +
            "\n\nAuto-Discovered:\n"
            + "\n".join(f"• {d}" for d in discovered)
        )

# ======================
# MAIN
# ======================
def main():
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
