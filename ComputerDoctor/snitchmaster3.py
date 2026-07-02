#!/usr/bin/env python3
"""
Real Signal Injection Detection System

This is NOT a simulator - it reads actual sensor data from your system:
- Real WiFi/Network data from /proc and iwconfig
- Real Bluetooth devices via hcitool/bluetoothctl
- Real audio input from microphone
- Real GPS from gpsd (if available)
- Real touch/input events from /dev/input
- Real accelerometer/gyroscope from /sys (if available on device)

Requirements:
    pip install numpy pyaudio --break-system-packages

Optional for full functionality:
    sudo apt install wireless-tools bluez gpsd gpsd-clients

Run with:
    python3 real_signal_injection_detector.py
    
For Bluetooth scanning (requires root):
    sudo python3 real_signal_injection_detector.py
"""

import os
import sys
import time
import struct
import subprocess
import threading
import queue
import hashlib
import select
from collections import deque
from datetime import datetime
from pathlib import Path
import argparse

import numpy as np

# Optional imports
try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    HAVE_PYAUDIO = False


# =============================================================================
# REAL SENSOR READERS
# =============================================================================

class RealWiFiSensor:
    """Read real WiFi CSI-like data and signal information"""
    
    def __init__(self):
        self.rssi_history = deque(maxlen=100)
        self.packet_hashes = deque(maxlen=1000)
        self.last_stats = {}
        self.interface = self._find_wifi_interface()
        
    def _find_wifi_interface(self):
        """Find the active WiFi interface"""
        try:
            wireless_path = Path('/proc/net/wireless')
            if wireless_path.exists():
                content = wireless_path.read_text()
                for line in content.split('\n')[2:]:
                    if line.strip():
                        return line.split()[0].rstrip(':')
        except Exception:
            pass
        
        # Fallback: check /sys/class/net
        try:
            net_path = Path('/sys/class/net')
            for iface in net_path.iterdir():
                wireless_dir = iface / 'wireless'
                if wireless_dir.exists():
                    return iface.name
        except Exception:
            pass
            
        return None
    
    def read_signal_data(self):
        """Read real WiFi signal data (simulates CSI reading)"""
        data = {
            'interface': self.interface,
            'ssid': None,
            'rssi': None,
            'noise': None,
            'quality': None,
            'frequency': None,
            'bitrate': None,
            'rx_packets': 0,
            'tx_packets': 0,
            'rx_bytes': 0,
            'tx_bytes': 0,
            'timestamp': time.time()
        }
        
        # Read from /proc/net/wireless
        try:
            with open('/proc/net/wireless', 'r') as f:
                lines = f.readlines()
                for line in lines[2:]:
                    parts = line.split()
                    if len(parts) >= 5:
                        data['interface'] = parts[0].rstrip(':')
                        data['quality'] = float(parts[2].rstrip('.'))
                        data['rssi'] = int(float(parts[3].rstrip('.')))
                        if len(parts) > 4:
                            data['noise'] = int(float(parts[4].rstrip('.')))
        except (FileNotFoundError, IndexError, ValueError):
            pass
        
        # Get more details via iwconfig
        if self.interface:
            try:
                result = subprocess.run(
                    ['iwconfig', self.interface],
                    capture_output=True, text=True, timeout=2
                )
                output = result.stdout
                
                # Parse ESSID
                if 'ESSID:' in output:
                    start = output.find('ESSID:"') + 7
                    end = output.find('"', start)
                    if start > 6 and end > start:
                        data['ssid'] = output[start:end]
                
                # Parse frequency
                if 'Frequency:' in output:
                    import re
                    match = re.search(r'Frequency[=:]?\s*([\d.]+)', output)
                    if match:
                        data['frequency'] = float(match.group(1))
                        
                # Parse bitrate
                if 'Bit Rate' in output:
                    import re
                    match = re.search(r'Bit Rate[=:]?\s*([\d.]+)', output)
                    if match:
                        data['bitrate'] = float(match.group(1))
                        
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        
        # Read packet statistics from /proc/net/dev
        try:
            with open('/proc/net/dev', 'r') as f:
                for line in f.readlines()[2:]:
                    parts = line.split()
                    if len(parts) >= 17:
                        iface = parts[0].rstrip(':')
                        if iface == self.interface or (self.interface is None and iface.startswith('wl')):
                            data['rx_bytes'] = int(parts[1])
                            data['rx_packets'] = int(parts[2])
                            data['tx_bytes'] = int(parts[9])
                            data['tx_packets'] = int(parts[10])
        except (FileNotFoundError, IndexError, ValueError):
            pass
            
        return data
    
    def create_packet_signature(self, data):
        """Create a signature from network data for replay detection"""
        sig_data = f"{data['rx_packets']}:{data['tx_packets']}:{data['rssi']}:{data['timestamp']}"
        return hashlib.sha256(sig_data.encode()).hexdigest()


class RealBluetoothSensor:
    """Read real Bluetooth device data"""
    
    def __init__(self):
        self.device_history = {}
        self.known_devices = {}
        self.scan_available = self._check_bluetooth()
        
    def _check_bluetooth(self):
        """Check if Bluetooth tools are available"""
        try:
            result = subprocess.run(['which', 'hcitool'], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def _check_adapter_up(self):
        """Check if Bluetooth adapter is up"""
        try:
            result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=2)
            return 'UP RUNNING' in result.stdout
        except Exception:
            return False
    
    def scan_devices(self, duration=2):
        """Scan for real Bluetooth devices"""
        devices = []
        
        if not self.scan_available:
            return devices
            
        if not self._check_adapter_up():
            return devices
        
        # Try LE scan (requires root)
        try:
            result = subprocess.run(
                ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
                capture_output=True, text=True, timeout=duration+2
            )
            
            seen = set()
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line and ':' in line:
                    parts = line.split(' ', 1)
                    mac = parts[0]
                    if mac not in seen and len(mac) == 17:
                        name = parts[1] if len(parts) > 1 else 'Unknown'
                        devices.append({
                            'mac': mac,
                            'name': name,
                            'type': 'LE',
                            'timestamp': time.time()
                        })
                        seen.add(mac)
                        
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            pass
        
        # Fallback: try bluetoothctl
        if not devices:
            try:
                result = subprocess.run(
                    ['bluetoothctl', 'devices'],
                    capture_output=True, text=True, timeout=3
                )
                
                for line in result.stdout.split('\n'):
                    if line.startswith('Device '):
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            mac = parts[1]
                            name = parts[2] if len(parts) > 2 else 'Unknown'
                            devices.append({
                                'mac': mac,
                                'name': name,
                                'type': 'paired',
                                'timestamp': time.time()
                            })
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
                
        return devices
    
    def get_device_rssi(self, mac):
        """Get RSSI for a specific device"""
        try:
            result = subprocess.run(
                ['hcitool', 'rssi', mac],
                capture_output=True, text=True, timeout=3
            )
            if 'RSSI return value:' in result.stdout:
                return int(result.stdout.split(':')[1].strip())
        except Exception:
            pass
        return None
    
    def check_rssi_anomaly(self, mac, rssi, timestamp):
        """Check for RSSI teleportation (spoofing indicator)"""
        if rssi is None:
            return False, None
            
        if mac not in self.device_history:
            self.device_history[mac] = [(timestamp, rssi)]
            return False, None
        
        history = self.device_history[mac]
        if len(history) > 0:
            last_ts, last_rssi = history[-1]
            time_diff = max(timestamp - last_ts, 0.001)
            rssi_diff = abs(rssi - last_rssi)
            
            # Max realistic change: ~5 dB per second (walking speed)
            max_change = time_diff * 5 + 10  # +10 margin
            
            if rssi_diff > max_change:
                history.append((timestamp, rssi))
                return True, f"RSSI teleportation: {rssi_diff:.0f}dB in {time_diff:.1f}s"
        
        history.append((timestamp, rssi))
        if len(history) > 100:
            history.pop(0)
            
        return False, None


class RealAudioSensor:
    """Read real audio from microphone"""
    
    # Sample rates to try (in order of preference)
    SAMPLE_RATES = [48000, 44100, 32000, 22050, 16000, 8000]
    
    def __init__(self, sample_rate=None, chunk_size=4096):
        self.sample_rate = sample_rate  # None = auto-detect
        self.chunk_size = chunk_size
        self.audio = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.audio_hashes = deque(maxlen=100)
        self.available = HAVE_PYAUDIO
        self.device_index = None
        self.device_name = None
        
    def _try_unmute_mic(self):
        """Try to unmute microphone using pactl/amixer"""
        try:
            # Try PulseAudio first
            subprocess.run(
                ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
                capture_output=True, timeout=2
            )
            subprocess.run(
                ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
                capture_output=True, timeout=2
            )
        except Exception:
            pass
        
        try:
            # Try ALSA amixer as fallback
            subprocess.run(
                ['amixer', 'set', 'Capture', 'cap'],
                capture_output=True, timeout=2
            )
            subprocess.run(
                ['amixer', 'set', 'Capture', '100%'],
                capture_output=True, timeout=2
            )
        except Exception:
            pass
    
    def _find_working_config(self):
        """Find a working sample rate and device"""
        if not self.available:
            return None, None, None
        
        try:
            p = pyaudio.PyAudio()
            
            # Find input devices
            input_devices = []
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    input_devices.append((i, info))
            
            if not input_devices:
                p.terminate()
                return None, None, None
            
            # Try each device with each sample rate
            for device_index, device_info in input_devices:
                # If sample rate specified, try only that one
                rates_to_try = [self.sample_rate] if self.sample_rate else self.SAMPLE_RATES
                
                for rate in rates_to_try:
                    try:
                        stream = p.open(
                            format=pyaudio.paFloat32,
                            channels=1,
                            rate=rate,
                            input=True,
                            input_device_index=device_index,
                            frames_per_buffer=self.chunk_size
                        )
                        # Try reading a sample
                        stream.read(self.chunk_size, exception_on_overflow=False)
                        stream.stop_stream()
                        stream.close()
                        p.terminate()
                        return device_index, device_info['name'], rate
                    except Exception:
                        continue
            
            p.terminate()
            return None, None, None
            
        except Exception:
            return None, None, None
        
    def start(self):
        """Start audio capture from microphone"""
        if not self.available:
            return False
        
        # Try to unmute mic first (especially for Kali/PulseAudio)
        self._try_unmute_mic()
        
        # Find working configuration
        self.device_index, self.device_name, detected_rate = self._find_working_config()
        
        if self.device_index is None:
            print("No working audio input configuration found")
            return False
        
        # Use detected rate if not specified
        if self.sample_rate is None:
            self.sample_rate = detected_rate
            
        try:
            self.audio = pyaudio.PyAudio()
            
            self.stream = self.audio.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size
            )
            
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            
            print(f"    Audio: {self.device_name} @ {self.sample_rate}Hz")
            return True
            
        except Exception as e:
            print(f"Audio initialization failed: {e}")
            return False
    
    def _capture_loop(self):
        """Background audio capture"""
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio_array = np.frombuffer(data, dtype=np.float32)
                if not self.audio_queue.full():
                    self.audio_queue.put(audio_array)
            except Exception:
                time.sleep(0.01)
    
    def get_sample(self):
        """Get latest audio sample"""
        try:
            return self.audio_queue.get_nowait()
        except queue.Empty:
            return None
    
    def analyze(self, audio_data):
        """Analyze audio for injection attacks"""
        if audio_data is None or len(audio_data) == 0:
            return None
            
        results = {
            'rms': float(np.sqrt(np.mean(audio_data**2))),
            'peak': float(np.max(np.abs(audio_data))),
            'timestamp': time.time()
        }
        
        # FFT analysis
        fft = np.fft.rfft(audio_data)
        freqs = np.fft.rfftfreq(len(audio_data), 1/self.sample_rate)
        magnitude = np.abs(fft)
        
        # Ultrasonic detection (18-22 kHz)
        ultrasonic_mask = (freqs >= 18000) & (freqs <= 22000)
        results['ultrasonic_energy'] = float(np.sum(magnitude[ultrasonic_mask]))
        
        # Audible range (300-3400 Hz for voice)
        audible_mask = (freqs >= 300) & (freqs <= 3400)
        results['audible_energy'] = float(np.sum(magnitude[audible_mask]))
        
        # Check for ultrasonic injection
        results['ultrasonic_suspicious'] = False
        if results['audible_energy'] > 0:
            ratio = results['ultrasonic_energy'] / results['audible_energy']
            if ratio > 0.2:
                results['ultrasonic_suspicious'] = True
                results['ultrasonic_ratio'] = ratio
        
        # Replay detection via fingerprinting
        audio_hash = hashlib.md5(audio_data.tobytes()).hexdigest()
        results['replay_detected'] = audio_hash in self.audio_hashes
        self.audio_hashes.append(audio_hash)
        
        return results
    
    def stop(self):
        """Stop audio capture"""
        self.running = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.audio:
            try:
                self.audio.terminate()
            except Exception:
                pass


class RealTouchSensor:
    """Read real touch/input events from /dev/input"""
    
    # Input event structure: time (16 bytes), type (2), code (2), value (4)
    EVENT_FORMAT = 'llHHI'
    EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
    
    # Event types
    EV_SYN = 0x00
    EV_KEY = 0x01
    EV_REL = 0x02
    EV_ABS = 0x03
    
    def __init__(self):
        self.devices = []
        self.touch_history = deque(maxlen=100)
        self.event_queue = queue.Queue(maxsize=100)
        self.running = False
        self.threads = []
        self._find_input_devices()
        
    def _find_input_devices(self):
        """Find touchscreen and other input devices"""
        self.devices = []
        
        # Parse /proc/bus/input/devices
        try:
            with open('/proc/bus/input/devices', 'r') as f:
                content = f.read()
                
            current_device = {}
            for line in content.split('\n'):
                if line.startswith('I:'):
                    current_device = {'info': line}
                elif line.startswith('N:'):
                    current_device['name'] = line.split('"')[1] if '"' in line else ''
                elif line.startswith('H:'):
                    handlers = line.split('=')[1] if '=' in line else ''
                    for handler in handlers.split():
                        if handler.startswith('event'):
                            current_device['event'] = f'/dev/input/{handler}'
                            
                            # Check if it's a touch device
                            if any(x in current_device.get('name', '').lower() 
                                   for x in ['touch', 'ts', 'screen', 'digitizer']):
                                self.devices.append(current_device.copy())
                                
        except (FileNotFoundError, PermissionError):
            pass
        
        # Fallback: just list event devices
        if not self.devices:
            input_path = Path('/dev/input')
            if input_path.exists():
                for event in sorted(input_path.glob('event*')):
                    self.devices.append({
                        'event': str(event),
                        'name': event.name
                    })
    
    def start(self):
        """Start monitoring input events"""
        self.running = True
        
        for device in self.devices[:3]:  # Monitor first 3 devices
            try:
                thread = threading.Thread(
                    target=self._monitor_device,
                    args=(device['event'],),
                    daemon=True
                )
                thread.start()
                self.threads.append(thread)
            except Exception:
                pass
                
        return len(self.threads) > 0
    
    def _monitor_device(self, device_path):
        """Monitor a single input device"""
        try:
            with open(device_path, 'rb') as f:
                while self.running:
                    # Use select for non-blocking read
                    r, _, _ = select.select([f], [], [], 0.1)
                    if r:
                        event_data = f.read(self.EVENT_SIZE)
                        if len(event_data) == self.EVENT_SIZE:
                            event = struct.unpack(self.EVENT_FORMAT, event_data)
                            tv_sec, tv_usec, ev_type, code, value = event
                            
                            if ev_type in [self.EV_KEY, self.EV_ABS]:
                                if not self.event_queue.full():
                                    self.event_queue.put({
                                        'timestamp': tv_sec + tv_usec / 1000000,
                                        'type': ev_type,
                                        'code': code,
                                        'value': value,
                                        'device': device_path
                                    })
        except (PermissionError, FileNotFoundError, OSError):
            pass
    
    def get_events(self):
        """Get recent input events"""
        events = []
        while not self.event_queue.empty():
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events
    
    def analyze_touch_physics(self, events):
        """Analyze touch events for injection indicators"""
        results = {
            'event_count': len(events),
            'suspicious': False,
            'issues': []
        }
        
        if not events:
            return results
        
        # Check timing patterns
        timestamps = [e['timestamp'] for e in events]
        if len(timestamps) > 5:
            intervals = np.diff(timestamps)
            if len(intervals) > 0:
                interval_std = np.std(intervals)
                
                # Too regular timing = possible injection
                if interval_std < 0.0001 and len(intervals) > 10:
                    results['suspicious'] = True
                    results['issues'].append("Suspiciously regular event timing")
        
        # Check for impossible event rates
        if len(events) > 0:
            duration = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 1
            if duration > 0:
                rate = len(events) / duration
                if rate > 1000:  # More than 1000 events/sec
                    results['suspicious'] = True
                    results['issues'].append(f"Impossible event rate: {rate:.0f}/sec")
        
        return results
    
    def stop(self):
        """Stop monitoring"""
        self.running = False


class RealGPSSensor:
    """Read real GPS data from gpsd"""
    
    def __init__(self):
        self.location_history = deque(maxlen=100)
        self.available = self._check_gpsd()
        
    def _check_gpsd(self):
        """Check if gpsd is available"""
        try:
            result = subprocess.run(['which', 'gpspipe'], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def read_location(self):
        """Read current GPS location"""
        location = {
            'latitude': None,
            'longitude': None,
            'altitude': None,
            'speed': None,
            'timestamp': time.time(),
            'available': False
        }
        
        if not self.available:
            return location
        
        try:
            result = subprocess.run(
                ['gpspipe', '-w', '-n', '5'],
                capture_output=True, text=True, timeout=3
            )
            
            if result.returncode == 0:
                import json
                for line in result.stdout.split('\n'):
                    try:
                        data = json.loads(line)
                        if data.get('class') == 'TPV':
                            location['latitude'] = data.get('lat')
                            location['longitude'] = data.get('lon')
                            location['altitude'] = data.get('alt')
                            location['speed'] = data.get('speed')
                            location['available'] = True
                            break
                    except json.JSONDecodeError:
                        continue
                        
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
            
        return location
    
    def check_spoofing(self, lat, lon, timestamp):
        """Check for GPS spoofing indicators"""
        if lat is None or lon is None:
            return False, None
        
        if len(self.location_history) > 0:
            last = self.location_history[-1]
            last_ts, last_lat, last_lon = last
            
            time_diff = max(timestamp - last_ts, 0.001)
            
            # Calculate distance (approximate meters)
            lat_diff = abs(lat - last_lat) * 111000
            lon_diff = abs(lon - last_lon) * 111000 * np.cos(np.radians(lat))
            distance = np.sqrt(lat_diff**2 + lon_diff**2)
            
            speed = distance / time_diff  # m/s
            
            # Check for impossible movement
            if speed > 340:  # Speed of sound
                self.location_history.append((timestamp, lat, lon))
                return True, f"Impossible GPS speed: {speed:.0f} m/s"
            elif speed > 100:  # 360 km/h
                self.location_history.append((timestamp, lat, lon))
                return True, f"Suspicious GPS speed: {speed:.0f} m/s"
        
        self.location_history.append((timestamp, lat, lon))
        return False, None


class RealAccelerometerSensor:
    """Read real accelerometer data (for devices with IMU)"""
    
    def __init__(self):
        self.device_path = self._find_accelerometer()
        self.history = deque(maxlen=100)
        
    def _find_accelerometer(self):
        """Find accelerometer in /sys"""
        iio_path = Path('/sys/bus/iio/devices')
        if not iio_path.exists():
            return None
            
        for device in iio_path.iterdir():
            name_file = device / 'name'
            if name_file.exists():
                name = name_file.read_text().strip().lower()
                if 'accel' in name:
                    return device
                    
        return None
    
    def read_data(self):
        """Read accelerometer data"""
        data = {
            'x': None,
            'y': None,
            'z': None,
            'timestamp': time.time(),
            'available': False
        }
        
        if not self.device_path:
            return data
        
        try:
            for axis in ['x', 'y', 'z']:
                raw_file = self.device_path / f'in_accel_{axis}_raw'
                if raw_file.exists():
                    data[axis] = float(raw_file.read_text().strip())
                    data['available'] = True
        except (ValueError, PermissionError, FileNotFoundError):
            pass
            
        return data
    
    def check_anomaly(self, accel_data):
        """Check for accelerometer anomalies"""
        if not accel_data['available']:
            return False, None
            
        x, y, z = accel_data['x'], accel_data['y'], accel_data['z']
        if None in [x, y, z]:
            return False, None
            
        magnitude = np.sqrt(x**2 + y**2 + z**2)
        
        self.history.append(magnitude)
        
        if len(self.history) > 20:
            recent = list(self.history)[-20:]
            std = np.std(recent)
            
            # Perfectly still readings are suspicious (device should have some noise)
            if std < 0.01:
                return True, "Suspiciously stable accelerometer (possible spoofing)"
                
        return False, None


# =============================================================================
# MAIN DETECTION SYSTEM
# =============================================================================

class RealSignalInjectionDetector:
    """Main detection system using real sensors"""
    
    def __init__(self):
        print("Initializing Real Signal Injection Detector...")
        print()
        
        # Initialize sensors
        self.wifi = RealWiFiSensor()
        self.bluetooth = RealBluetoothSensor()
        self.audio = RealAudioSensor()
        self.touch = RealTouchSensor()
        self.gps = RealGPSSensor()
        self.accel = RealAccelerometerSensor()
        
        # State tracking
        self.threat_log = deque(maxlen=1000)
        self.start_time = time.time()
        self.sample_count = 0
        
        # Detection state
        self.wifi_rssi_history = deque(maxlen=50)
        self.last_wifi_data = None
        
    def initialize(self):
        """Initialize all sensors"""
        status = {}
        
        # WiFi
        status['wifi'] = self.wifi.interface is not None
        print(f"  {'✓' if status['wifi'] else '✗'} WiFi sensor ({self.wifi.interface or 'not found'})")
        
        # Bluetooth
        status['bluetooth'] = self.bluetooth.scan_available
        print(f"  {'✓' if status['bluetooth'] else '✗'} Bluetooth sensor")
        
        # Audio
        status['audio'] = self.audio.start()
        print(f"  {'✓' if status['audio'] else '✗'} Audio sensor (microphone)")
        
        # Touch
        status['touch'] = self.touch.start()
        print(f"  {'✓' if status['touch'] else '✗'} Touch/Input sensor ({len(self.touch.devices)} devices)")
        
        # GPS
        status['gps'] = self.gps.available
        print(f"  {'✓' if status['gps'] else '✗'} GPS sensor")
        
        # Accelerometer
        status['accel'] = self.accel.device_path is not None
        print(f"  {'✓' if status['accel'] else '✗'} Accelerometer sensor")
        
        print()
        return status
    
    def collect_and_analyze(self):
        """Collect data from all sensors and analyze for threats"""
        timestamp = time.time()
        threats = []
        
        data = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'wifi': {},
            'bluetooth': {},
            'audio': {},
            'touch': {},
            'gps': {},
            'accel': {}
        }
        
        # === WiFi Analysis ===
        wifi_data = self.wifi.read_signal_data()
        data['wifi'] = wifi_data
        
        if wifi_data['rssi'] is not None:
            self.wifi_rssi_history.append(wifi_data['rssi'])
            
            # Check for RSSI anomalies
            if len(self.wifi_rssi_history) > 10:
                rssi_std = np.std(list(self.wifi_rssi_history)[-10:])
                
                # Too stable RSSI might indicate replay/injection
                if rssi_std < 0.5:
                    threats.append(('WiFi', 'Suspiciously stable RSSI (possible replay)'))
                
                # Sudden large change
                if self.last_wifi_data and self.last_wifi_data['rssi']:
                    rssi_change = abs(wifi_data['rssi'] - self.last_wifi_data['rssi'])
                    if rssi_change > 20:
                        threats.append(('WiFi', f'Sudden RSSI change: {rssi_change} dB'))
        
        # Check for packet replay (same packet stats = replay attack)
        if self.last_wifi_data:
            if (wifi_data['rx_packets'] == self.last_wifi_data['rx_packets'] and
                wifi_data['tx_packets'] == self.last_wifi_data['tx_packets'] and
                wifi_data['rx_packets'] > 0):
                # Only flag if packets should be changing
                pass  # Might be normal if no traffic
                
        self.last_wifi_data = wifi_data
        
        # === Bluetooth Analysis ===
        if self.bluetooth.scan_available:
            # Don't scan every cycle (too slow)
            if self.sample_count % 10 == 0:
                devices = self.bluetooth.scan_devices(duration=1)
                data['bluetooth']['devices'] = devices
                data['bluetooth']['count'] = len(devices)
                
                for device in devices:
                    rssi = self.bluetooth.get_device_rssi(device['mac'])
                    if rssi is not None:
                        is_anomaly, msg = self.bluetooth.check_rssi_anomaly(
                            device['mac'], rssi, timestamp
                        )
                        if is_anomaly:
                            threats.append(('Bluetooth', msg))
        
        # === Audio Analysis ===
        audio_sample = self.audio.get_sample()
        if audio_sample is not None:
            audio_analysis = self.audio.analyze(audio_sample)
            data['audio'] = audio_analysis
            
            if audio_analysis:
                if audio_analysis.get('ultrasonic_suspicious'):
                    threats.append(('Audio', f"Ultrasonic injection detected (ratio: {audio_analysis.get('ultrasonic_ratio', 0):.2f})"))
                    
                if audio_analysis.get('replay_detected'):
                    threats.append(('Audio', 'Audio replay attack detected'))
        
        # === Touch Analysis ===
        touch_events = self.touch.get_events()
        if touch_events:
            touch_analysis = self.touch.analyze_touch_physics(touch_events)
            data['touch'] = touch_analysis
            
            if touch_analysis['suspicious']:
                for issue in touch_analysis['issues']:
                    threats.append(('Touch', issue))
        
        # === GPS Analysis ===
        if self.gps.available:
            gps_data = self.gps.read_location()
            data['gps'] = gps_data
            
            if gps_data['latitude'] is not None:
                is_spoofed, msg = self.gps.check_spoofing(
                    gps_data['latitude'],
                    gps_data['longitude'],
                    timestamp
                )
                if is_spoofed:
                    threats.append(('GPS', msg))
        
        # === Accelerometer Analysis ===
        accel_data = self.accel.read_data()
        data['accel'] = accel_data
        
        if accel_data['available']:
            is_anomaly, msg = self.accel.check_anomaly(accel_data)
            if is_anomaly:
                threats.append(('Accelerometer', msg))
        
        # === Calculate Risk Level ===
        threat_count = len(threats)
        if threat_count >= 3:
            risk_level = 'CRITICAL'
        elif threat_count >= 2:
            risk_level = 'HIGH'
        elif threat_count >= 1:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'
        
        data['threats'] = threats
        data['risk_level'] = risk_level
        
        self.sample_count += 1
        return data
    
    def display_dashboard(self, data):
        """Display real-time dashboard"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        # Header
        print("╔" + "═" * 72 + "╗")
        print("║" + " " * 15 + "REAL SIGNAL INJECTION DETECTOR" + " " * 26 + "║")
        print("║" + f"  {data['datetime'][:19]}   Sample #{self.sample_count}   Runtime: {time.time()-self.start_time:.0f}s" + " " * 12 + "║")
        print("╚" + "═" * 72 + "╝")
        print()
        
        # WiFi Status
        wifi = data.get('wifi', {})
        print("┌─ WiFi/CSI SENSOR " + "─" * 54 + "┐")
        if wifi.get('ssid'):
            print(f"│  SSID: {wifi['ssid']:<63}│")
        if wifi.get('rssi') is not None:
            print(f"│  Signal: {wifi['rssi']} dBm   Quality: {wifi.get('quality', 'N/A')}" + " " * 40 + "│")
        if wifi.get('rx_packets'):
            print(f"│  Packets RX: {wifi['rx_packets']:,}   TX: {wifi['tx_packets']:,}" + " " * 34 + "│")
        if not wifi.get('ssid') and wifi.get('rssi') is None:
            print("│  No WiFi connection detected" + " " * 42 + "│")
        print("└" + "─" * 72 + "┘")
        print()
        
        # Bluetooth Status
        bt = data.get('bluetooth', {})
        print("┌─ BLUETOOTH SENSOR " + "─" * 53 + "┐")
        if bt.get('count', 0) > 0:
            print(f"│  Devices found: {bt['count']}" + " " * 53 + "│")
            for dev in bt.get('devices', [])[:3]:
                name = dev.get('name', 'Unknown')[:40]
                print(f"│    {dev['mac']} - {name}" + " " * (40 - len(name)) + "│")
        else:
            status = "Ready" if self.bluetooth.scan_available else "Not available"
            print(f"│  Status: {status}" + " " * (60 - len(status)) + "│")
        print("└" + "─" * 72 + "┘")
        print()
        
        # Audio Status
        audio = data.get('audio', {})
        print("┌─ AUDIO SENSOR " + "─" * 57 + "┐")
        if audio:
            print(f"│  Level (RMS): {audio.get('rms', 0):.4f}   Peak: {audio.get('peak', 0):.4f}" + " " * 33 + "│")
            print(f"│  Ultrasonic Energy: {audio.get('ultrasonic_energy', 0):.1f}" + " " * 47 + "│")
            if audio.get('ultrasonic_suspicious'):
                print(f"│  ⚠  ULTRASONIC INJECTION DETECTED" + " " * 36 + "│")
        else:
            print("│  No audio data (microphone not available or silent)" + " " * 19 + "│")
        print("└" + "─" * 72 + "┘")
        print()
        
        # GPS Status
        gps = data.get('gps', {})
        print("┌─ GPS SENSOR " + "─" * 59 + "┐")
        if gps.get('latitude'):
            print(f"│  Location: {gps['latitude']:.6f}, {gps['longitude']:.6f}" + " " * 37 + "│")
            if gps.get('speed'):
                print(f"│  Speed: {gps['speed']:.1f} m/s" + " " * 56 + "│")
        else:
            print("│  GPS not available" + " " * 52 + "│")
        print("└" + "─" * 72 + "┘")
        print()
        
        # Threat Assessment
        risk_colors = {
            'LOW': '\033[92m',
            'MEDIUM': '\033[93m',
            'HIGH': '\033[91m',
            'CRITICAL': '\033[95m'
        }
        reset = '\033[0m'
        color = risk_colors.get(data['risk_level'], '')
        
        print("┌─ THREAT ASSESSMENT " + "─" * 52 + "┐")
        print(f"│  Risk Level: {color}{data['risk_level']}{reset}" + " " * (57 - len(data['risk_level'])) + "│")
        print(f"│  Active Threats: {len(data['threats'])}" + " " * 52 + "│")
        print("│" + " " * 72 + "│")
        
        if data['threats']:
            for threat_type, message in data['threats'][:5]:
                line = f"│  🚨 [{threat_type}] {message}"
                padding = 73 - len(line) + 4  # +4 for emoji
                print(line + " " * max(0, padding) + "│")
        else:
            print("│  ✅ All sensors normal - No injection detected" + " " * 24 + "│")
        
        print("└" + "─" * 72 + "┘")
        print()
        print("  Press Ctrl+C to stop")
    
    def run(self, interval=1.0):
        """Run continuous monitoring"""
        try:
            while True:
                data = self.collect_and_analyze()
                self.display_dashboard(data)
                
                # Log threats
                for threat in data['threats']:
                    self.threat_log.append({
                        'timestamp': data['datetime'],
                        'type': threat[0],
                        'message': threat[1]
                    })
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nShutting down...")
            self.cleanup()
            
            if self.threat_log:
                print(f"\n=== Session Summary ===")
                print(f"Duration: {time.time() - self.start_time:.0f} seconds")
                print(f"Samples: {self.sample_count}")
                print(f"Threats detected: {len(self.threat_log)}")
                
                if self.threat_log:
                    print("\nRecent threats:")
                    for threat in list(self.threat_log)[-5:]:
                        print(f"  [{threat['timestamp'][:19]}] {threat['type']}: {threat['message']}")
    
    def cleanup(self):
        """Clean up resources"""
        self.audio.stop()
        self.touch.stop()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Real Signal Injection Detection System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 real_signal_injection_detector.py
    python3 real_signal_injection_detector.py --interval 0.5
    sudo python3 real_signal_injection_detector.py  # For Bluetooth scanning

This tool monitors REAL sensors for injection attacks:
    - WiFi signal anomalies
    - Bluetooth spoofing detection  
    - Ultrasonic audio injection
    - Touch event injection
    - GPS spoofing
    - Accelerometer manipulation
        """
    )
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Monitoring interval in seconds (default: 1.0)')
    
    args = parser.parse_args()
    
    print("=" * 74)
    print("  REAL SIGNAL INJECTION DETECTION SYSTEM")
    print("  Reading from actual hardware sensors - NOT a simulation")
    print("=" * 74)
    print()
    
    detector = RealSignalInjectionDetector()
    status = detector.initialize()
    
    active_sensors = sum(1 for v in status.values() if v)
    print(f"Active sensors: {active_sensors}/{len(status)}")
    print()
    
    if active_sensors == 0:
        print("Warning: No sensors available. The detector will have limited functionality.")
        print("Try running with sudo for Bluetooth, or install pyaudio for audio monitoring.")
        print()
    
    print("Starting real-time monitoring...")
    print("Press Ctrl+C to stop")
    print()
    time.sleep(2)
    
    detector.run(interval=args.interval)


if __name__ == "__main__":
    main()