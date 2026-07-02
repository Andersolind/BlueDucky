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
# AUDIO PATH DETECTION
# ======================
def detect_digital_audio_path():
    if len(wifi_rssi) < 40:
        return False, 0.0

    # Convert deque → list → numpy array
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

    short = np.std(list(wifi_rssi)[-10:])
    long = np.std(list(wifi_rssi)[-60:])
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
# CSV LOGGING
# ======================
LOG_FILE = "activity_audio_timeline.csv"

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp",
            "wifi_std",
            "ble_rate",
            "digital_audio_score",
            "beamformed_score",
            "digital_audio_detected",
            "beamformed_detected",
            "top_ble_beacons"
        ])

def log_csv(digital, d_score, beam, b_score, ble_rate):
    beacons = top_ble_beacons()
    beacon_str = ";".join(f"{m[-5:]}:{r:.1f}" for m, r in beacons)

    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            f"{np.std(wifi_rssi):.2f}",
            ble_rate,
            f"{d_score:.2f}",
            f"{b_score:.2f}",
            digital,
            beam,
            beacon_str
        ])

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class AudioPathGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Digital Audio / Beamforming Detection")

        self.status = QLabel("Starting…")
        layout = QVBoxLayout()
        layout.addWidget(self.status)
        self.setLayout(layout)

    def update_view(self):
        now = time.time()
        ble_rate = sum(1 for t in ble_packets_window if now - t < 5)

        digital, d_score = detect_digital_audio_path()
        beam, b_score = detect_beamformed_audio()

        log_csv(digital, d_score, beam, b_score, ble_rate)

        beacon_text = ", ".join(
            f"{m[-5:]}:{r:.1f}" for m, r in top_ble_beacons()
        )

        self.status.setText(
            f"Digital Audio Path: {digital} (score {d_score:.2f})\n"
            f"Beamformed Audio: {beam} (score {b_score:.2f})\n"
            f"BLE rate: {ble_rate}\n"
            f"Top BLE beacons: {beacon_text}"
        )

# ======================
# MAIN
# ======================
def main():
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()
    threading.Thread(target=wifi_loop, daemon=True).start()

    app = QApplication(sys.argv)
    gui = AudioPathGUI()
    gui.show()

    timer = QTimer()
    timer.timeout.connect(gui.update_view)
    timer.start(1000)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
