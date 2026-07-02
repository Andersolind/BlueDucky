import sys, time, threading, asyncio, subprocess, os, csv
import numpy as np
from collections import defaultdict, deque

# ======================
# SAFETY: DO NOT RUN AS ROOT
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
    "DF:AE:71:78:A0:E1"
}

# --- BLE state ---
ble_packets_total = 0
ble_packets_window = deque(maxlen=20)

ble_first_seen = {}
ble_last_seen = {}
ble_last_rssi = {}
ble_dwell_time = defaultdict(float)
ble_rssi_trail = defaultdict(lambda: deque(maxlen=60))

ble_active_devices = set()
ble_following_device = None

LOG_DIR = "ble_logs"
os.makedirs(LOG_DIR, exist_ok=True)

# ======================
# BLE CALLBACK
# ======================
def detection_callback(device, adv):
    global ble_packets_total, ble_following_device

    mac = device.address.lower()
    if mac not in BLE_TARGET_MACS or adv.rssi is None:
        return

    now = time.time()
    ble_packets_total += 1
    ble_packets_window.append(now)

    if mac not in ble_first_seen:
        ble_first_seen[mac] = now
        print(f"[ALERT] BLE APPEARED: {mac}")

    last = ble_last_seen.get(mac, now)
    ble_dwell_time[mac] += now - last

    ble_last_seen[mac] = now
    ble_last_rssi[mac] = adv.rssi
    ble_rssi_trail[mac].append((now, adv.rssi))
    ble_active_devices.add(mac)

    ble_following_device = mac

    # CSV logging
    csv_path = os.path.join(LOG_DIR, f"{mac.replace(':','_')}.csv")
    new_file = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "rssi"])
        writer.writerow([now, adv.rssi])

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

# ======================
# WIFI VIA NMCLI (SAFE)
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
# MOTION / FOLLOWING LOGIC
# ======================
def detect_motion():
    wifi_motion = False
    if len(wifi_rssi) >= 8:
        wifi_motion = np.std(list(wifi_rssi)[-8:]) > 2.0

    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)
    ble_motion = ble_rate >= 3

    return wifi_motion or ble_motion

def prune_ble_devices(timeout=6):
    now = time.time()
    for mac in list(ble_active_devices):
        if now - ble_last_seen.get(mac, 0) > timeout:
            ble_active_devices.remove(mac)
            print(f"[ALERT] BLE DISAPPEARED: {mac}")

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
        self.setWindowTitle("BLE Following + Dwell Tracker")

        self.fig, self.ax = plt.subplots(figsize=(8,4))
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.status = QLabel("Starting…")

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def update_view(self):
        self.ax.cla()

        if ble_following_device in ble_rssi_trail:
            trail = ble_rssi_trail[ble_following_device]
            if len(trail) > 1:
                t0 = trail[0][0]
                times = [t - t0 for t, _ in trail]
                rssis = [r for _, r in trail]
                self.ax.plot(times, rssis)
                self.ax.set_title(f"RSSI Trail: {ble_following_device}")

        self.canvas.draw()

        fd = ble_following_device or "None"
        dwell = ble_dwell_time.get(fd, 0.0)
        motion = detect_motion()

        self.status.setText(
            f"WiFi samples: {wifi_samples} | "
            f"BLE packets: {ble_packets_total} | "
            f"Following: {fd} | "
            f"Dwell: {dwell:.1f}s | "
            f"Motion: {motion} | "
            f"Active BLE: {len(ble_active_devices)}"
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
        prune_ble_devices()
        gui.update_view()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
