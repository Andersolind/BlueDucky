import sys
import time
import threading
import subprocess
import asyncio
import csv
import os
from datetime import datetime, timezone
from collections import defaultdict

import numpy as np
from scipy import signal
import sounddevice as sd
import soundfile as sf
from bleak import BleakScanner

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QTextEdit, QLabel,
    QSpinBox, QGroupBox
)
from PyQt5.QtCore import Qt

# =====================================================
# Config
# =====================================================
OUT_DIR = "audio_rf_ble_gui_logs"
os.makedirs(OUT_DIR, exist_ok=True)

AUDIO_FS = 44100
AUDIO_LOW = 300
AUDIO_HIGH = 3000
ENV_THRESHOLD = 0.02

CORR_WINDOW = 1.0
CORR_MIN_HITS = 3
RSSI_SLOPE_WINDOW = 10

KNOWN_DEVICE_HINTS = [
    "tv", "speaker", "roku", "chromecast", "fire",
    "headphone", "earbud", "watch", "fitbit",
    "iphone", "android", "samsung", "apple",
    "keyboard", "mouse"
]

# =====================================================
# Shared State
# =====================================================
audio_pulses = []
ble_seen = defaultdict(list)   # mac -> [(t, rssi)]
ble_names = {}
ble_lock = threading.Lock()

# =====================================================
# Utilities
# =====================================================
def log(ui, msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    ui.append(f"[{ts}] {msg}")
    ui.ensureCursorVisible()

def get_audio_device():
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            return i
    raise RuntimeError("No audio input device")

def is_known_device(name):
    name = (name or "").lower()
    return any(k in name for k in KNOWN_DEVICE_HINTS)

# =====================================================
# Audio Worker
# =====================================================
def audio_worker(ui, duration):
    global audio_pulses
    log(ui, "🎧 Audio capture started")

    fs = AUDIO_FS
    device = get_audio_device()

    data = sd.rec(int(duration * fs), fs, channels=1, device=device, dtype="float32")
    sd.wait()
    audio = data.flatten()

    ts = int(time.time())
    wav_path = f"{OUT_DIR}/audio_{ts}.wav"
    sf.write(wav_path, audio, fs)

    filtered = signal.sosfilt(
        signal.butter(6, [AUDIO_LOW, AUDIO_HIGH], "band", fs=fs, output="sos"),
        audio
    )
    env = np.abs(signal.hilbert(filtered))
    mask = env > ENV_THRESHOLD
    edges = np.diff(mask.astype(int))
    onsets = np.where(edges == 1)[0]

    audio_pulses = [o / fs for o in onsets]

    log(ui, f"🎧 Pulses detected: {len(audio_pulses)}")
    log(ui, f"🎧 Audio saved → {wav_path}")

# =====================================================
# HackRF Worker
# =====================================================
def rf_worker(ui, duration):
    log(ui, "📡 HackRF sweep started")

    ts = int(time.time())
    path = f"{OUT_DIR}/rf_{ts}.csv"

    cmd = [
        "hackrf_sweep",
        "-f", "2400:2483",
        "-w", "200000",
        "-l", "24",
        "-g", "20"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    start = time.time()

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_utc", "freq_low", "freq_high", "power_db"])

        while time.time() - start < duration:
            line = proc.stdout.readline()
            if not line:
                continue
            parts = line.strip().split(",")
            if len(parts) >= 6:
                writer.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    parts[2], parts[3], parts[5]
                ])

    proc.terminate()
    log(ui, f"📡 RF sweep saved → {path}")

# =====================================================
# BLE Worker (FIXED RSSI HANDLING)
# =====================================================
async def ble_async(ui, duration):
    log(ui, "📶 BLE scan started")
    start = time.time()

    def cb(device, advertisement_data):
        t = time.time() - start
        rssi = advertisement_data.rssi
        if rssi is None:
            return

        with ble_lock:
            ble_seen[device.address].append((t, rssi))
            ble_names[device.address] = device.name or advertisement_data.local_name or ""

    scanner = BleakScanner(cb)
    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()

    ts = int(time.time())
    path = f"{OUT_DIR}/ble_{ts}.csv"

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "mac", "rssi", "name"])
        for mac, samples in ble_seen.items():
            for t, rssi in samples:
                writer.writerow([t, mac, rssi, ble_names.get(mac, "")])

    log(ui, f"📶 BLE saved → {path}")

def ble_worker(ui, duration):
    asyncio.run(ble_async(ui, duration))

# =====================================================
# Correlation + Movement
# =====================================================
def correlate_and_report(ui):
    log(ui, "🔗 BLE ↔ Audio correlation")

    with ble_lock:
        for mac, samples in ble_seen.items():
            name = ble_names.get(mac, "")
            if is_known_device(name):
                continue

            hits = 0
            for t, _ in samples:
                for p in audio_pulses:
                    if abs(t - p) <= CORR_WINDOW:
                        hits += 1

            if hits >= CORR_MIN_HITS:
                recent = samples[-RSSI_SLOPE_WINDOW:]
                if len(recent) >= 3:
                    ys = [r for _, r in recent]
                    xs = list(range(len(ys)))
                    slope = np.polyfit(xs, ys, 1)[0]
                else:
                    slope = 0.0

                motion = "approaching" if slope > 0.3 else "receding" if slope < -0.3 else "static"
                log(ui, f"🔗 {mac} hits={hits} slope={slope:.2f} motion={motion} name={name}")

# =====================================================
# GUI
# =====================================================
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio • RF • BLE Correlation Monitor")
        self.resize(820, 560)

        self.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #e0e0e0;
                font-size: 14px;
            }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 6px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #1e88e5;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #42a5f5;
            }
            QCheckBox {
                padding: 4px;
            }
            QTextEdit {
                background-color: #0d0d0d;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)

        layout = QVBoxLayout(self)

        # === Controls ===
        group = QGroupBox("Modules")
        g_layout = QVBoxLayout()

        self.chk_audio = QCheckBox("🎧 Audio analysis")
        self.chk_rf = QCheckBox("📡 HackRF sweep")
        self.chk_ble = QCheckBox("📶 BLE scan")
        self.chk_corr = QCheckBox("🔗 BLE ↔ Audio correlation")

        g_layout.addWidget(self.chk_audio)
        g_layout.addWidget(self.chk_rf)
        g_layout.addWidget(self.chk_ble)
        g_layout.addWidget(self.chk_corr)
        group.setLayout(g_layout)

        # === Duration ===
        dur_box = QHBoxLayout()
        dur_box.addWidget(QLabel("Duration (seconds):"))
        self.duration = QSpinBox()
        self.duration.setRange(10, 3600)
        self.duration.setValue(180)
        dur_box.addWidget(self.duration)

        # === Buttons ===
        btn_box = QHBoxLayout()
        start_btn = QPushButton("START")
        stop_btn = QPushButton("STOP")
        btn_box.addWidget(start_btn)
        btn_box.addWidget(stop_btn)

        # === Log ===
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        layout.addWidget(group)
        layout.addLayout(dur_box)
        layout.addLayout(btn_box)
        layout.addWidget(self.log)

        start_btn.clicked.connect(self.start)
        stop_btn.clicked.connect(self.stop)

    def start(self):
        dur = self.duration.value()
        log(self.log, "▶ Run started")

        if self.chk_audio.isChecked():
            threading.Thread(target=audio_worker, args=(self.log, dur), daemon=True).start()

        if self.chk_rf.isChecked():
            threading.Thread(target=rf_worker, args=(self.log, dur), daemon=True).start()

        if self.chk_ble.isChecked():
            threading.Thread(target=ble_worker, args=(self.log, dur), daemon=True).start()

        if self.chk_corr.isChecked():
            threading.Timer(dur + 1, correlate_and_report, args=(self.log,)).start()

    def stop(self):
        log(self.log, "⏹ Stop requested (threads end naturally)")

# =====================================================
# Entry
# =====================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec_())
