import sys, time, threading, asyncio, subprocess, os
import numpy as np
from collections import defaultdict, deque

# ======================
# SAFETY: NO SUDO
# ======================
if os.geteuid() == 0:
    print("❌ Do NOT run this script with sudo.")
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

ble_packets_total = 0
ble_packets_window = deque(maxlen=10)  # packets per second window

def detection_callback(device, adv):
    global ble_packets_total
    if device.address.lower() in BLE_TARGET_MACS and adv.rssi is not None:
        ble_packets_total += 1
        ble_packets_window.append(time.time())

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

# ======================
# WIFI VIA NMCLI
# ======================
wifi_rssi = deque(maxlen=300)
wifi_samples = 0

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
    global wifi_samples
    while True:
        rssi = read_wifi_rssi()
        if rssi is not None:
            wifi_rssi.append(rssi)
            wifi_samples += 1
        time.sleep(1)

# ======================
# MOTION + STATE LOGIC
# ======================
def detect_motion():
    """
    Returns:
      wifi_motion (bool)
      ble_motion (bool)
      wifi_score (float)
      ble_rate (float)
    """

    # --- Wi-Fi motion (short window variance)
    if len(wifi_rssi) >= 8:
        recent = np.array(list(wifi_rssi)[-8:])
        wifi_score = np.std(recent)
        wifi_motion = wifi_score > 2.0
    else:
        wifi_score = 0.0
        wifi_motion = False

    # --- BLE motion (packet rate)
    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)
    ble_motion = ble_rate >= 3

    return wifi_motion, ble_motion, wifi_score, ble_rate

def classify_state():
    if len(wifi_rssi) < 10:
        return "no-data", None, False

    sig = np.array(wifi_rssi)
    var = np.std(sig)

    wifi_motion, ble_motion, wifi_score, ble_rate = detect_motion()
    motion_detected = wifi_motion or ble_motion

    if motion_detected:
        state = "motion"
    elif var < 0.8:
        state = "idle"
    else:
        state = "breathing-like"

    return state, sig, motion_detected

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import matplotlib.pyplot as plt

class FusionGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE + Wi-Fi Fusion (Motion Enabled)")

        self.fig, self.ax = plt.subplots(figsize=(8,4))
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.status = QLabel("Starting…")

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def update_view(self, sig, state, motion):
        self.ax.cla()
        if sig is not None:
            self.ax.plot(sig)
            self.ax.set_title("Wi-Fi RSSI (nmcli)")
        self.canvas.draw()

        self.status.setText(
            f"WiFi samples: {wifi_samples} | "
            f"BLE packets: {ble_packets_total} | "
            f"Motion: {motion} | "
            f"State: {state}"
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
    gui = FusionGUI()
    gui.show()

    def tick():
        state, sig, motion = classify_state()
        gui.update_view(sig, state, motion)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
