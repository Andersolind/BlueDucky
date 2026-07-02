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
    "df:ae:71:78:a0:e1"
}

ble_packets_window = deque(maxlen=40)
ble_seen_strength = defaultdict(list)

def detection_callback(device, adv):
    if adv.rssi is None:
        return
    mac = device.address.lower()
    if mac in BLE_TARGET_MACS:
        ble_packets_window.append(time.time())
        ble_seen_strength[mac].append(adv.rssi)

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

# ======================
# WIFI RSSI (NMCLI)
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
# ROOMS / FLOORS
# ======================
ROOMS = ["Living Room", "Bedroom", "Office"]
current_room = "Living Room"
current_floor = 0

gesture_history = defaultdict(lambda: deque(maxlen=180))

step_count = 0

# ======================
# GESTURE CLASSIFIER
# ======================
def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data", 0, 0, 0

    sig = np.array(wifi_rssi)
    short = sig[-10:]
    long = sig[-40:]

    short_std = np.std(short)
    long_std = np.std(long)

    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    short_long_ratio = short_std / max(long_std, 0.01)

    # breathing trend proxy
    breathing_rising = np.std(sig[-10:]) > np.std(sig[-20:-10])

    if short_std < 0.8 and ble_rate == 0:
        return "sitting_idle", short_std, long_std, ble_rate

    if short_std < 1.2 and long_std < 1.5:
        return "breathing", short_std, long_std, ble_rate

    # 🪜 stairs up / down
    if (
        short_std > 2.2 and
        long_std > 1.5 and
        short_long_ratio > 1.4 and
        2 <= ble_rate <= 5
    ):
        if breathing_rising:
            return "stairs_up", short_std, long_std, ble_rate
        else:
            return "stairs_down", short_std, long_std, ble_rate

    # 🥄 eating micro-motion
    if (
        1.2 < short_std < 2.2 and
        long_std < 2.0 and
        1 <= ble_rate <= 3
    ):
        return "hand_to_mouth_motion", short_std, long_std, ble_rate

    if short_std > 3.0 and long_std < 2.0:
        return "standing_transition", short_std, long_std, ble_rate

    if short_std > 2.0 or ble_rate > 4:
        return "walking_moving", short_std, long_std, ble_rate

    return "unknown", short_std, long_std, ble_rate

# ======================
# STEP COUNT / FATIGUE / FALL
# ======================
def detect_fatigue(room):
    recent = list(gesture_history[room])[-40:]
    return recent.count("stairs_up") > 15 and recent.count("breathing") > 8

def detect_fall():
    if len(wifi_rssi) < 20:
        return False

    sig = np.array(wifi_rssi)
    impulse = np.max(np.abs(np.diff(sig)))

    now = time.time()
    ble_recent = sum(1 for t in ble_packets_window if now - t < 2)

    # Convert deque → list before slicing
    silence = np.std(list(wifi_rssi)[-10:]) < 0.3

    return impulse > 6.0 and ble_recent > 3 and silence

def top_ble_beacons(n=3):
    avgs = {
        mac: np.mean(rssis)
        for mac, rssis in ble_seen_strength.items()
        if len(rssis) > 3
    }
    return sorted(avgs.items(), key=lambda x: -x[1])[:n]

# ======================
# CSV LOGGING
# ======================
LOG_FILE = "activity_timeline.csv"

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp",
            "room",
            "floor",
            "gesture",
            "wifi_short_std",
            "wifi_long_std",
            "ble_rate",
            "steps",
            "fatigue",
            "fall"
        ])

def log_csv(room, floor, gesture, sstd, lstd, ble, steps, fatigue, fall):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            room,
            floor,
            gesture,
            f"{sstd:.2f}",
            f"{lstd:.2f}",
            ble,
            steps,
            fatigue,
            fall
        ])

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt5.QtCore import QTimer

class ActivityGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE + Wi-Fi Multi-Floor Activity Detection")

        self.status = QLabel("Starting…")

        room_bar = QHBoxLayout()
        for r in ROOMS:
            b = QPushButton(r)
            b.clicked.connect(lambda _, x=r: self.set_room(x))
            room_bar.addWidget(b)

        layout = QVBoxLayout()
        layout.addLayout(room_bar)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def set_room(self, room):
        global current_room
        current_room = room
        print(f"[ROOM] {room}")

    def update_view(self):
        global step_count, current_floor

        gesture, sstd, lstd, ble = classify_gesture()
        gesture_history[current_room].append(gesture)

        if gesture in ("walking_moving", "stairs_up", "stairs_down") and sstd > 2.0:
            step_count += 1

        if gesture == "stairs_up":
            current_floor += 1
        elif gesture == "stairs_down":
            current_floor -= 1

        fatigue = detect_fatigue(current_room)
        fall = detect_fall()

        if fall:
            print("[🚨 FALL DETECTED] Sudden impulse + silence")

        beacons = top_ble_beacons()
        beacon_text = ", ".join(f"{m[-5:]}:{r:.1f}" for m, r in beacons)

        log_csv(
            current_room,
            current_floor,
            gesture,
            sstd,
            lstd,
            ble,
            step_count,
            fatigue,
            fall
        )

        self.status.setText(
            f"Room: {current_room}\n"
            f"Floor: {current_floor}\n"
            f"Gesture: {gesture}\n"
            f"Steps: {step_count}\n"
            f"Fatigue: {fatigue}\n"
            f"Top BLE: {beacon_text}"
        )

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
