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
# AUDIO LEVEL (dB ONLY)
# ======================
import sounddevice as sd

AUDIO_FS = 16000
AUDIO_WINDOW = 0.1  # seconds

audio_db = 0.0
audio_db_history = deque(maxlen=50)

def audio_loop():
    global audio_db
    while True:
        audio = sd.rec(
            int(AUDIO_WINDOW * AUDIO_FS),
            samplerate=AUDIO_FS,
            channels=1,
            dtype="float32",
            blocking=True,
        )
        rms = np.sqrt(np.mean(audio**2))
        db = 20 * np.log10(rms + 1e-6)
        audio_db = db
        audio_db_history.append(db)

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
ble_seen_time = {}

def detection_callback(device, adv):
    if adv.rssi is None:
        return
    ble_packets_window.append(time.time())
    ble_seen_time[device.address.lower()] = time.time()

async def ble_loop():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    while True:
        await asyncio.sleep(1)

# ======================
# WIFI RSSI
# ======================
wifi_rssi = deque(maxlen=400)

def read_wifi_rssi():
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "IN-USE,SIGNAL", "dev", "wifi", "list"],
            stderr=subprocess.DEVNULL,
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
# AUDIO SPIKE DETECTION
# ======================
def detect_audio_spike():
    if len(audio_db_history) < 10:
        return False

    recent = list(audio_db_history)[-10:]
    baseline = np.mean(recent[:-1])
    return recent[-1] - baseline > 6.0  # ~6 dB jump

def audio_active():
    return audio_db > -40  # room noise threshold

# ======================
# RF GESTURE
# ======================
def classify_gesture():
    if len(wifi_rssi) < 40:
        return "no-data", 0.0

    sig = np.array(list(wifi_rssi)[-40:])
    short = sig[-10:]

    short_std = np.std(short)
    ble_rate = sum(1 for t in ble_packets_window if time.time() - t < 5)
    energy = short_std + ble_rate * 0.3

    if detect_audio_spike() and short_std < 1.0:
        return "audio_impulse", energy

    if short_std < 0.8 and not audio_active():
        return "idle", energy

    if audio_active() and short_std < 1.2:
        return "listening", energy

    if audio_active() and short_std > 1.2:
        return "talking", energy

    if short_std > 2.0:
        return "movement", energy

    return "unknown", energy

# ======================
# GUI
# ======================
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QTimer

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RF + BLE + Audio Correlation Dashboard")
        self.label = QLabel("Starting…")
        self.label.setStyleSheet("font-family: monospace;")
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def update_view(self):
        gesture, energy = classify_gesture()
        spike = detect_audio_spike()

        self.label.setText(
            f"Gesture       : {gesture}\n"
            f"Energy        : {energy:.2f}\n"
            f"Audio dB      : {audio_db:.1f}\n"
            f"Audio spike   : {spike}\n"
            f"BLE devices   : {len(ble_seen_time)}"
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
