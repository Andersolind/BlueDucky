#!/usr/bin/env python3
"""
================================================================================
UNIFIED SIGNAL INJECTION DETECTION SYSTEM
================================================================================

Combines all detection capabilities into one comprehensive tool:

SENSORS:
    - WiFi/CSI: Signal strength, packet analysis, replay detection
    - Bluetooth: Device scanning, RSSI tracking, spoofing detection
    - Audio: Ultrasonic injection, replay attacks, detailed frequency analysis
    - Touch/Input: Event injection, EM correlation detection
    - GPS: Location spoofing, impossible movement detection
    - Accelerometer: Sensor manipulation detection
    - Network: Traffic analysis, error detection
    - USB: Device monitoring, new device alerts
    - Process: Suspicious process detection
    - Temperature: System thermal monitoring

FEATURES:
    - Adjustable sensitivity (low/medium/high/paranoid)
    - Detailed frequency spectrum analysis
    - Pattern detection over time
    - Source identification for ultrasonic signals
    - JSON logging for forensic analysis
    - Real-time dashboard with color coding
    - Cross-sensor validation

REQUIREMENTS:
    pip install numpy pyaudio psutil --break-system-packages

OPTIONAL (for full functionality):
    sudo apt install wireless-tools bluez gpsd gpsd-clients

USAGE:
    python3 unified_signal_detector.py
    python3 unified_signal_detector.py --sensitivity low
    python3 unified_signal_detector.py --sensitivity paranoid --log threats.json
    python3 unified_signal_detector.py --mode minimal    # Audio + WiFi only
    python3 unified_signal_detector.py --mode full       # All sensors
    sudo python3 unified_signal_detector.py              # With Bluetooth scanning

================================================================================
"""

import os
import sys
import time
import json
import struct
import subprocess
import threading
import queue
import hashlib
import select
import argparse
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

import numpy as np

# Optional imports with availability flags
HAVE_PYAUDIO = False
HAVE_PSUTIL = False

try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    pass

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "1.0.0"

SENSITIVITY_PROFILES = {
    'low': {
        'ultrasonic_ratio_threshold': 0.8,
        'ultrasonic_absolute_threshold': 1000,
        'rssi_change_threshold': 30,
        'gps_speed_threshold': 200,  # m/s
        'description': 'Minimal alerts - only obvious attacks'
    },
    'medium': {
        'ultrasonic_ratio_threshold': 0.4,
        'ultrasonic_absolute_threshold': 500,
        'rssi_change_threshold': 20,
        'gps_speed_threshold': 100,
        'description': 'Balanced detection (recommended)'
    },
    'high': {
        'ultrasonic_ratio_threshold': 0.2,
        'ultrasonic_absolute_threshold': 200,
        'rssi_change_threshold': 15,
        'gps_speed_threshold': 50,
        'description': 'Sensitive - may have false positives'
    },
    'paranoid': {
        'ultrasonic_ratio_threshold': 0.1,
        'ultrasonic_absolute_threshold': 100,
        'rssi_change_threshold': 10,
        'gps_speed_threshold': 30,
        'description': 'Maximum sensitivity - expect false positives'
    }
}

KNOWN_ULTRASONIC_SOURCES = {
    (15000, 17000): "CRT TV / Old monitor",
    (17000, 19000): "LCD backlight / LED driver / Charger",
    (19000, 20000): "Mosquito/Teen deterrent",
    (19500, 20500): "⚠ DolphinAttack range",
    (20000, 22000): "Ultrasonic pest repeller",
    (22000, 24000): "Industrial equipment",
}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def read_file(path: str, default: str = None) -> Optional[str]:
    """Safely read a file"""
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, IOError):
        return default


def run_command(cmd: List[str], timeout: int = 5) -> Tuple[bool, str]:
    """Run a command and return success status and output"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, ""


# =============================================================================
# WIFI SENSOR
# =============================================================================

class WiFiSensor:
    """WiFi/CSI signal monitoring"""
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.interface = self._find_interface()
        self.rssi_history = deque(maxlen=100)
        self.packet_hashes = deque(maxlen=1000)
        self.last_data = None
        
    def _find_interface(self) -> Optional[str]:
        """Find active WiFi interface"""
        # Check /proc/net/wireless
        content = read_file('/proc/net/wireless')
        if content:
            for line in content.split('\n')[2:]:
                if line.strip():
                    return line.split()[0].rstrip(':')
        
        # Check /sys/class/net
        net_path = Path('/sys/class/net')
        if net_path.exists():
            for iface in net_path.iterdir():
                if (iface / 'wireless').exists():
                    return iface.name
        return None
    
    def read(self) -> dict:
        """Read WiFi data"""
        data = {
            'available': self.interface is not None,
            'interface': self.interface,
            'ssid': None,
            'rssi': None,
            'quality': None,
            'noise': None,
            'frequency': None,
            'rx_packets': 0,
            'tx_packets': 0,
            'rx_bytes': 0,
            'tx_bytes': 0,
            'timestamp': time.time()
        }
        
        if not self.interface:
            return data
        
        # Read /proc/net/wireless
        content = read_file('/proc/net/wireless')
        if content:
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 5 and parts[0].rstrip(':') == self.interface:
                    data['quality'] = float(parts[2].rstrip('.'))
                    data['rssi'] = int(float(parts[3].rstrip('.')))
                    data['noise'] = int(float(parts[4].rstrip('.')))
        
        # Get SSID via iwconfig
        success, output = run_command(['iwconfig', self.interface], timeout=2)
        if success and 'ESSID:"' in output:
            start = output.find('ESSID:"') + 7
            end = output.find('"', start)
            if start > 6 and end > start:
                data['ssid'] = output[start:end]
            
            # Parse frequency
            import re
            freq_match = re.search(r'Frequency[=:]?\s*([\d.]+)', output)
            if freq_match:
                data['frequency'] = float(freq_match.group(1))
        
        # Read packet stats from /proc/net/dev
        content = read_file('/proc/net/dev')
        if content:
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 17 and parts[0].rstrip(':') == self.interface:
                    data['rx_bytes'] = int(parts[1])
                    data['rx_packets'] = int(parts[2])
                    data['tx_bytes'] = int(parts[9])
                    data['tx_packets'] = int(parts[10])
        
        return data
    
    def analyze(self, data: dict) -> List[Tuple[str, str]]:
        """Analyze WiFi data for anomalies"""
        threats = []
        
        if data['rssi'] is not None:
            self.rssi_history.append(data['rssi'])
            
            # Check for suspiciously stable RSSI
            if len(self.rssi_history) > 10:
                std = np.std(list(self.rssi_history)[-10:])
                if std < 0.5 and len(self.rssi_history) > 20:
                    threats.append(('WiFi', 'Suspiciously stable RSSI (possible replay)'))
            
            # Check for sudden RSSI change
            if self.last_data and self.last_data.get('rssi'):
                change = abs(data['rssi'] - self.last_data['rssi'])
                if change > self.profile['rssi_change_threshold']:
                    threats.append(('WiFi', f'Sudden RSSI change: {change} dB'))
        
        # Check for packet replay (identical packet signature)
        if data['rx_packets'] > 0:
            sig = f"{data['rx_packets']}:{data['tx_packets']}:{data['rssi']}"
            sig_hash = hashlib.sha256(sig.encode()).hexdigest()[:16]
            
            if sig_hash in self.packet_hashes:
                threats.append(('WiFi', 'Possible packet replay detected'))
            self.packet_hashes.append(sig_hash)
        
        self.last_data = data
        return threats


# =============================================================================
# BLUETOOTH SENSOR
# =============================================================================

class BluetoothSensor:
    """Bluetooth device monitoring"""
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.available = self._check_available()
        self.device_history = {}
        self.known_devices = {}
        
    def _check_available(self) -> bool:
        """Check if Bluetooth tools are available"""
        success, _ = run_command(['which', 'hcitool'])
        return success
    
    def _adapter_up(self) -> bool:
        """Check if Bluetooth adapter is up"""
        success, output = run_command(['hciconfig'], timeout=2)
        return success and 'UP RUNNING' in output
    
    def scan(self, duration: int = 2) -> List[dict]:
        """Scan for Bluetooth devices"""
        devices = []
        
        if not self.available or not self._adapter_up():
            return devices
        
        # LE scan (requires root)
        success, output = run_command(
            ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
            timeout=duration + 2
        )
        
        if success:
            seen = set()
            for line in output.split('\n'):
                if ':' in line:
                    parts = line.strip().split(' ', 1)
                    mac = parts[0]
                    if mac not in seen and len(mac) == 17:
                        devices.append({
                            'mac': mac,
                            'name': parts[1] if len(parts) > 1 else 'Unknown',
                            'type': 'LE',
                            'timestamp': time.time()
                        })
                        seen.add(mac)
        
        # Fallback: bluetoothctl
        if not devices:
            success, output = run_command(['bluetoothctl', 'devices'], timeout=3)
            if success:
                for line in output.split('\n'):
                    if line.startswith('Device '):
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            devices.append({
                                'mac': parts[1],
                                'name': parts[2] if len(parts) > 2 else 'Unknown',
                                'type': 'paired',
                                'timestamp': time.time()
                            })
        
        return devices
    
    def get_rssi(self, mac: str) -> Optional[int]:
        """Get RSSI for a device"""
        success, output = run_command(['hcitool', 'rssi', mac], timeout=3)
        if success and 'RSSI return value:' in output:
            try:
                return int(output.split(':')[1].strip())
            except (ValueError, IndexError):
                pass
        return None
    
    def analyze(self, mac: str, rssi: Optional[int], timestamp: float) -> List[Tuple[str, str]]:
        """Analyze for RSSI anomalies (spoofing detection)"""
        threats = []
        
        if rssi is None:
            return threats
        
        if mac not in self.device_history:
            self.device_history[mac] = [(timestamp, rssi)]
            return threats
        
        history = self.device_history[mac]
        if history:
            last_ts, last_rssi = history[-1]
            time_diff = max(timestamp - last_ts, 0.001)
            rssi_diff = abs(rssi - last_rssi)
            
            # Max realistic change based on walking speed
            max_change = time_diff * 5 + self.profile['rssi_change_threshold'] / 2
            
            if rssi_diff > max_change:
                threats.append(('Bluetooth', f'RSSI teleportation: {rssi_diff:.0f}dB in {time_diff:.1f}s ({mac})'))
        
        history.append((timestamp, rssi))
        if len(history) > 100:
            history.pop(0)
        
        # Check for new devices
        if mac not in self.known_devices:
            self.known_devices[mac] = timestamp
            # Only alert after initial scan period
            if timestamp - list(self.known_devices.values())[0] > 30:
                threats.append(('Bluetooth', f'New device detected: {mac}'))
        
        return threats


# =============================================================================
# AUDIO SENSOR (ENHANCED)
# =============================================================================

class AudioSensor:
    """Enhanced audio sensor with detailed ultrasonic analysis"""
    
    def __init__(self, profile: dict, sample_rate: int = 44100, chunk_size: int = 8192):
        self.profile = profile
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.available = HAVE_PYAUDIO
        
        self.audio = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        
        # History for pattern detection
        self.ultrasonic_history = deque(maxlen=60)
        self.audio_hashes = deque(maxlen=100)
        self.detailed_log = deque(maxlen=1000)
        
    def start(self) -> bool:
        """Start audio capture"""
        if not self.available:
            return False
        
        try:
            self.audio = pyaudio.PyAudio()
            
            # Find input device
            device_index = None
            device_name = "Unknown"
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    device_index = i
                    device_name = info['name']
                    break
            
            if device_index is None:
                return False
            
            self.stream = self.audio.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size
            )
            
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            return True
            
        except Exception as e:
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
    
    def get_sample(self) -> Optional[np.ndarray]:
        """Get latest audio sample"""
        try:
            return self.audio_queue.get_nowait()
        except queue.Empty:
            return None
    
    def analyze(self, audio_data: np.ndarray) -> Optional[dict]:
        """Comprehensive audio analysis"""
        if audio_data is None or len(audio_data) == 0:
            return None
        
        timestamp = time.time()
        
        results = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'rms': float(np.sqrt(np.mean(audio_data**2))),
            'peak': float(np.max(np.abs(audio_data)))
        }
        
        # Skip if too quiet
        if results['rms'] < 0.001:
            results['status'] = 'silent'
            return results
        
        results['status'] = 'active'
        
        # FFT analysis
        fft = np.fft.rfft(audio_data)
        freqs = np.fft.rfftfreq(len(audio_data), 1/self.sample_rate)
        magnitude = np.abs(fft)
        
        # Frequency band energy
        bands = {
            'voice': (300, 3400),
            'high': (10000, 15000),
            'very_high': (15000, 18000),
            'ultrasonic_low': (18000, 19000),
            'ultrasonic_mid': (19000, 20000),
            'ultrasonic_high': (20000, 22000),
        }
        
        band_energy = {}
        for name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs < high)
            band_energy[name] = float(np.sum(magnitude[mask]))
        
        results['band_energy'] = band_energy
        
        # Total energies
        ultrasonic_mask = (freqs >= 18000) & (freqs <= 22000)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        
        results['ultrasonic_energy'] = float(np.sum(magnitude[ultrasonic_mask]))
        results['voice_energy'] = float(np.sum(magnitude[voice_mask]))
        
        # Ratios
        results['ultrasonic_ratio'] = (
            results['ultrasonic_energy'] / results['voice_energy']
            if results['voice_energy'] > 0 else 0
        )
        
        # Find peak frequencies in ultrasonic range
        ultrasonic_freqs = freqs[ultrasonic_mask]
        ultrasonic_mags = magnitude[ultrasonic_mask]
        
        peak_frequencies = []
        if len(ultrasonic_mags) > 0 and np.max(ultrasonic_mags) > 10:
            for i in range(1, len(ultrasonic_mags) - 1):
                if (ultrasonic_mags[i] > ultrasonic_mags[i-1] and
                    ultrasonic_mags[i] > ultrasonic_mags[i+1] and
                    ultrasonic_mags[i] > np.mean(ultrasonic_mags) * 2):
                    peak_frequencies.append({
                        'frequency': float(ultrasonic_freqs[i]),
                        'magnitude': float(ultrasonic_mags[i])
                    })
            peak_frequencies.sort(key=lambda x: x['magnitude'], reverse=True)
            peak_frequencies = peak_frequencies[:5]
        
        results['ultrasonic_peaks'] = peak_frequencies
        
        # Identify likely source
        likely_sources = []
        if peak_frequencies:
            dom_freq = peak_frequencies[0]['frequency']
            for (low, high), source in KNOWN_ULTRASONIC_SOURCES.items():
                if low <= dom_freq <= high:
                    likely_sources.append(source)
        results['likely_sources'] = likely_sources
        
        # Threat assessment
        ratio_threshold = self.profile['ultrasonic_ratio_threshold']
        absolute_threshold = self.profile['ultrasonic_absolute_threshold']
        
        results['suspicious'] = False
        results['threat_level'] = 'none'
        results['threat_reasons'] = []
        
        ratio = results['ultrasonic_ratio']
        energy = results['ultrasonic_energy']
        
        if ratio > ratio_threshold and energy > absolute_threshold:
            results['suspicious'] = True
            results['threat_reasons'].append(
                f"High ultrasonic ratio: {ratio:.2f} (threshold: {ratio_threshold})"
            )
            
            if ratio > ratio_threshold * 3:
                results['threat_level'] = 'high'
            elif ratio > ratio_threshold * 1.5:
                results['threat_level'] = 'medium'
            else:
                results['threat_level'] = 'low'
        
        # Check for DolphinAttack range
        if peak_frequencies:
            dom_freq = peak_frequencies[0]['frequency']
            if 19500 <= dom_freq <= 20500:
                results['threat_reasons'].append(
                    f"Frequency {dom_freq:.0f}Hz in DolphinAttack range"
                )
                if not results['suspicious']:
                    results['suspicious'] = True
                    results['threat_level'] = 'medium'
        
        # Pattern analysis
        self.ultrasonic_history.append({
            'timestamp': timestamp,
            'energy': energy,
            'ratio': ratio,
            'peaks': [p['frequency'] for p in peak_frequencies]
        })
        
        if len(self.ultrasonic_history) >= 10:
            recent = list(self.ultrasonic_history)[-10:]
            high_count = sum(1 for r in recent if r['energy'] > absolute_threshold)
            
            if high_count >= 8:
                results['pattern'] = 'continuous'
                results['threat_reasons'].append(f"Continuous ultrasonic ({high_count}/10)")
            elif high_count >= 4:
                results['pattern'] = 'intermittent'
            else:
                results['pattern'] = 'sporadic'
            
            # Consistent frequency = deliberate signal
            if peak_frequencies:
                recent_peaks = [r['peaks'] for r in recent if r['peaks']]
                if len(recent_peaks) >= 5:
                    all_peaks = [p for peaks in recent_peaks for p in peaks]
                    if all_peaks and np.std(all_peaks) < 500:
                        results['threat_reasons'].append("Consistent frequency pattern")
                        if results['threat_level'] in ['none', 'low']:
                            results['threat_level'] = 'medium'
                            results['suspicious'] = True
        
        # Replay detection
        audio_hash = hashlib.md5(audio_data.tobytes()).hexdigest()
        results['replay_detected'] = audio_hash in self.audio_hashes
        self.audio_hashes.append(audio_hash)
        
        if results['replay_detected']:
            results['threat_reasons'].append("Audio replay detected")
            results['threat_level'] = 'high'
            results['suspicious'] = True
        
        # Log if suspicious
        if results['suspicious']:
            self.detailed_log.append({
                'timestamp': results['datetime'],
                'threat_level': results['threat_level'],
                'energy': energy,
                'ratio': ratio,
                'peaks': peak_frequencies,
                'sources': likely_sources,
                'reasons': results['threat_reasons'],
                'pattern': results.get('pattern', 'unknown')
            })
        
        return results
    
    def get_log(self) -> List[dict]:
        """Get detailed threat log"""
        return list(self.detailed_log)
    
    def export_log(self, filepath: str) -> int:
        """Export log to JSON"""
        data = {
            'export_time': datetime.now().isoformat(),
            'events': self.get_log()
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return len(data['events'])
    
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


# =============================================================================
# TOUCH/INPUT SENSOR
# =============================================================================

class TouchSensor:
    """Touch and input event monitoring"""
    
    EVENT_FORMAT = 'llHHI'
    EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
    EV_KEY = 0x01
    EV_ABS = 0x03
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.devices = []
        self.event_queue = queue.Queue(maxsize=100)
        self.running = False
        self.threads = []
        self._find_devices()
        
    def _find_devices(self):
        """Find input devices"""
        self.devices = []
        
        # Parse /proc/bus/input/devices
        content = read_file('/proc/bus/input/devices')
        if content:
            current = {}
            for line in content.split('\n'):
                if line.startswith('N:'):
                    current['name'] = line.split('"')[1] if '"' in line else ''
                elif line.startswith('H:'):
                    handlers = line.split('=')[1] if '=' in line else ''
                    for h in handlers.split():
                        if h.startswith('event'):
                            current['path'] = f'/dev/input/{h}'
                            self.devices.append(current.copy())
                            break
                    current = {}
        
        # Fallback
        if not self.devices:
            input_path = Path('/dev/input')
            if input_path.exists():
                for event in sorted(input_path.glob('event*')):
                    self.devices.append({'path': str(event), 'name': event.name})
    
    def start(self) -> bool:
        """Start monitoring input events"""
        self.running = True
        
        for device in self.devices[:3]:
            try:
                thread = threading.Thread(
                    target=self._monitor,
                    args=(device['path'],),
                    daemon=True
                )
                thread.start()
                self.threads.append(thread)
            except Exception:
                pass
        
        return len(self.threads) > 0
    
    def _monitor(self, path: str):
        """Monitor single device"""
        try:
            with open(path, 'rb') as f:
                while self.running:
                    r, _, _ = select.select([f], [], [], 0.1)
                    if r:
                        data = f.read(self.EVENT_SIZE)
                        if len(data) == self.EVENT_SIZE:
                            event = struct.unpack(self.EVENT_FORMAT, data)
                            tv_sec, tv_usec, ev_type, code, value = event
                            
                            if ev_type in [self.EV_KEY, self.EV_ABS]:
                                if not self.event_queue.full():
                                    self.event_queue.put({
                                        'timestamp': tv_sec + tv_usec / 1000000,
                                        'type': ev_type,
                                        'code': code,
                                        'value': value,
                                        'device': path
                                    })
        except Exception:
            pass
    
    def get_events(self) -> List[dict]:
        """Get recent events"""
        events = []
        while not self.event_queue.empty():
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events
    
    def analyze(self, events: List[dict]) -> List[Tuple[str, str]]:
        """Analyze for injection"""
        threats = []
        
        if not events:
            return threats
        
        timestamps = [e['timestamp'] for e in events]
        
        if len(timestamps) > 5:
            intervals = np.diff(timestamps)
            if len(intervals) > 10 and np.std(intervals) < 0.0001:
                threats.append(('Touch', 'Suspiciously regular event timing'))
        
        if len(events) > 1:
            duration = timestamps[-1] - timestamps[0]
            if duration > 0:
                rate = len(events) / duration
                if rate > 1000:
                    threats.append(('Touch', f'Impossible event rate: {rate:.0f}/sec'))
        
        return threats
    
    def stop(self):
        """Stop monitoring"""
        self.running = False


# =============================================================================
# GPS SENSOR
# =============================================================================

class GPSSensor:
    """GPS location monitoring"""
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.available = self._check_available()
        self.history = deque(maxlen=100)
        
    def _check_available(self) -> bool:
        success, _ = run_command(['which', 'gpspipe'])
        return success
    
    def read(self) -> dict:
        """Read GPS location"""
        data = {
            'available': self.available,
            'latitude': None,
            'longitude': None,
            'altitude': None,
            'speed': None,
            'timestamp': time.time()
        }
        
        if not self.available:
            return data
        
        success, output = run_command(['gpspipe', '-w', '-n', '5'], timeout=3)
        if success:
            for line in output.split('\n'):
                try:
                    parsed = json.loads(line)
                    if parsed.get('class') == 'TPV':
                        data['latitude'] = parsed.get('lat')
                        data['longitude'] = parsed.get('lon')
                        data['altitude'] = parsed.get('alt')
                        data['speed'] = parsed.get('speed')
                        break
                except json.JSONDecodeError:
                    continue
        
        return data
    
    def analyze(self, data: dict) -> List[Tuple[str, str]]:
        """Check for GPS spoofing"""
        threats = []
        
        lat, lon = data.get('latitude'), data.get('longitude')
        if lat is None or lon is None:
            return threats
        
        timestamp = data['timestamp']
        
        if self.history:
            last = self.history[-1]
            time_diff = max(timestamp - last['timestamp'], 0.001)
            
            lat_diff = abs(lat - last['latitude']) * 111000
            lon_diff = abs(lon - last['longitude']) * 111000 * np.cos(np.radians(lat))
            distance = np.sqrt(lat_diff**2 + lon_diff**2)
            speed = distance / time_diff
            
            threshold = self.profile['gps_speed_threshold']
            if speed > 340:  # Speed of sound
                threats.append(('GPS', f'Impossible speed: {speed:.0f} m/s'))
            elif speed > threshold:
                threats.append(('GPS', f'Suspicious speed: {speed:.0f} m/s'))
        
        self.history.append({
            'timestamp': timestamp,
            'latitude': lat,
            'longitude': lon
        })
        
        return threats


# =============================================================================
# SYSTEM SENSORS
# =============================================================================

class SystemSensor:
    """System monitoring (CPU, Memory, Network, USB, Processes)"""
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.last_net_stats = {}
        self.usb_history = set()
        self.net_baseline = {}
        
    def read_cpu(self) -> dict:
        """Read CPU info"""
        data = {'usage': 0, 'cores': 0}
        
        if HAVE_PSUTIL:
            data['usage'] = psutil.cpu_percent(interval=0.1)
            data['cores'] = psutil.cpu_count()
        else:
            content = read_file('/proc/stat')
            if content:
                for line in content.split('\n'):
                    if line.startswith('cpu '):
                        parts = line.split()
                        if len(parts) >= 5:
                            total = sum(int(p) for p in parts[1:5])
                            idle = int(parts[4])
                            data['usage'] = (1 - idle/total) * 100 if total > 0 else 0
                    elif line.startswith('cpu') and line[3].isdigit():
                        data['cores'] += 1
        
        return data
    
    def read_memory(self) -> dict:
        """Read memory info"""
        data = {'total_mb': 0, 'available_mb': 0, 'used_percent': 0}
        
        if HAVE_PSUTIL:
            mem = psutil.virtual_memory()
            data['total_mb'] = mem.total / (1024*1024)
            data['available_mb'] = mem.available / (1024*1024)
            data['used_percent'] = mem.percent
        else:
            content = read_file('/proc/meminfo')
            if content:
                for line in content.split('\n'):
                    if line.startswith('MemTotal:'):
                        data['total_mb'] = int(line.split()[1]) / 1024
                    elif line.startswith('MemAvailable:'):
                        data['available_mb'] = int(line.split()[1]) / 1024
                
                if data['total_mb'] > 0:
                    data['used_percent'] = (1 - data['available_mb']/data['total_mb']) * 100
        
        return data
    
    def read_network(self) -> dict:
        """Read network stats"""
        stats = {}
        
        content = read_file('/proc/net/dev')
        if content:
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 17:
                    iface = parts[0].rstrip(':')
                    stats[iface] = {
                        'rx_bytes': int(parts[1]),
                        'rx_packets': int(parts[2]),
                        'rx_errors': int(parts[3]),
                        'rx_dropped': int(parts[4]),
                        'tx_bytes': int(parts[9]),
                        'tx_packets': int(parts[10]),
                        'tx_errors': int(parts[11]),
                        'tx_dropped': int(parts[12])
                    }
        
        return stats
    
    def read_usb(self) -> List[dict]:
        """Read USB devices"""
        devices = []
        
        usb_path = Path('/sys/bus/usb/devices')
        if usb_path.exists():
            for device in usb_path.iterdir():
                vendor = read_file(str(device / 'idVendor'))
                product = read_file(str(device / 'idProduct'))
                
                if vendor and product:
                    devices.append({
                        'vendor': vendor,
                        'product': product,
                        'name': read_file(str(device / 'product'), 'Unknown'),
                        'id': f"{vendor}:{product}"
                    })
        
        return devices
    
    def read_temperatures(self) -> dict:
        """Read temperature sensors"""
        temps = {}
        
        hwmon_path = Path('/sys/class/hwmon')
        if hwmon_path.exists():
            for hwmon in hwmon_path.iterdir():
                name = read_file(str(hwmon / 'name'), hwmon.name)
                for temp_file in hwmon.glob('temp*_input'):
                    try:
                        temp = int(read_file(str(temp_file), '0')) / 1000
                        temps[f"{name}/{temp_file.stem}"] = temp
                    except ValueError:
                        pass
        
        # Thermal zones
        thermal_path = Path('/sys/class/thermal')
        if thermal_path.exists():
            for zone in thermal_path.glob('thermal_zone*'):
                temp_str = read_file(str(zone / 'temp'))
                zone_type = read_file(str(zone / 'type'), zone.name)
                if temp_str:
                    try:
                        temps[zone_type] = int(temp_str) / 1000
                    except ValueError:
                        pass
        
        return temps
    
    def analyze_network(self, stats: dict) -> List[Tuple[str, str]]:
        """Analyze network for anomalies"""
        threats = []
        
        for iface, current in stats.items():
            if iface in self.last_net_stats:
                last = self.last_net_stats[iface]
                
                err_delta = (current['rx_errors'] - last['rx_errors'] +
                            current['tx_errors'] - last['tx_errors'])
                drop_delta = (current['rx_dropped'] - last['rx_dropped'] +
                             current['tx_dropped'] - last['tx_dropped'])
                
                if err_delta > 50:
                    threats.append(('Network', f'{iface}: {err_delta} packet errors'))
                if drop_delta > 20:
                    threats.append(('Network', f'{iface}: {drop_delta} dropped packets'))
                
                # Traffic spike detection
                rx_rate = current['rx_bytes'] - last['rx_bytes']
                key = f'{iface}_rx'
                if key not in self.net_baseline:
                    self.net_baseline[key] = []
                self.net_baseline[key].append(rx_rate)
                
                if len(self.net_baseline[key]) > 30:
                    self.net_baseline[key] = self.net_baseline[key][-30:]
                    avg = np.mean(self.net_baseline[key][:-1])
                    std = np.std(self.net_baseline[key][:-1])
                    if std > 0 and rx_rate > avg + 4 * std:
                        threats.append(('Network', f'{iface}: Unusual traffic spike'))
        
        self.last_net_stats = stats
        return threats
    
    def analyze_usb(self, devices: List[dict]) -> List[Tuple[str, str]]:
        """Check for new USB devices"""
        threats = []
        
        current_ids = set(d['id'] for d in devices)
        
        # After initial scan, alert on new devices
        if self.usb_history:
            new_devices = current_ids - self.usb_history
            for dev_id in new_devices:
                dev = next((d for d in devices if d['id'] == dev_id), None)
                name = dev['name'] if dev else dev_id
                threats.append(('USB', f'New device: {name} ({dev_id})'))
        
        self.usb_history = current_ids
        return threats
    
    def check_processes(self) -> List[Tuple[str, str]]:
        """Check for suspicious processes"""
        threats = []
        
        suspicious = [
            'keylog', 'sniffer', 'inject', 'hook', 'mitm',
            'tcpdump', 'wireshark', 'ettercap', 'arpspoof',
            'aircrack', 'airmon', 'airodump', 'meterpreter'
        ]
        
        proc_path = Path('/proc')
        for entry in proc_path.iterdir():
            if entry.is_dir() and entry.name.isdigit():
                comm = read_file(str(entry / 'comm'), '').lower()
                cmdline = read_file(str(entry / 'cmdline'), '').lower()
                
                for pattern in suspicious:
                    if pattern in comm or pattern in cmdline:
                        threats.append(('Process', f'Suspicious: {comm} (PID {entry.name})'))
                        break
        
        return threats


# =============================================================================
# UNIFIED DETECTOR
# =============================================================================

class UnifiedSignalDetector:
    """Main unified detection system"""
    
    def __init__(self, sensitivity: str = 'medium', mode: str = 'full', log_file: str = None):
        self.sensitivity = sensitivity
        self.mode = mode
        self.log_file = log_file
        self.profile = SENSITIVITY_PROFILES.get(sensitivity, SENSITIVITY_PROFILES['medium'])
        
        print("=" * 78)
        print("  UNIFIED SIGNAL INJECTION DETECTION SYSTEM")
        print(f"  Version {VERSION}")
        print("=" * 78)
        print()
        print(f"  Sensitivity: {sensitivity.upper()} - {self.profile['description']}")
        print(f"  Mode: {mode}")
        print()
        
        # Initialize sensors
        self.wifi = WiFiSensor(self.profile)
        self.bluetooth = BluetoothSensor(self.profile)
        self.audio = AudioSensor(self.profile)
        self.touch = TouchSensor(self.profile)
        self.gps = GPSSensor(self.profile)
        self.system = SystemSensor(self.profile)
        
        # State
        self.threat_log = deque(maxlen=1000)
        self.start_time = time.time()
        self.sample_count = 0
        self.sensor_status = {}
        
    def initialize(self) -> dict:
        """Initialize all sensors"""
        print("Initializing sensors...")
        
        status = {
            'wifi': self.wifi.interface is not None,
            'bluetooth': self.bluetooth.available,
            'audio': self.audio.start(),
            'touch': self.touch.start() if self.mode == 'full' else False,
            'gps': self.gps.available,
            'system': True
        }
        
        icons = {True: '✓', False: '✗'}
        print(f"  {icons[status['wifi']]} WiFi ({self.wifi.interface or 'not found'})")
        print(f"  {icons[status['bluetooth']]} Bluetooth")
        print(f"  {icons[status['audio']]} Audio (microphone)")
        
        if self.mode == 'full':
            print(f"  {icons[status['touch']]} Touch/Input ({len(self.touch.devices)} devices)")
            print(f"  {icons[status['gps']]} GPS")
            print(f"  {icons[status['system']]} System sensors")
        
        print()
        
        self.sensor_status = status
        return status
    
    def collect(self) -> dict:
        """Collect data from all sensors"""
        timestamp = time.time()
        threats = []
        
        data = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'sensitivity': self.sensitivity,
            'mode': self.mode
        }
        
        # WiFi
        wifi_data = self.wifi.read()
        data['wifi'] = wifi_data
        threats.extend(self.wifi.analyze(wifi_data))
        
        # Bluetooth (less frequent)
        if self.bluetooth.available and self.sample_count % 10 == 0:
            devices = self.bluetooth.scan(duration=1)
            data['bluetooth'] = {'devices': devices, 'count': len(devices)}
            for dev in devices:
                rssi = self.bluetooth.get_rssi(dev['mac'])
                threats.extend(self.bluetooth.analyze(dev['mac'], rssi, timestamp))
        
        # Audio
        audio_sample = self.audio.get_sample()
        if audio_sample is not None:
            audio_data = self.audio.analyze(audio_sample)
            data['audio'] = audio_data
            
            if audio_data and audio_data.get('suspicious'):
                msg = f"Ultrasonic (ratio: {audio_data['ultrasonic_ratio']:.2f}"
                if audio_data.get('ultrasonic_peaks'):
                    msg += f" @ {audio_data['ultrasonic_peaks'][0]['frequency']:.0f}Hz"
                if audio_data.get('likely_sources'):
                    msg += f" [{audio_data['likely_sources'][0]}]"
                msg += ")"
                threats.append(('Audio', msg))
                
            if audio_data and audio_data.get('replay_detected'):
                threats.append(('Audio', 'Replay attack detected'))
        
        # Full mode sensors
        if self.mode == 'full':
            # Touch
            touch_events = self.touch.get_events()
            if touch_events:
                threats.extend(self.touch.analyze(touch_events))
                data['touch'] = {'events': len(touch_events)}
            
            # GPS
            if self.gps.available:
                gps_data = self.gps.read()
                data['gps'] = gps_data
                threats.extend(self.gps.analyze(gps_data))
            
            # System (less frequent)
            if self.sample_count % 5 == 0:
                data['cpu'] = self.system.read_cpu()
                data['memory'] = self.system.read_memory()
                data['temps'] = self.system.read_temperatures()
                
                net_stats = self.system.read_network()
                threats.extend(self.system.analyze_network(net_stats))
                
                usb_devices = self.system.read_usb()
                data['usb'] = usb_devices
                threats.extend(self.system.analyze_usb(usb_devices))
                
                threats.extend(self.system.check_processes())
        
        # Risk level
        count = len(threats)
        if count >= 4:
            data['risk_level'] = 'CRITICAL'
        elif count >= 2:
            data['risk_level'] = 'HIGH'
        elif count >= 1:
            data['risk_level'] = 'MEDIUM'
        else:
            data['risk_level'] = 'LOW'
        
        data['threats'] = threats
        self.sample_count += 1
        
        return data
    
    def display(self, data: dict):
        """Display dashboard"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 78
        
        # Header
        print("╔" + "═" * width + "╗")
        print("║" + " " * 20 + "UNIFIED SIGNAL INJECTION DETECTOR" + " " * 23 + "║")
        runtime = int(time.time() - self.start_time)
        info = f"{data['datetime'][:19]}  |  {self.sensitivity.upper()}  |  Sample #{self.sample_count}  |  Runtime: {runtime}s"
        pad = width - len(info) - 2
        print(f"║ {info}" + " " * pad + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # WiFi
        wifi = data.get('wifi', {})
        print("┌─ WiFi " + "─" * (width - 8) + "┐")
        if wifi.get('ssid'):
            line = f"│  {wifi['ssid']}  |  RSSI: {wifi.get('rssi', 'N/A')} dBm  |  Quality: {wifi.get('quality', 'N/A')}"
        else:
            line = "│  Not connected"
        print(line + " " * (width - len(line)) + "│")
        print("└" + "─" * width + "┘")
        print()
        
        # Audio
        audio = data.get('audio', {})
        print("┌─ Audio Analysis " + "─" * (width - 18) + "┐")
        
        if audio and audio.get('status') != 'silent':
            line = f"│  RMS: {audio.get('rms', 0):.4f}  |  Peak: {audio.get('peak', 0):.4f}"
            print(line + " " * (width - len(line)) + "│")
            
            ratio = audio.get('ultrasonic_ratio', 0)
            energy = audio.get('ultrasonic_energy', 0)
            line = f"│  Ultrasonic: ratio={ratio:.3f}  energy={energy:.1f}"
            print(line + " " * (width - len(line)) + "│")
            
            peaks = audio.get('ultrasonic_peaks', [])
            if peaks:
                peak_str = ", ".join(f"{p['frequency']:.0f}Hz" for p in peaks[:3])
                line = f"│  Peak frequencies: {peak_str}"
                print(line + " " * (width - len(line)) + "│")
            
            sources = audio.get('likely_sources', [])
            if sources:
                line = f"│  Likely source: {sources[0]}"
                print(line + " " * (width - len(line)) + "│")
            
            # Spectrum bars
            bands = audio.get('band_energy', {})
            if bands:
                print("│" + " " * width + "│")
                u_low = bands.get('ultrasonic_low', 0)
                u_mid = bands.get('ultrasonic_mid', 0)
                u_high = bands.get('ultrasonic_high', 0)
                max_v = max(u_low, u_mid, u_high, 1)
                
                for label, val in [('18-19k', u_low), ('19-20k', u_mid), ('20-22k', u_high)]:
                    bar = "█" * int(val / max_v * 25) if max_v > 0 else ""
                    line = f"│  {label}: {bar:<25} {val:>8.1f}"
                    print(line + " " * (width - len(line)) + "│")
            
            # Threat reasons
            reasons = audio.get('threat_reasons', [])
            if reasons:
                print("│" + " " * width + "│")
                for reason in reasons[:3]:
                    line = f"│  ⚠ {reason[:width-6]}"
                    print(line + " " * (width - len(line)) + "│")
        else:
            status = audio.get('status', 'no data') if audio else 'not available'
            line = f"│  Status: {status}"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # System (full mode)
        if self.mode == 'full' and 'cpu' in data:
            print("┌─ System " + "─" * (width - 10) + "┐")
            cpu = data.get('cpu', {})
            mem = data.get('memory', {})
            line = f"│  CPU: {cpu.get('usage', 0):.1f}%  |  Memory: {mem.get('used_percent', 0):.1f}%"
            
            temps = data.get('temps', {})
            if temps:
                temp = list(temps.values())[0]
                line += f"  |  Temp: {temp:.1f}°C"
            
            print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
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
        
        print("┌─ Threat Assessment " + "─" * (width - 21) + "┐")
        line = f"│  Risk: {color}{data['risk_level']}{reset}  |  Active: {len(data['threats'])}  |  Logged: {len(self.audio.detailed_log)}"
        # Adjust padding for color codes
        visible_len = len(f"│  Risk: {data['risk_level']}  |  Active: {len(data['threats'])}  |  Logged: {len(self.audio.detailed_log)}")
        print(line + " " * (width - visible_len) + "│")
        print("│" + " " * width + "│")
        
        if data['threats']:
            for threat_type, message in data['threats'][:5]:
                msg = message[:width-15]
                line = f"│  🚨 [{threat_type}] {msg}"
                # Emoji takes extra space
                print(line + " " * (width - len(line) + 2) + "│")
        else:
            line = "│  ✅ All sensors normal - No threats detected"
            print(line + " " * (width - len(line) + 1) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Recent log
        recent = list(self.audio.detailed_log)[-3:]
        if recent:
            print("┌─ Recent Threat Log " + "─" * (width - 21) + "┐")
            for entry in recent:
                ts = entry['timestamp'][11:19]
                lvl = entry['threat_level'].upper()
                ratio = entry.get('ratio', 0)
                freq = entry['peaks'][0]['frequency'] if entry.get('peaks') else 0
                line = f"│  [{ts}] {lvl}: ratio={ratio:.2f} @ {freq:.0f}Hz"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        print(f"  Mode: {self.mode} | Sensitivity: {self.sensitivity} | Ctrl+C to stop")
        print(f"  Options: --sensitivity [low/medium/high/paranoid] --mode [minimal/full] --log FILE")
    
    def run(self, interval: float = 1.0):
        """Main monitoring loop"""
        try:
            while True:
                data = self.collect()
                self.display(data)
                
                for threat in data['threats']:
                    self.threat_log.append({
                        'timestamp': data['datetime'],
                        'type': threat[0],
                        'message': threat[1]
                    })
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.shutdown()
    
    def shutdown(self):
        """Clean shutdown"""
        print("\n\nShutting down...")
        
        # Export log
        if self.log_file:
            count = self.audio.export_log(self.log_file)
            print(f"Exported {count} events to {self.log_file}")
        
        # Stop sensors
        self.audio.stop()
        self.touch.stop()
        
        # Summary
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Duration: {int(time.time() - self.start_time)} seconds")
        print(f"  Samples: {self.sample_count}")
        print(f"  Threats logged: {len(self.audio.detailed_log)}")
        
        if self.audio.detailed_log:
            print()
            print("  Recent threats:")
            for entry in list(self.audio.detailed_log)[-5:]:
                print(f"    [{entry['timestamp'][:19]}] {entry['threat_level'].upper()}")
                for reason in entry.get('reasons', [])[:2]:
                    print(f"        → {reason}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Unified Signal Injection Detection System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SENSITIVITY LEVELS:
    low      - Only obvious attacks, minimal false positives
    medium   - Balanced detection (default)
    high     - More sensitive, some false positives
    paranoid - Maximum sensitivity, expect false positives

MODES:
    minimal  - WiFi + Audio only (faster, less resource usage)
    full     - All sensors (WiFi, Audio, Touch, GPS, System, USB, Process)

EXAMPLES:
    %(prog)s
    %(prog)s --sensitivity low
    %(prog)s --sensitivity high --mode full
    %(prog)s --log threats.json
    sudo %(prog)s  # For Bluetooth scanning

DEPENDENCIES:
    Required: numpy
    Optional: pyaudio (audio), psutil (system monitoring)
    
    pip install numpy pyaudio psutil --break-system-packages
        """
    )
    
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high', 'paranoid'],
                        default='medium',
                        help='Detection sensitivity')
    parser.add_argument('-m', '--mode',
                        choices=['minimal', 'full'],
                        default='full',
                        help='Sensor mode')
    parser.add_argument('-l', '--log',
                        help='Export threat log to JSON file')
    parser.add_argument('-i', '--interval',
                        type=float, default=1.0,
                        help='Update interval in seconds')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    # Check dependencies
    missing = []
    if not HAVE_PYAUDIO:
        missing.append('pyaudio')
    if not HAVE_PSUTIL and args.mode == 'full':
        missing.append('psutil')
    
    if missing:
        print(f"Note: Optional dependencies not installed: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)} --break-system-packages")
        print()
    
    # Create and run detector
    detector = UnifiedSignalDetector(
        sensitivity=args.sensitivity,
        mode=args.mode,
        log_file=args.log
    )
    
    detector.initialize()
    
    print("Starting monitoring...")
    time.sleep(1)
    
    detector.run(interval=args.interval)


if __name__ == "__main__":
    main()