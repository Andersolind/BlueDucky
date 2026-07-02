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
# USER STATIC BLE LIST
# ======================
KNOWN_BLE_MACS = {
    "f0:ef:86:f0:4a:f2",
    "56:4c:8b:ac:93:f5",
    "74:88:a8:42:e3:e2",
    "44:27:45:c9:56:63",
    "10:2c:b1:19:7d:1a",
    "4f:e4:4a:2a:dd:1c",
}

# ======================
# BLE STATE
# ======================
from bleak import BleakScanner

ble_seen = {}                 # mac -> last_seen_time
ble_rssi = {}                 # mac -> last_rssi
new_ble_devices = set()       # unknown devices
ble_packets_window = deque(maxlen=20)

def detection_callback(device, adv):
    mac = device.address.lower()
    if adv.rssi is None:
        return

    now = time.time()
    ble_seen[mac] = now
    ble_rssi[mac] = adv.rssi
    ble_packets_window.append(now)

    if mac not in KNOWN_BLE_MACS:
        if mac not in new_ble_devices:
            print(f"[ALERT] NEW BLE DEVICE DETECTED: {mac}")
            new_ble_devices.add(mac)

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

# ======================
# WIFI RSSI (NMCLI)
# ======================
wifi_rssi = deque(maxlen=120)

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
# ACTIVITY CLASSIFIER
# ======================
def classify_activity():
    """
    Returns:
      activity_label
      confidence (0–1)
    """
    if len(wifi_rssi) < 20:
        return "no-data", 0.0

    sig = np.array(wifi_rssi)
    recent = sig[-10:]
    long = sig[-40:]

    short_var = np.std(recent)
    long_var = np.std(long)

    # BLE burst rate
    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    # ---- Heuristics ----
    if short_var < 0.6 and ble_rate == 0:
        return "sitting / idle", 0.8

    if short_var < 1.0 and long_var < 1.5:
        return "breathing", 0.7

    if short_var > 3.0 and long_var < 2.0:
        return "standing up", 0.9

    if short_var > 2.0 or ble_rate > 4:
        return "moving", 0.85

    return "unknown", 0.4

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import matplotlib.pyplot as plt

class ActivityGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE + Wi-Fi Activity Classifier")

        self.fig, self.ax = plt.subplots(figsize=(8,4))
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.status = QLabel("Starting…")

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def update_view(self):
        self.ax.cla()
        if len(wifi_rssi) > 0:
            self.ax.plot(wifi_rssi)
            self.ax.set_title("Wi-Fi RSSI (variance-based motion)")
        self.canvas.draw()

        activity, conf = classify_activity()

        self.status.setText(
            f"Activity: {activity} ({conf:.2f}) | "
            f"Known BLE: {len(ble_seen & KNOWN_BLE_MACS) if hasattr(set(), 'intersection') else ''} | "
            f"New BLE: {len(new_ble_devices)}"
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
    gui = ActivityGUI()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
