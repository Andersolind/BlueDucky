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
    "df:ae:71:78:a0:e1"
}

ble_packets_window = deque(maxlen=50)
ble_seen_strength = defaultdict(list)
ble_seen_time = {}

def detection_callback(device, adv):
    if adv.rssi is None:
        return
    mac = device.address.lower()
    ble_packets_window.append(time.time())
    ble_seen_strength[mac].append(adv.rssi)
    ble_seen_time[mac] = time.time()

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
# AUDIO PATH DETECTION
# ======================
def detect_digital_audio():
    if len(wifi_rssi) < 40:
        return False

    sig = np.array(list(wifi_rssi)[-40:])
    var = np.std(sig)
    diff = np.std(np.diff(sig))

    ble_rate = sum(1 for t in ble_packets_window if time.time() - t < 5)

    return (0.5 < var < 2.0) and diff < var * 0.6 and ble_rate > 3

# ======================
# TALKING VS LISTENING
# ======================
def detect_talking():
    if len(wifi_rssi) < 40:
        return False

    sig = np.array(list(wifi_rssi)[-40:])
    short = sig[-10:]

    short_std = np.std(short)
    jitter = np.std(np.diff(short))
    audio = detect_digital_audio()

    return audio and (0.6 < short_std < 1.6) and jitter > short_std * 0.6

def detect_listening():
    if len(wifi_rssi) < 40:
        return False

    sig = np.array(list(wifi_rssi)[-40:])
    short_std = np.std(sig[-10:])
    audio = detect_digital_audio()

    return audio and short_std < 0.6

# ======================
# GROUP CONVERSATION
# ======================
def detect_group_conversation():
    now = time.time()
    active_devices = [
        mac for mac, t in ble_seen_time.items()
        if now - t < 8
    ]

    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    return len(active_devices) >= 3 and ble_rate >= 8

# ======================
# GESTURE CLASSIFIER
# ======================
def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data", 0.0

    sig = np.array(list(wifi_rssi)[-40:])
    short = sig[-10:]
    long = sig[-40:]

    short_std = np.std(short)
    long_std = np.std(long)

    ble_rate = sum(1 for t in ble_packets_window if time.time() - t < 5)
    energy = short_std + ble_rate * 0.3

    if detect_group_conversation():
        return "group_conversation", energy

    if detect_talking():
        return "talking", energy

    if detect_listening():
        return "listening", energy * 0.4

    if short_std < 0.8 and ble_rate == 0:
        return "idle_breathing", energy

    if 1.2 < short_std < 2.2:
        return "hand_eating", energy

    if short_std > 2.0 and ble_rate <= 4:
        return "walking", energy

    if short_std > 2.5 and long_std > 1.5:
        return "stairs_exertion", energy

    if np.max(np.abs(np.diff(sig))) > 5.5:
        return "impulse", energy * 1.5

    return "unknown", energy

# ======================
# AUTO-LEARN ZONES
# ======================
ZONE_COUNT = 6
zone_centers = np.linspace(-70, -30, ZONE_COUNT)

def infer_zone():
    mean_rssi = np.mean(wifi_rssi) if wifi_rssi else -50
    return int(np.argmin(np.abs(zone_centers - mean_rssi)))

# ======================
# HEAT MAP STRUCTURE
# ======================
heat_layers = {
    "idle_breathing": np.zeros(ZONE_COUNT),
    "hand_eating": np.zeros(ZONE_COUNT),
    "talking": np.zeros(ZONE_COUNT),
    "listening": np.zeros(ZONE_COUNT),
    "group_conversation": np.zeros(ZONE_COUNT),
    "walking": np.zeros(ZONE_COUNT),
    "stairs_exertion": np.zeros(ZONE_COUNT),
    "impulse": np.zeros(ZONE_COUNT),
    "audio": np.zeros(ZONE_COUNT),
}

DECAY = 0.995

def update_heat(zone, gesture, energy, audio):
    for k in heat_layers:
        heat_layers[k] *= DECAY

    if gesture in heat_layers:
        heat_layers[gesture][zone] += energy

    if audio:
        heat_layers["audio"][zone] += energy * 0.6

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import matplotlib.pyplot as plt

COLORS = {
    "idle_breathing": "blue",
    "hand_eating": "green",
    "talking": "cyan",
    "listening": "lightblue",
    "group_conversation": "magenta",
    "walking": "yellow",
    "stairs_exertion": "orange",
    "impulse": "red",
    "audio": "purple",
}

class HeatMapGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RF Conversation & Energy Heat Map")

        self.fig, self.ax = plt.subplots(figsize=(9,4))
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.status = QLabel("Starting…")
        self.status.setStyleSheet("font-family: monospace;")

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.status)
        self.setLayout(layout)

    def update_view(self):
        gesture, energy = classify_gesture()
        audio = detect_digital_audio()
        zone = infer_zone()

        update_heat(zone, gesture, energy, audio)

        self.ax.cla()
        for name, layer in heat_layers.items():
            self.ax.plot(layer, label=name, color=COLORS[name])

        self.ax.legend(fontsize=8)
        self.ax.set_title("Activity-Specific RF Energy Heat Layers")
        self.canvas.draw()

        self.status.setText(
            f"Gesture: {gesture} | Zone: {zone} | Energy: {energy:.2f} | "
            f"Audio: {audio} | BLE devices: {len(ble_seen_time)}"
        )

# ======================
# MAIN
# ======================
def main():
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()
    threading.Thread(target=wifi_loop, daemon=True).start()

    app = QApplication(sys.argv)
    gui = HeatMapGUI()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
