import sys, time, threading, asyncio, subprocess, os
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
}

ble_packets_window = deque(maxlen=20)

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
# MULTI-ROOM PROFILES
# ======================
rooms = {
    "Living Room": {"mean": None, "std": None},
    "Bedroom": {"mean": None, "std": None},
    "Office": {"mean": None, "std": None},
}

current_room = "Living Room"

# Adaptive calibration parameters
EMA_ALPHA = 0.02   # slow adaptation
MIN_IDLE_STD = 0.3

def adaptive_update(std_now):
    room = rooms[current_room]
    if room["std"] is None:
        room["std"] = std_now
    else:
        room["std"] = (
            (1 - EMA_ALPHA) * room["std"] + EMA_ALPHA * std_now
        )

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

    room_std = rooms[current_room]["std"] or 1.0

    # BLE activity
    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    # ---- Gesture logic ----
    if short_std < room_std * 0.8 and ble_rate == 0:
        adaptive_update(short_std)
        return "sitting / idle"

    if short_std < room_std * 1.2 and long_std < room_std * 1.5:
        adaptive_update(short_std)
        return "breathing"

    if short_std > room_std * 3.0 and long_std < room_std * 2.0:
        return "standing up / sitting down"

    if short_std > room_std * 2.0 or ble_rate > 4:
        return "walking / moving"

    return "unknown"

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QPushButton, QHBoxLayout
)
from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import matplotlib.pyplot as plt

class GestureGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Adaptive BLE + Wi-Fi Gesture Detection")

        self.fig, self.ax = plt.subplots(figsize=(8,4))
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.status = QLabel("Starting…")

        # Room buttons
        room_layout = QHBoxLayout()
        for r in rooms:
            btn = QPushButton(r)
            btn.clicked.connect(lambda _, x=r: self.set_room(x))
            room_layout.addWidget(btn)

        layout = QVBoxLayout()
        layout.addLayout(room_layout)
        layout.addWidget(self.canvas)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def set_room(self, room):
        global current_room
        current_room = room
        print(f"[ROOM] Switched to {room}")

    def update_view(self):
        self.ax.cla()
        if wifi_rssi:
            self.ax.plot(wifi_rssi)
            self.ax.set_title(f"Wi-Fi RSSI — {current_room}")
        self.canvas.draw()

        gesture = classify_gesture()
        std = rooms[current_room]["std"]

        self.status.setText(
            f"Room: {current_room} | "
            f"Gesture: {gesture} | "
            f"Baseline STD: {std:.2f}" if std else
            f"Room: {current_room} | Gesture: {gesture} | Calibrating…"
        )

# ======================
# MAIN
# ======================
def main():
    threading.Thread(
        target=lambda: asyncio.run(ble_loop()),
        daemon=True
    ).start()

    threading.Thread(
        target=wifi_loop,
        daemon=True
    ).start()

    app = QApplication(sys.argv)
    gui = GestureGUI()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
