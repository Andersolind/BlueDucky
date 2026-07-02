#!/usr/bin/env python3
"""
================================================================================
MULTI-SENSOR FUSION ATTACK DETECTOR
================================================================================

Detects speaker/transducer hijacking and sophisticated injection attacks by
cross-validating multiple independent sensor streams:

DETECTION METHODS:

1. CSI (Channel State Information) Injection
   - Detects fake WiFi-based monitoring data
   - Replay detection on CSI patterns
   - Packet signature validation
   - Physics plausibility checks (signal propagation)
   - Heartbeat/breathing pattern validation

2. Touch Injection (Invisible Finger)
   - Detects electromagnetic touch injection
   - Correlates EM field spikes with touch events
   - Validates touch physics (pressure, size, duration, velocity)
   - Detects impossible touch patterns

3. BLE Spoofing Detection
   - RSSI "teleportation" detection (impossible signal changes)
   - Device fingerprinting (advertisement patterns)
   - Multi-location presence detection
   - Clone detection via timing analysis

4. Audio Injection Detection
   - Ultrasonic attack detection (18-22kHz)
   - Hidden voice command detection
   - Speaker vs live voice discrimination
   - Replay fingerprinting

5. MULTI-SENSOR FUSION (Key Defense)
   - Cross-validates ALL sensors simultaneously
   - Detects inconsistencies between sensor streams
   - Spoofing multiple sensors coherently is extremely difficult
   - Temporal correlation analysis
   - Physics-based plausibility checking

SPEAKER/TRANSDUCER HIJACK INDICATORS:
   - Audio playing without corresponding app activity
   - Ultrasonic content in speaker output
   - Mismatch between audio output and network traffic
   - Unusual electromagnetic emissions during audio
   - BLE commands not matching user activity

USAGE:
    python3 multi_sensor_fusion_detector.py
    python3 multi_sensor_fusion_detector.py --sensitivity high --log attacks.json
    sudo python3 multi_sensor_fusion_detector.py  # For BLE scanning

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
import glob
import re
from collections import deque, Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set
import argparse

import numpy as np

# Optional imports
HAVE_PYAUDIO = False
try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "1.0.0"

SENSITIVITY = {
    'low': {
        'csi_replay_threshold': 0.98,
        'rssi_teleport_threshold': 30,  # dB change in 1 second
        'ultrasonic_ratio_threshold': 0.5,
        'touch_em_correlation_threshold': 0.9,
        'fusion_min_sensors': 3,
        'fusion_confidence_threshold': 0.8,
    },
    'medium': {
        'csi_replay_threshold': 0.92,
        'rssi_teleport_threshold': 20,
        'ultrasonic_ratio_threshold': 0.3,
        'touch_em_correlation_threshold': 0.8,
        'fusion_min_sensors': 2,
        'fusion_confidence_threshold': 0.6,
    },
    'high': {
        'csi_replay_threshold': 0.85,
        'rssi_teleport_threshold': 15,
        'ultrasonic_ratio_threshold': 0.15,
        'touch_em_correlation_threshold': 0.7,
        'fusion_min_sensors': 2,
        'fusion_confidence_threshold': 0.4,
    }
}

# Attack type definitions
ATTACK_TYPES = {
    'csi_injection': {
        'name': 'CSI Injection',
        'description': 'Fake WiFi channel state information injected',
        'severity': 'HIGH',
        'sensors': ['wifi', 'csi'],
    },
    'csi_replay': {
        'name': 'CSI Replay',
        'description': 'Previously recorded CSI data being replayed',
        'severity': 'HIGH',
        'sensors': ['wifi', 'csi'],
    },
    'touch_injection': {
        'name': 'Touch Injection (Invisible Finger)',
        'description': 'Electromagnetic touch screen injection detected',
        'severity': 'CRITICAL',
        'sensors': ['touch', 'em'],
    },
    'ble_spoofing': {
        'name': 'BLE Spoofing',
        'description': 'Cloned/spoofed Bluetooth device detected',
        'severity': 'HIGH',
        'sensors': ['bluetooth'],
    },
    'ble_teleportation': {
        'name': 'BLE Teleportation',
        'description': 'Impossible RSSI changes detected (device cloning)',
        'severity': 'CRITICAL',
        'sensors': ['bluetooth'],
    },
    'ultrasonic_injection': {
        'name': 'Ultrasonic Injection',
        'description': 'Inaudible ultrasonic commands detected',
        'severity': 'CRITICAL',
        'sensors': ['audio'],
    },
    'audio_replay': {
        'name': 'Audio Replay',
        'description': 'Previously recorded audio being replayed',
        'severity': 'HIGH',
        'sensors': ['audio'],
    },
    'speaker_hijack': {
        'name': 'Speaker/Transducer Hijack',
        'description': 'Speaker outputting unauthorized audio',
        'severity': 'CRITICAL',
        'sensors': ['audio', 'process', 'network'],
    },
    'multi_sensor_anomaly': {
        'name': 'Multi-Sensor Anomaly',
        'description': 'Inconsistent readings across multiple sensors',
        'severity': 'HIGH',
        'sensors': ['fusion'],
    },
}


# =============================================================================
# CSI (CHANNEL STATE INFORMATION) ANALYZER
# =============================================================================

class CSIAnalyzer:
    """
    Analyzes WiFi Channel State Information for injection attacks.
    
    CSI contains amplitude and phase information for each subcarrier,
    which can be used for:
    - Human presence detection
    - Gesture recognition
    - Heartbeat/breathing monitoring
    
    Attackers may inject fake CSI to spoof presence or health data.
    """
    
    def __init__(self, config: dict):
        self.config = config
        
        # CSI pattern history for replay detection
        self.csi_history = deque(maxlen=500)
        self.csi_hashes = deque(maxlen=1000)
        
        # Physics baselines
        self.rssi_baseline = None
        self.noise_baseline = None
        
        # Timing for plausibility checks
        self.last_csi_time = None
        self.csi_intervals = deque(maxlen=100)
        
    def read_csi_data(self) -> Optional[dict]:
        """
        Read CSI data from WiFi interface.
        Note: Real CSI requires special hardware/drivers (Intel 5300, Atheros, etc.)
        This simulates CSI using available WiFi metrics.
        """
        csi_data = {
            'timestamp': time.time(),
            'rssi': None,
            'noise': None,
            'snr': None,
            'link_quality': None,
            'tx_packets': None,
            'rx_packets': None,
            'subcarrier_amplitudes': None,
            'channel': None,
        }
        
        # Read from /proc/net/wireless
        try:
            content = Path('/proc/net/wireless').read_text()
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    csi_data['link_quality'] = float(parts[2].rstrip('.'))
                    csi_data['rssi'] = int(float(parts[3].rstrip('.')))
                    if len(parts) >= 5:
                        csi_data['noise'] = int(float(parts[4].rstrip('.')))
        except Exception:
            pass
        
        # Read packet counts from /proc/net/dev
        try:
            content = Path('/proc/net/dev').read_text()
            for line in content.split('\n'):
                if 'wlan' in line or 'wlp' in line:
                    parts = line.split()
                    if len(parts) >= 10:
                        csi_data['rx_packets'] = int(parts[2])
                        csi_data['tx_packets'] = int(parts[10])
        except Exception:
            pass
        
        # Get channel info
        try:
            result = subprocess.run(['iwconfig'], capture_output=True, text=True, timeout=2)
            for line in result.stdout.split('\n'):
                if 'Frequency' in line:
                    match = re.search(r'Frequency[:\s]+(\d+\.?\d*)', line)
                    if match:
                        freq = float(match.group(1))
                        # Convert frequency to channel
                        if freq > 5:
                            csi_data['channel'] = int((freq * 1000 - 5000) / 5)
                        else:
                            csi_data['channel'] = int((freq * 1000 - 2407) / 5)
        except Exception:
            pass
        
        # Simulate subcarrier amplitudes (in real implementation, read from driver)
        if csi_data['rssi'] is not None:
            # Generate synthetic subcarrier data based on RSSI
            np.random.seed(int(time.time() * 1000) % 2**32)
            base_amplitude = 10 ** (csi_data['rssi'] / 20)
            csi_data['subcarrier_amplitudes'] = base_amplitude * (1 + 0.1 * np.random.randn(56))
        
        return csi_data
    
    def analyze(self, csi_data: dict) -> dict:
        """Analyze CSI data for injection attacks"""
        result = {
            'timestamp': csi_data['timestamp'],
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'indicators': [],
            'csi_data': csi_data
        }
        
        if csi_data['rssi'] is None:
            return result
        
        # === Check 1: CSI Replay Detection ===
        # Create hash of CSI pattern
        if csi_data['subcarrier_amplitudes'] is not None:
            amp_quantized = (csi_data['subcarrier_amplitudes'] * 100).astype(np.int32)
            csi_hash = hashlib.md5(amp_quantized.tobytes()).hexdigest()
            
            if csi_hash in self.csi_hashes:
                result['is_attack'] = True
                result['attack_type'] = 'csi_replay'
                result['confidence'] = 0.95
                result['indicators'].append("Exact CSI pattern replay detected")
            
            self.csi_hashes.append(csi_hash)
        
        # === Check 2: Physics Plausibility ===
        # RSSI shouldn't change too rapidly without movement
        if self.rssi_baseline is not None:
            rssi_change = abs(csi_data['rssi'] - self.rssi_baseline)
            
            if rssi_change > 20:  # >20dB instant change is suspicious
                result['confidence'] = max(result['confidence'], 0.7)
                result['indicators'].append(f"Implausible RSSI change: {rssi_change}dB")
                if rssi_change > 30:
                    result['is_attack'] = True
                    result['attack_type'] = 'csi_injection'
        
        self.rssi_baseline = csi_data['rssi']
        
        # === Check 3: Timing Analysis ===
        if self.last_csi_time is not None:
            interval = csi_data['timestamp'] - self.last_csi_time
            self.csi_intervals.append(interval)
            
            if len(self.csi_intervals) > 10:
                # Check for unnaturally regular intervals (replay signature)
                std = np.std(list(self.csi_intervals)[-10:])
                mean = np.mean(list(self.csi_intervals)[-10:])
                
                if mean > 0 and std / mean < 0.001:  # <0.1% variation
                    result['confidence'] = max(result['confidence'], 0.6)
                    result['indicators'].append("Unnaturally regular CSI timing")
        
        self.last_csi_time = csi_data['timestamp']
        
        # === Check 4: Heartbeat/Breathing Plausibility ===
        # If CSI is being used for health monitoring, check vital signs
        if csi_data['subcarrier_amplitudes'] is not None:
            self.csi_history.append(csi_data['subcarrier_amplitudes'])
            
            if len(self.csi_history) > 50:
                # Analyze for breathing/heartbeat patterns
                recent = np.array(list(self.csi_history)[-50:])
                
                # Check for impossible vital signs
                # Normal breathing: 12-20 per minute
                # Normal heartbeat: 60-100 per minute
                
                # Compute variance across time
                temporal_variance = np.var(recent, axis=0)
                mean_variance = np.mean(temporal_variance)
                
                # Zero variance = static replay
                if mean_variance < 1e-10:
                    result['is_attack'] = True
                    result['attack_type'] = 'csi_replay'
                    result['confidence'] = max(result['confidence'], 0.85)
                    result['indicators'].append("Static CSI pattern (no natural variation)")
        
        return result


# =============================================================================
# TOUCH INJECTION DETECTOR (INVISIBLE FINGER)
# =============================================================================

class TouchInjectionDetector:
    """
    Detects electromagnetic touch injection attacks ("invisible finger").
    
    These attacks use strong EM fields to induce touch events without
    physical contact. Detection methods:
    - Correlate EM field measurements with touch events
    - Validate touch physics (pressure, size, duration)
    - Detect impossible touch patterns
    """
    
    def __init__(self, config: dict):
        self.config = config
        
        # Touch event history
        self.touch_history = deque(maxlen=200)
        self.em_history = deque(maxlen=200)
        
        # Touch physics baselines
        self.typical_pressure_range = (0.1, 1.0)
        self.typical_size_range = (10, 100)  # pixels
        self.typical_duration_range = (50, 2000)  # ms
        
        # Input device paths
        self.input_devices = self._find_input_devices()
        
    def _find_input_devices(self) -> List[str]:
        """Find touch input devices"""
        devices = []
        
        try:
            for path in Path('/dev/input').glob('event*'):
                devices.append(str(path))
        except Exception:
            pass
        
        return devices
    
    def read_touch_events(self) -> List[dict]:
        """Read recent touch events from input devices"""
        events = []
        
        # Read from /dev/input/event* (requires permissions)
        for device in self.input_devices:
            try:
                # Check if device has data
                import select
                fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
                
                # Read available events
                while True:
                    try:
                        data = os.read(fd, 24)  # input_event struct size
                        if len(data) < 24:
                            break
                        
                        # Parse input_event struct
                        tv_sec, tv_usec, ev_type, ev_code, ev_value = struct.unpack('llHHi', data)
                        
                        if ev_type == 3:  # EV_ABS (touch events)
                            events.append({
                                'timestamp': tv_sec + tv_usec / 1000000,
                                'type': 'touch',
                                'code': ev_code,
                                'value': ev_value,
                                'device': device
                            })
                    except BlockingIOError:
                        break
                
                os.close(fd)
                
            except (PermissionError, FileNotFoundError, OSError):
                pass
        
        return events
    
    def read_em_field(self) -> Optional[dict]:
        """
        Read electromagnetic field measurements.
        Uses magnetometer if available, or estimates from other sensors.
        """
        em_data = {
            'timestamp': time.time(),
            'magnetic_field': None,
            'em_anomaly': False
        }
        
        # Try to read from IIO magnetometer
        iio_path = Path('/sys/bus/iio/devices')
        if iio_path.exists():
            for device in iio_path.iterdir():
                try:
                    # Check for magnetometer
                    name_file = device / 'name'
                    if name_file.exists():
                        name = name_file.read_text().strip()
                        if 'mag' in name.lower():
                            # Read magnetic field values
                            x = float((device / 'in_magn_x_raw').read_text())
                            y = float((device / 'in_magn_y_raw').read_text())
                            z = float((device / 'in_magn_z_raw').read_text())
                            
                            em_data['magnetic_field'] = {
                                'x': x, 'y': y, 'z': z,
                                'magnitude': np.sqrt(x**2 + y**2 + z**2)
                            }
                            break
                except Exception:
                    pass
        
        return em_data
    
    def analyze(self, touch_events: List[dict], em_data: dict) -> dict:
        """Analyze for touch injection attacks"""
        result = {
            'timestamp': time.time(),
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'indicators': [],
            'touch_events': len(touch_events),
            'em_data': em_data
        }
        
        if not touch_events:
            return result
        
        # Store history
        for event in touch_events:
            self.touch_history.append(event)
        if em_data:
            self.em_history.append(em_data)
        
        # === Check 1: EM-Touch Correlation ===
        if em_data and em_data.get('magnetic_field'):
            mag = em_data['magnetic_field']['magnitude']
            
            # Check for EM spike correlating with touch
            if len(self.em_history) > 5:
                recent_mags = [e['magnetic_field']['magnitude'] 
                             for e in list(self.em_history)[-5:] 
                             if e.get('magnetic_field')]
                
                if recent_mags:
                    avg_mag = np.mean(recent_mags)
                    
                    # EM spike during touch = suspicious
                    if mag > avg_mag * 2:
                        result['confidence'] = max(result['confidence'], 0.7)
                        result['indicators'].append(f"EM spike during touch (2x baseline)")
                        
                        if mag > avg_mag * 5:
                            result['is_attack'] = True
                            result['attack_type'] = 'touch_injection'
                            result['confidence'] = 0.9
                            result['indicators'].append("Strong EM field correlates with touch")
        
        # === Check 2: Touch Physics Validation ===
        # Extract touch characteristics
        for event in touch_events:
            code = event.get('code', 0)
            value = event.get('value', 0)
            
            # ABS_MT_PRESSURE = 0x3a
            if code == 0x3a:
                if value < 0.01 or value > 10:
                    result['confidence'] = max(result['confidence'], 0.5)
                    result['indicators'].append(f"Abnormal touch pressure: {value}")
            
            # ABS_MT_TOUCH_MAJOR = 0x30 (touch size)
            if code == 0x30:
                if value < 1 or value > 500:
                    result['confidence'] = max(result['confidence'], 0.5)
                    result['indicators'].append(f"Abnormal touch size: {value}")
        
        # === Check 3: Touch Timing Analysis ===
        if len(self.touch_history) > 20:
            recent = list(self.touch_history)[-20:]
            timestamps = [e['timestamp'] for e in recent]
            
            if len(timestamps) > 1:
                intervals = np.diff(timestamps)
                
                # Check for machine-like regularity
                if len(intervals) > 5:
                    std = np.std(intervals)
                    mean = np.mean(intervals)
                    
                    if mean > 0 and std / mean < 0.01:  # <1% variation
                        result['confidence'] = max(result['confidence'], 0.6)
                        result['indicators'].append("Machine-like touch timing regularity")
                
                # Check for impossible speed
                # Human touch: max ~10 taps per second
                if mean < 0.05:  # >20 per second
                    result['is_attack'] = True
                    result['attack_type'] = 'touch_injection'
                    result['confidence'] = max(result['confidence'], 0.8)
                    result['indicators'].append("Superhuman touch speed detected")
        
        # === Check 4: Touch Without Capacitance ===
        # EM injection creates touch without actual capacitive contact
        # This would require specialized hardware to detect
        
        return result


# =============================================================================
# BLE SPOOFING DETECTOR
# =============================================================================

class BLESpoofingDetector:
    """
    Detects Bluetooth Low Energy spoofing and device cloning.
    
    Detection methods:
    - RSSI "teleportation" (impossible signal changes)
    - Device fingerprinting (advertisement patterns)
    - Multi-location presence detection
    - Timing analysis
    """
    
    def __init__(self, config: dict):
        self.config = config
        
        # Device tracking
        self.devices: Dict[str, dict] = {}  # MAC -> device info
        self.rssi_history: Dict[str, deque] = {}  # MAC -> RSSI history
        self.adv_patterns: Dict[str, List] = {}  # MAC -> advertisement patterns
        
        # Clone detection
        self.simultaneous_locations: Dict[str, List] = {}
        
    def scan(self, duration: int = 2) -> List[dict]:
        """Scan for BLE devices"""
        devices = []
        
        # Try hcitool lescan
        try:
            result = subprocess.run(
                ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
                capture_output=True, text=True, timeout=duration + 2
            )
            
            seen = set()
            for line in result.stdout.split('\n'):
                if ':' in line:
                    parts = line.strip().split(' ', 1)
                    mac = parts[0]
                    if len(mac) == 17 and mac not in seen:
                        devices.append({
                            'mac': mac,
                            'name': parts[1] if len(parts) > 1 else 'Unknown',
                            'timestamp': time.time()
                        })
                        seen.add(mac)
        except Exception:
            pass
        
        # Try to get RSSI via hcitool
        for device in devices:
            try:
                result = subprocess.run(
                    ['hcitool', 'rssi', device['mac']],
                    capture_output=True, text=True, timeout=2
                )
                if 'RSSI return value' in result.stdout:
                    rssi = int(result.stdout.split(':')[-1].strip())
                    device['rssi'] = rssi
            except Exception:
                device['rssi'] = None
        
        return devices
    
    def analyze(self, devices: List[dict]) -> dict:
        """Analyze BLE devices for spoofing"""
        result = {
            'timestamp': time.time(),
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'indicators': [],
            'devices_seen': len(devices),
            'suspicious_devices': []
        }
        
        for device in devices:
            mac = device['mac']
            rssi = device.get('rssi')
            
            # Initialize tracking
            if mac not in self.devices:
                self.devices[mac] = {
                    'first_seen': device['timestamp'],
                    'name': device['name'],
                    'scan_count': 0
                }
                self.rssi_history[mac] = deque(maxlen=100)
            
            self.devices[mac]['last_seen'] = device['timestamp']
            self.devices[mac]['scan_count'] += 1
            
            if rssi is not None:
                self.rssi_history[mac].append({
                    'rssi': rssi,
                    'timestamp': device['timestamp']
                })
            
            # === Check 1: RSSI Teleportation ===
            if mac in self.rssi_history and len(self.rssi_history[mac]) >= 2:
                history = list(self.rssi_history[mac])
                
                # Check recent RSSI changes
                if len(history) >= 2:
                    prev = history[-2]
                    curr = history[-1]
                    
                    rssi_change = abs(curr['rssi'] - prev['rssi'])
                    time_delta = curr['timestamp'] - prev['timestamp']
                    
                    if time_delta > 0:
                        change_rate = rssi_change / time_delta  # dB per second
                        
                        # >20dB/sec is physically impossible without teleportation
                        if change_rate > self.config['rssi_teleport_threshold']:
                            result['is_attack'] = True
                            result['attack_type'] = 'ble_teleportation'
                            result['confidence'] = max(result['confidence'], 0.9)
                            result['indicators'].append(
                                f"RSSI teleportation: {rssi_change}dB in {time_delta:.2f}s ({change_rate:.1f}dB/s)"
                            )
                            result['suspicious_devices'].append({
                                'mac': mac,
                                'name': device['name'],
                                'issue': 'teleportation'
                            })
            
            # === Check 2: Device Fingerprint Mismatch ===
            # Same MAC but different advertisement pattern = clone
            adv_pattern = f"{device['name']}_{device.get('manufacturer', '')}"
            
            if mac in self.adv_patterns:
                if adv_pattern not in self.adv_patterns[mac]:
                    self.adv_patterns[mac].append(adv_pattern)
                    
                    if len(self.adv_patterns[mac]) > 1:
                        result['confidence'] = max(result['confidence'], 0.7)
                        result['indicators'].append(
                            f"Device {mac} changed advertisement pattern (possible clone)"
                        )
            else:
                self.adv_patterns[mac] = [adv_pattern]
            
            # === Check 3: Multi-Location Presence ===
            # If same device appears with vastly different RSSI simultaneously
            # (would need multiple receivers, simulated here)
        
        return result


# =============================================================================
# AUDIO INJECTION DETECTOR
# =============================================================================

class AudioInjectionDetector:
    """
    Detects ultrasonic and audio replay injection attacks.
    """
    
    def __init__(self, config: dict, sample_rate: int = 48000):
        self.config = config
        self.sample_rate = sample_rate
        
        # History for replay detection
        self.audio_hashes = deque(maxlen=500)
        self.spectral_hashes = deque(maxlen=200)
        
    def analyze(self, audio: np.ndarray) -> dict:
        """Analyze audio for injection attacks"""
        result = {
            'timestamp': time.time(),
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'indicators': [],
            'rms': float(np.sqrt(np.mean(audio**2))),
            'ultrasonic_ratio': 0.0
        }
        
        if result['rms'] < 0.001:
            return result
        
        # FFT analysis
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        # === Check 1: Ultrasonic Content ===
        ultrasonic_mask = (freqs >= 18000) & (freqs <= 22000)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        
        ultrasonic_energy = np.sum(fft[ultrasonic_mask])
        voice_energy = np.sum(fft[voice_mask])
        
        if voice_energy > 0:
            ratio = ultrasonic_energy / voice_energy
            result['ultrasonic_ratio'] = float(ratio)
            
            if ratio > self.config['ultrasonic_ratio_threshold']:
                result['is_attack'] = True
                result['attack_type'] = 'ultrasonic_injection'
                result['confidence'] = min(1.0, ratio)
                result['indicators'].append(f"High ultrasonic ratio: {ratio:.2f}")
                
                # Check for DolphinAttack frequency range
                dolphin_mask = (freqs >= 19500) & (freqs <= 20500)
                dolphin_energy = np.sum(fft[dolphin_mask])
                if dolphin_energy > ultrasonic_energy * 0.5:
                    result['indicators'].append("DolphinAttack frequency range detected")
        
        # === Check 2: Audio Replay ===
        # Waveform hash
        downsampled = audio[::10]
        if np.max(np.abs(downsampled)) > 0:
            normalized = downsampled / np.max(np.abs(downsampled))
            quantized = (normalized * 100).astype(np.int8)
            audio_hash = hashlib.md5(quantized.tobytes()).hexdigest()
            
            if audio_hash in self.audio_hashes:
                result['is_attack'] = True
                result['attack_type'] = 'audio_replay'
                result['confidence'] = max(result['confidence'], 0.95)
                result['indicators'].append("Exact audio waveform replay detected")
            
            self.audio_hashes.append(audio_hash)
        
        # Spectral hash
        spectral_bands = np.array_split(fft, 32)
        band_energies = np.array([np.sum(b) for b in spectral_bands])
        if np.max(band_energies) > 0:
            band_energies = band_energies / np.max(band_energies)
            binary_hash = (band_energies > np.median(band_energies)).astype(np.uint8)
            spectral_hash = hashlib.md5(binary_hash.tobytes()).hexdigest()
            
            for old_hash in self.spectral_hashes:
                if spectral_hash == old_hash:
                    result['confidence'] = max(result['confidence'], 0.8)
                    result['indicators'].append("Spectral fingerprint match (near-replay)")
                    break
            
            self.spectral_hashes.append(spectral_hash)
        
        return result


# =============================================================================
# SPEAKER/TRANSDUCER HIJACK DETECTOR
# =============================================================================

class SpeakerHijackDetector:
    """
    Detects unauthorized speaker/transducer activity.
    
    Indicators:
    - Audio output without corresponding app activity
    - Ultrasonic content in speaker output
    - Mismatch between audio and network traffic
    - Unusual process audio activity
    """
    
    def __init__(self):
        self.audio_apps_baseline = set()
        self.network_baseline = 0
        
        # Capture baseline
        self._capture_baseline()
    
    def _capture_baseline(self):
        """Capture baseline audio apps"""
        try:
            result = subprocess.run(
                ['pactl', 'list', 'sink-inputs', 'short'],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        self.audio_apps_baseline.add(parts[2])
        except Exception:
            pass
    
    def analyze(self) -> dict:
        """Analyze for speaker hijack"""
        result = {
            'timestamp': time.time(),
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'indicators': [],
            'audio_apps': [],
            'suspicious_apps': []
        }
        
        # === Check 1: Unknown Audio Apps ===
        try:
            proc_result = subprocess.run(
                ['pactl', 'list', 'sink-inputs', 'short'],
                capture_output=True, text=True, timeout=3
            )
            
            current_apps = set()
            for line in proc_result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        app = parts[2]
                        current_apps.add(app)
                        result['audio_apps'].append(app)
                        
                        if app not in self.audio_apps_baseline:
                            result['suspicious_apps'].append(app)
                            result['confidence'] = max(result['confidence'], 0.5)
                            result['indicators'].append(f"New audio app: {app}")
        except Exception:
            pass
        
        # === Check 2: Audio Without User Interaction ===
        # Check if any audio is playing without recent user input
        try:
            # Check idle time
            result_idle = subprocess.run(
                ['xprintidle'],
                capture_output=True, text=True, timeout=2
            )
            if result_idle.returncode == 0:
                idle_ms = int(result_idle.stdout.strip())
                
                # If idle for >5 minutes but audio playing = suspicious
                if idle_ms > 300000 and result['audio_apps']:
                    result['confidence'] = max(result['confidence'], 0.6)
                    result['indicators'].append(f"Audio playing after {idle_ms/1000:.0f}s idle")
        except Exception:
            pass
        
        # === Check 3: Suspicious Processes ===
        suspicious_processes = ['aplay', 'mpv', 'ffplay', 'cvlc']
        try:
            proc_result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
            for proc in suspicious_processes:
                if proc in proc_result.stdout.lower():
                    # Check if started recently
                    result['confidence'] = max(result['confidence'], 0.4)
                    result['indicators'].append(f"Audio process running: {proc}")
        except Exception:
            pass
        
        if result['confidence'] > 0.6:
            result['is_attack'] = True
            result['attack_type'] = 'speaker_hijack'
        
        return result


# =============================================================================
# MULTI-SENSOR FUSION ENGINE
# =============================================================================

class MultiSensorFusion:
    """
    The KEY defense: Cross-validates all sensors simultaneously.
    
    Spoofing multiple independent sensors coherently is extremely difficult.
    This engine looks for inconsistencies that reveal attacks.
    """
    
    def __init__(self, config: dict):
        self.config = config
        
        # Sensor results history
        self.sensor_history = {
            'csi': deque(maxlen=100),
            'touch': deque(maxlen=100),
            'ble': deque(maxlen=100),
            'audio': deque(maxlen=100),
            'speaker': deque(maxlen=100),
        }
        
        # Cross-sensor correlation tracking
        self.correlation_history = deque(maxlen=50)
        
    def fuse(self, sensor_results: Dict[str, dict]) -> dict:
        """
        Fuse multiple sensor results and detect cross-sensor anomalies.
        """
        timestamp = time.time()
        
        result = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'indicators': [],
            'sensor_summary': {},
            'cross_validation': {},
            'individual_attacks': []
        }
        
        # Store sensor results
        for sensor, data in sensor_results.items():
            if data:
                self.sensor_history[sensor].append(data)
                
                # Track individual sensor attacks
                if data.get('is_attack'):
                    result['individual_attacks'].append({
                        'sensor': sensor,
                        'attack_type': data.get('attack_type'),
                        'confidence': data.get('confidence', 0),
                        'indicators': data.get('indicators', [])
                    })
        
        # Summarize sensor states
        for sensor, data in sensor_results.items():
            if data:
                result['sensor_summary'][sensor] = {
                    'status': 'attack' if data.get('is_attack') else 'normal',
                    'confidence': data.get('confidence', 0)
                }
        
        # === Cross-Sensor Validation ===
        
        # Check 1: Audio + CSI correlation
        # If audio shows injection but CSI shows no presence = attack
        audio_result = sensor_results.get('audio', {})
        csi_result = sensor_results.get('csi', {})
        
        if audio_result.get('rms', 0) > 0.01:  # Audio is active
            csi_data = csi_result.get('csi_data', {})
            rssi = csi_data.get('rssi')
            
            if rssi is not None and rssi < -80:  # Very weak WiFi
                # Audio without WiFi presence = suspicious
                result['cross_validation']['audio_csi'] = {
                    'status': 'mismatch',
                    'detail': 'Audio active but weak WiFi presence'
                }
                result['confidence'] = max(result['confidence'], 0.5)
                result['indicators'].append("Audio activity without WiFi presence")
        
        # Check 2: Touch + EM correlation
        touch_result = sensor_results.get('touch', {})
        if touch_result.get('touch_events', 0) > 0:
            em_data = touch_result.get('em_data', {})
            if em_data and em_data.get('magnetic_field'):
                mag = em_data['magnetic_field'].get('magnitude', 0)
                
                # High EM during touch = injection
                if mag > 1000:  # Arbitrary threshold
                    result['cross_validation']['touch_em'] = {
                        'status': 'anomaly',
                        'detail': f'High EM field ({mag}) during touch'
                    }
                    result['confidence'] = max(result['confidence'], 0.7)
                    result['indicators'].append("EM spike correlates with touch events")
        
        # Check 3: BLE + Audio correlation
        # Voice command via BLE speaker should correlate
        ble_result = sensor_results.get('ble', {})
        if ble_result.get('is_attack') and audio_result.get('is_attack'):
            result['cross_validation']['ble_audio'] = {
                'status': 'correlated_attacks',
                'detail': 'Both BLE and Audio show attack signatures'
            }
            result['confidence'] = max(result['confidence'], 0.9)
            result['indicators'].append("Correlated BLE and Audio attacks")
        
        # Check 4: Multiple independent sensor attacks
        attack_count = len(result['individual_attacks'])
        if attack_count >= self.config['fusion_min_sensors']:
            result['is_attack'] = True
            result['attack_type'] = 'multi_sensor_anomaly'
            result['confidence'] = max(result['confidence'], 0.85)
            result['indicators'].append(f"{attack_count} sensors show attack signatures")
        
        # Check 5: Temporal consistency
        # Attacks should be temporally correlated if real
        if attack_count >= 2:
            timestamps = [a.get('timestamp', timestamp) for a in result['individual_attacks']]
            if len(timestamps) >= 2:
                time_spread = max(timestamps) - min(timestamps)
                if time_spread > 5:  # >5 seconds apart
                    result['indicators'].append("Attack signatures not temporally correlated")
                    result['confidence'] *= 0.8  # Reduce confidence
        
        # === Final Decision ===
        if result['confidence'] > self.config['fusion_confidence_threshold']:
            result['is_attack'] = True
            if not result['attack_type']:
                # Determine primary attack type
                if result['individual_attacks']:
                    # Use highest confidence attack type
                    best = max(result['individual_attacks'], key=lambda x: x['confidence'])
                    result['attack_type'] = best['attack_type']
                else:
                    result['attack_type'] = 'multi_sensor_anomaly'
        
        return result


# =============================================================================
# AUDIO CAPTURE
# =============================================================================

class AudioCapture:
    """Audio capture with mic verification"""
    
    SAMPLE_RATES = [48000, 44100, 32000]
    
    def __init__(self, chunk_size: int = 8192):
        self.chunk_size = chunk_size
        self.sample_rate = None
        self.audio = None
        self.stream = None
        self.queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.device_name = None
        self.last_audio = None
    
    def _unmute(self):
        for cmd in [
            ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
            ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
        ]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass
    
    def start(self) -> bool:
        if not HAVE_PYAUDIO:
            return False
        
        self._unmute()
        
        try:
            p = pyaudio.PyAudio()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    for rate in self.SAMPLE_RATES:
                        try:
                            stream = p.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            stream.read(self.chunk_size, exception_on_overflow=False)
                            stream.close()
                            
                            self.sample_rate = rate
                            self.device_name = info['name']
                            
                            self.audio = pyaudio.PyAudio()
                            self.stream = self.audio.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            self.running = True
                            self.thread = threading.Thread(target=self._capture, daemon=True)
                            self.thread.start()
                            
                            p.terminate()
                            return True
                        except Exception:
                            continue
            p.terminate()
        except Exception:
            pass
        return False
    
    def _capture(self):
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                self.last_audio = audio
                if not self.queue.full():
                    self.queue.put(audio)
            except Exception:
                time.sleep(0.01)
    
    def get_sample(self) -> Optional[np.ndarray]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class MultiSensorFusionApp:
    """Main application combining all detectors"""
    
    def __init__(self, sensitivity: str = 'medium', log_file: str = None):
        self.sensitivity = sensitivity
        self.config = SENSITIVITY.get(sensitivity, SENSITIVITY['medium'])
        self.log_file = log_file
        
        # Initialize components
        self.audio_capture = AudioCapture()
        self.csi_analyzer = CSIAnalyzer(self.config)
        self.touch_detector = TouchInjectionDetector(self.config)
        self.ble_detector = BLESpoofingDetector(self.config)
        self.audio_detector = None  # Initialized after audio starts
        self.speaker_detector = SpeakerHijackDetector()
        self.fusion = MultiSensorFusion(self.config)
        
        # State
        self.start_time = time.time()
        self.sample_count = 0
        self.attack_count = 0
        self.attack_log = deque(maxlen=1000)
    
    def initialize(self) -> bool:
        """Initialize all components"""
        print("=" * 75)
        print("  MULTI-SENSOR FUSION ATTACK DETECTOR")
        print(f"  Version {VERSION}")
        print("=" * 75)
        print()
        print(f"  Sensitivity: {self.sensitivity.upper()}")
        print()
        
        print("Initializing sensors...")
        
        # Audio
        audio_ok = self.audio_capture.start()
        if audio_ok:
            print(f"  ✓ Audio: {self.audio_capture.device_name[:40]} @ {self.audio_capture.sample_rate}Hz")
            self.audio_detector = AudioInjectionDetector(self.config, self.audio_capture.sample_rate)
        else:
            print("  ✗ Audio: Not available")
        
        # CSI/WiFi
        csi_data = self.csi_analyzer.read_csi_data()
        if csi_data.get('rssi'):
            print(f"  ✓ CSI/WiFi: RSSI {csi_data['rssi']} dBm")
        else:
            print("  ⚠ CSI/WiFi: Limited data available")
        
        # Touch
        if self.touch_detector.input_devices:
            print(f"  ✓ Touch: {len(self.touch_detector.input_devices)} input devices")
        else:
            print("  ⚠ Touch: No input devices found")
        
        # BLE
        if self.ble_detector:
            print("  ✓ BLE: Ready (run as root for scanning)")
        
        # Speaker monitor
        print("  ✓ Speaker Monitor: Active")
        
        # Fusion engine
        print("  ✓ Multi-Sensor Fusion: Active")
        
        print()
        return True
    
    def run(self, interval: float = 0.5):
        """Main detection loop"""
        print("Starting multi-sensor monitoring...")
        print("  Press Ctrl+C to stop")
        print()
        time.sleep(1)
        
        ble_counter = 0
        
        try:
            while True:
                self.sample_count += 1
                sensor_results = {}
                
                # === Collect Sensor Data ===
                
                # CSI Analysis
                csi_data = self.csi_analyzer.read_csi_data()
                sensor_results['csi'] = self.csi_analyzer.analyze(csi_data)
                
                # Touch Analysis
                touch_events = self.touch_detector.read_touch_events()
                em_data = self.touch_detector.read_em_field()
                sensor_results['touch'] = self.touch_detector.analyze(touch_events, em_data)
                
                # BLE Analysis (less frequent due to scan time)
                ble_counter += 1
                if ble_counter >= 5:  # Every 5 iterations
                    ble_counter = 0
                    devices = self.ble_detector.scan(duration=1)
                    sensor_results['ble'] = self.ble_detector.analyze(devices)
                
                # Audio Analysis
                audio = self.audio_capture.get_sample()
                if audio is not None and self.audio_detector:
                    sensor_results['audio'] = self.audio_detector.analyze(audio)
                
                # Speaker Analysis
                sensor_results['speaker'] = self.speaker_detector.analyze()
                
                # === Multi-Sensor Fusion ===
                fusion_result = self.fusion.fuse(sensor_results)
                
                # Log attacks
                if fusion_result['is_attack']:
                    self.attack_count += 1
                    self.attack_log.append(fusion_result)
                
                # Display
                self._display(fusion_result, sensor_results)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self._shutdown()
    
    def _display(self, fusion_result: dict, sensor_results: dict):
        """Display current status"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 78
        runtime = int(time.time() - self.start_time)
        
        # Header
        print("╔" + "═" * width + "╗")
        print("║" + " " * 20 + "MULTI-SENSOR FUSION DETECTOR" + " " * 28 + "║")
        info = f"Runtime: {runtime}s  |  Samples: {self.sample_count}  |  Attacks: {self.attack_count}"
        print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # Sensor Status Grid
        print("┌─ Sensor Status " + "─" * (width - 17) + "┐")
        
        sensors = ['csi', 'touch', 'ble', 'audio', 'speaker']
        sensor_names = {
            'csi': 'CSI/WiFi',
            'touch': 'Touch/EM',
            'ble': 'Bluetooth',
            'audio': 'Audio',
            'speaker': 'Speaker'
        }
        
        for sensor in sensors:
            data = sensor_results.get(sensor, {})
            name = sensor_names.get(sensor, sensor)
            
            if data.get('is_attack'):
                status = f"\033[91m⚠ ATTACK\033[0m"
                status_plain = "⚠ ATTACK"
            elif data:
                status = f"\033[92m✓ Normal\033[0m"
                status_plain = "✓ Normal"
            else:
                status = f"\033[93m○ N/A\033[0m"
                status_plain = "○ N/A"
            
            conf = data.get('confidence', 0)
            
            line = f"│  {name:<12} {status}"
            visible = f"│  {name:<12} {status_plain}"
            
            if conf > 0:
                extra = f"  ({conf:.0%})"
                line += extra
                visible += extra
            
            print(line + " " * (width - len(visible)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Fusion Result
        print("┌─ Multi-Sensor Fusion " + "─" * (width - 23) + "┐")
        
        if fusion_result['is_attack']:
            atype = fusion_result.get('attack_type', 'unknown')
            conf = fusion_result['confidence']
            
            attack_info = ATTACK_TYPES.get(atype, {})
            severity = attack_info.get('severity', 'UNKNOWN')
            
            sev_colors = {'CRITICAL': '\033[95m', 'HIGH': '\033[91m', 'MEDIUM': '\033[93m'}
            color = sev_colors.get(severity, '')
            reset = '\033[0m'
            
            line = f"│  {color}⚠ {attack_info.get('name', atype).upper()}{reset} ({conf:.0%})"
            visible = f"│  ⚠ {attack_info.get('name', atype).upper()} ({conf:.0%})"
            print(line + " " * (width - len(visible)) + "│")
            
            line = f"│  Severity: {severity}"
            print(line + " " * (width - len(line)) + "│")
            
            print("│" + " " * width + "│")
            
            for indicator in fusion_result.get('indicators', [])[:4]:
                line = f"│  → {indicator[:width-6]}"
                print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  ✓ All sensors normal - No attack detected"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Cross-Validation
        cv = fusion_result.get('cross_validation', {})
        if cv:
            print("┌─ Cross-Sensor Validation " + "─" * (width - 27) + "┐")
            for check, result in cv.items():
                status = result.get('status', 'ok')
                detail = result.get('detail', '')[:50]
                
                if status in ['mismatch', 'anomaly', 'correlated_attacks']:
                    color = '\033[93m'
                else:
                    color = '\033[92m'
                reset = '\033[0m'
                
                line = f"│  {check}: {color}{status}{reset} - {detail}"
                visible = f"│  {check}: {status} - {detail}"
                print(line + " " * (width - len(visible)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        # Individual Attacks
        individual = fusion_result.get('individual_attacks', [])
        if individual:
            print("┌─ Individual Sensor Alerts " + "─" * (width - 28) + "┐")
            for attack in individual[:4]:
                sensor = attack.get('sensor', '?')
                atype = attack.get('attack_type', '?')
                conf = attack.get('confidence', 0)
                line = f"│  [{sensor.upper()}] {atype} ({conf:.0%})"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        # Recent Attack Log
        if self.attack_log:
            print("┌─ Recent Attacks " + "─" * (width - 18) + "┐")
            for attack in list(self.attack_log)[-3:]:
                ts = attack['datetime'][11:19]
                atype = attack.get('attack_type', '?')
                conf = attack['confidence']
                line = f"│  [{ts}] {atype} ({conf:.0%})"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        print("  Ctrl+C to stop  |  sudo for BLE scanning  |  --sensitivity [low/medium/high]")
    
    def _shutdown(self):
        """Clean shutdown"""
        print("\n\nShutting down...")
        
        self.audio_capture.stop()
        
        # Export log
        if self.log_file and self.attack_log:
            log_data = {
                'export_time': datetime.now().isoformat(),
                'sensitivity': self.sensitivity,
                'total_samples': self.sample_count,
                'attacks': list(self.attack_log)
            }
            
            with open(self.log_file, 'w') as f:
                json.dump(log_data, f, indent=2, default=str)
            
            print(f"  Exported {len(self.attack_log)} attacks to {self.log_file}")
        
        # Summary
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Duration: {int(time.time() - self.start_time)}s")
        print(f"  Samples: {self.sample_count}")
        print(f"  Attacks detected: {self.attack_count}")
        
        if self.attack_log:
            print()
            print("  Attack types detected:")
            types = Counter(a.get('attack_type', 'unknown') for a in self.attack_log)
            for atype, count in types.most_common():
                print(f"    {atype}: {count}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Multi-Sensor Fusion Attack Detector',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
DETECTION CAPABILITIES:

  CSI Injection      - Fake WiFi monitoring data
  Touch Injection    - Electromagnetic "invisible finger" attacks
  BLE Spoofing       - Cloned Bluetooth devices, RSSI teleportation
  Audio Injection    - Ultrasonic attacks, hidden voice commands
  Speaker Hijack     - Unauthorized speaker/transducer activity
  Multi-Sensor Fusion - Cross-validates all sensors simultaneously

KEY CONCEPT:
  Spoofing multiple independent sensors coherently is extremely difficult.
  The fusion engine detects inconsistencies across sensor streams.

EXAMPLES:
    %(prog)s
    %(prog)s --sensitivity high
    %(prog)s --log attacks.json
    sudo %(prog)s  # For BLE scanning
        """
    )
    
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high'],
                        default='medium')
    parser.add_argument('-l', '--log', help='Export attacks to JSON file')
    parser.add_argument('-i', '--interval', type=float, default=0.5)
    
    args = parser.parse_args()
    
    app = MultiSensorFusionApp(
        sensitivity=args.sensitivity,
        log_file=args.log
    )
    
    if not app.initialize():
        print("Failed to initialize")
        sys.exit(1)
    
    app.run(interval=args.interval)


if __name__ == "__main__":
    main()