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
# BLE SETUP
# ======================
from bleak import BleakScanner

BLE_TARGET_MACS = {
    "f0:ef:86:f0:4a:f2",
    "56:4c:8b:ac:93:f5",
    "74:88:a8:42:e3:e2",
    "44:27:45:c9:56:63",
    "10:2c:b1:19:7d:1a",
    "4f:e4:4a:2a:dd:1c",
    "DF:AE:71:78:A0:E1"
}

ble_packets_window = deque(maxlen=30)

def detection_callback(device, adv):
    if adv.rssi is None:
        return
    if device.address.lower() in BLE_TARGET_MACS:
        ble_packets_window.append(time.time())

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

# ======================
# WIFI RSSI (NMCLI)
# ======================
wifi_rssi = deque(maxlen=300)

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
# ROOMS + ONLINE LEARNING
# ======================
ROOMS = {
    "Living Room": {},
    "Bedroom": {},
    "Office": {},
}

current_room = "Living Room"

# Gesture history (per room)
gesture_history = defaultdict(lambda: deque(maxlen=120))

# Activity weights (online learning)
activity_weights = defaultdict(lambda: {
    "sitting_idle": 1.0,
    "breathing": 1.0,
    "standing_transition": 1.0,
    "walking_moving": 1.0,
})

LEARNING_RATE = 0.01

# ======================
# GESTURE CLASSIFIER
# ======================
def classify_gesture():
    if len(wifi_rssi) < 30:
        return "no-data"

    sig = np.array(wifi_rssi)
    short = sig[-10:]
    long = sig[-40:]

    short_std = np.std(short)
    long_std = np.std(long)

    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    if short_std < 0.8 and ble_rate == 0:
        return "sitting_idle"
    if short_std < 1.2 and long_std < 1.5:
        return "breathing"
    if short_std > 3.0 and long_std < 2.0:
        return "standing_transition"
    if short_std > 2.0 or ble_rate > 4:
        return "walking_moving"

    return "unknown"

# ======================
# ACTIVITY PROBABILITIES
# ======================
def compute_activity_probabilities(room):
    hist = gesture_history[room]
    if len(hist) < 15:
        return {}

    counts = defaultdict(int)
    for g in hist:
        counts[g] += 1

    total = sum(counts.values())
    frac = {k: v / total for k, v in counts.items()}

    w = activity_weights

    probs = {
        "eating": (
            0.6 * frac.get("sitting_idle", 0) +
            0.3 * frac.get("breathing", 0) +
            0.1 * frac.get("standing_transition", 0)
        ),
        "working": (
            0.7 * frac.get("sitting_idle", 0) +
            0.2 * frac.get("breathing", 0)
        ),
        "resting": (
            0.6 * frac.get("sitting_idle", 0) +
            0.4 * frac.get("breathing", 0)
        ),
        "walking": frac.get("walking_moving", 0),
        "transitioning": (
            0.7 * frac.get("standing_transition", 0) +
            0.3 * frac.get("walking_moving", 0)
        ),
    }

    # Normalize
    s = sum(probs.values())
    if s > 0:
        for k in probs:
            probs[k] /= s

    return probs

# ======================
# ONLINE LEARNING UPDATE
# ======================
def online_learn(room, dominant_activity):
    hist = gesture_history[room]
    if not hist:
        return

    recent = hist[-1]

    # 🚫 Do not learn from invalid gestures
    if recent in ("no-data", "unknown"):
        return

    weights = activity_weights[dominant_activity]

    # Initialize missing gesture keys safely
    if recent not in weights:
        weights[recent] = 1.0

    weights[recent] += LEARNING_RATE

    # Gentle decay to keep weights bounded
    for g in weights:
        weights[g] *= (1 - LEARNING_RATE)


# ======================
# ACTIVITY DURATION + ALERTS
# ======================
activity_start_time = None
current_activity = None

ALERT_EATING_SECONDS = 600  # 10 minutes

def update_activity_duration(activity):
    global activity_start_time, current_activity

    now = time.time()
    if activity != current_activity:
        current_activity = activity
        activity_start_time = now
        return 0

    return now - activity_start_time

# ======================
# CSV LOGGING
# ======================
LOG_FILE = "activity_timeline.csv"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "room", "gesture", "activity", "probability"])

def log_activity(room, gesture, probs):
    if not probs:
        return
    top = max(probs.items(), key=lambda x: x[1])
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([time.time(), room, gesture, top[0], f"{top[1]:.2f}"])

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt5.QtCore import QTimer

class ActivityGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Online Learned Activity Recognition")

        self.status = QLabel("Starting…")

        room_layout = QHBoxLayout()
        for r in ROOMS:
            btn = QPushButton(r)
            btn.clicked.connect(lambda _, x=r: self.set_room(x))
            room_layout.addWidget(btn)

        layout = QVBoxLayout()
        layout.addLayout(room_layout)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def set_room(self, room):
        global current_room
        current_room = room
        print(f"[ROOM] {room}")

    def update_view(self):
        gesture = classify_gesture()
        gesture_history[current_room].append(gesture)

        probs = compute_activity_probabilities(current_room)
        if probs:
            top_activity, top_prob = max(probs.items(), key=lambda x: x[1])
            online_learn(current_room, top_activity)
            duration = update_activity_duration(top_activity)
            log_activity(current_room, gesture, probs)

            if top_activity == "eating" and duration > ALERT_EATING_SECONDS:
                print("[ALERT] Eating detected for >10 minutes")

            prob_list = " | ".join(
                f"{k}:{v:.2f}" for k, v in sorted(probs.items(), key=lambda x: -x[1])
            )

            self.status.setText(
                f"Room: {current_room}\n"
                f"Gesture: {gesture}\n"
                f"Activity: {top_activity} ({top_prob:.2f})\n"
                f"Duration: {duration/60:.1f} min\n"
                f"All: {prob_list}"
            )
        else:
            self.status.setText("Learning gestures…")

# ======================
# MAIN
# ======================
def main():
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()
    threading.Thread(target=wifi_loop, daemon=True).start()

    app = QApplication(sys.argv)
    gui = ActivityGUI()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
