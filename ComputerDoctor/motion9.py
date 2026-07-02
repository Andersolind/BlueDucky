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
# GESTURE CLASSIFIER
# ======================
def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data"

    sig = np.array(list(wifi_rssi)[-40:])
    short = sig[-10:]
    long = sig[-40:]

    short_std = np.std(short)
    long_std = np.std(long)

    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    ratio = short_std / max(long_std, 0.01)

    if short_std < 0.8 and ble_rate == 0:
        return "sitting_idle"

    if short_std < 1.2 and long_std < 1.5:
        return "breathing"

    if (
        1.2 < short_std < 2.2 and
        long_std < 2.0 and
        1 <= ble_rate <= 3
    ):
        return "hand_to_mouth_motion"

    if short_std > 2.2 and long_std > 1.5 and ratio > 1.4:
        return "stairs / exertion"

    if short_std > 2.0 or ble_rate > 4:
        return "walking_moving"

    return "unknown"

# ======================
# AUDIO PATH DETECTION
# ======================
def detect_digital_audio_path():
    if len(wifi_rssi) < 40:
        return False, 0.0

    sig = np.array(list(wifi_rssi)[-40:])
    var = np.std(sig)
    diff_var = np.std(np.diff(sig))

    now = time.time()
    ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

    score = 0.0
    if 0.5 < var < 2.0:
        score += 0.4
    if diff_var < var * 0.6:
        score += 0.3
    if ble_rate > 3:
        score += 0.3

    return score > 0.6, score

def detect_beamformed_audio():
    if len(wifi_rssi) < 60:
        return False, 0.0

    data = list(wifi_rssi)
    short = np.std(data[-10:])
    long = np.std(data[-60:])
    ratio = short / max(long, 0.01)

    if ratio < 0.6 and long > 0.8:
        return True, ratio

    return False, ratio

# ======================
# BLE BEACONS
# ======================
def top_ble_beacons(n=3):
    avgs = {
        mac: np.mean(rssis)
        for mac, rssis in ble_seen_strength.items()
        if len(rssis) > 3
    }
    return sorted(avgs.items(), key=lambda x: -x[1])[:n]

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class AudioPathGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gestures + Digital Audio / Beamforming")

        self.status = QLabel("Starting…")
        self.status.setStyleSheet(
            "font-family: monospace; font-size: 11pt;"
        )

        layout = QVBoxLayout()
        layout.addWidget(self.status)
        self.setLayout(layout)

    def update_view(self):
        now = time.time()
        ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

        gesture = classify_gesture()
        digital, d_score = detect_digital_audio_path()
        beam, b_score = detect_beamformed_audio()

        beacon_text = ", ".join(
            f"{m[-5:]}:{r:.1f}"
            for m, r in top_ble_beacons()
        )

        self.status.setText(
            f"Current Gesture : {gesture}\n\n"
            f"Digital Audio   : {digital} (score {d_score:.2f})\n"
            f"Beamformed Audio: {beam} (score {b_score:.2f})\n"
            f"BLE rate        : {ble_rate}\n"
            f"Top BLE beacons : {beacon_text}"
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
    gui = AudioPathGUI()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
