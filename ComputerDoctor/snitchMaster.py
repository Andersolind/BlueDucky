#!/usr/bin/env python3
"""
Real Signal Injection Detection System - Enhanced Edition

IMPROVEMENTS IN THIS VERSION:
- Detailed ultrasonic frequency analysis (shows exact frequencies detected)
- Adjustable sensitivity levels (low/medium/high/paranoid)
- Pattern detection (continuous vs intermittent ultrasonic)
- Frequency band breakdown (shows which specific ranges are active)
- Historical logging with detailed timestamps
- Export logs to JSON for analysis
- Identifies common ultrasonic sources

Requirements:
    pip install numpy pyaudio --break-system-packages

Run with:
    python3 real_signal_injection_detector_enhanced.py
    python3 real_signal_injection_detector_enhanced.py --sensitivity low
    python3 real_signal_injection_detector_enhanced.py --log-file threats.json
    python3 real_signal_injection_detector_enhanced.py --sensitivity paranoid --log-file detailed.json
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

import numpy as np

# Optional imports
try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    HAVE_PYAUDIO = False


# =============================================================================
# SENSITIVITY PROFILES
# =============================================================================

SENSITIVITY_PROFILES = {
    'low': {
        'ultrasonic_ratio_threshold': 0.8,  # Only alert on very high ratios
        'ultrasonic_absolute_threshold': 1000,  # Need significant absolute energy
        'rssi_change_threshold': 30,  # Large RSSI changes only
        'description': 'Minimal alerts, only obvious attacks'
    },
    'medium': {
        'ultrasonic_ratio_threshold': 0.4,
        'ultrasonic_absolute_threshold': 500,
        'rssi_change_threshold': 20,
        'description': 'Balanced detection (recommended)'
    },
    'high': {
        'ultrasonic_ratio_threshold': 0.2,
        'ultrasonic_absolute_threshold': 200,
        'rssi_change_threshold': 15,
        'description': 'Sensitive detection, may have false positives'
    },
    'paranoid': {
        'ultrasonic_ratio_threshold': 0.1,
        'ultrasonic_absolute_threshold': 100,
        'rssi_change_threshold': 10,
        'description': 'Maximum sensitivity, expect false positives'
    }
}


# =============================================================================
# ENHANCED AUDIO SENSOR WITH DETAILED ANALYSIS
# =============================================================================

class EnhancedAudioSensor:
    """Enhanced audio sensor with detailed ultrasonic analysis"""
    
    # Common ultrasonic sources and their typical frequencies
    KNOWN_SOURCES = {
        (15000, 17000): "CRT TV/Old monitor",
        (17000, 19000): "LCD backlight / LED driver",
        (19000, 20000): "Mosquito deterrent / Teen deterrent",
        (20000, 22000): "Ultrasonic pest repeller",
        (22000, 24000): "Industrial ultrasonic cleaner",
        (18000, 22000): "Potential DolphinAttack range",
    }
    
    def __init__(self, sample_rate=44100, chunk_size=8192, sensitivity='medium'):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.audio = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.available = HAVE_PYAUDIO
        
        # Sensitivity settings
        self.sensitivity = sensitivity
        self.profile = SENSITIVITY_PROFILES.get(sensitivity, SENSITIVITY_PROFILES['medium'])
        
        # History for pattern detection
        self.ultrasonic_history = deque(maxlen=60)  # Last 60 samples (~1 minute)
        self.frequency_history = deque(maxlen=30)
        self.audio_hashes = deque(maxlen=100)
        
        # Detailed logging
        self.detailed_log = deque(maxlen=1000)
        
    def start(self):
        """Start audio capture from microphone"""
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
                print("No audio input device found")
                return False
            
            print(f"  Using audio device: {device_name}")
            
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
        """Detailed audio analysis with frequency breakdown"""
        if audio_data is None or len(audio_data) == 0:
            return None
        
        timestamp = time.time()
        
        results = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'rms': float(np.sqrt(np.mean(audio_data**2))),
            'peak': float(np.max(np.abs(audio_data))),
            'sensitivity': self.sensitivity
        }
        
        # Skip analysis if audio is too quiet (noise floor)
        if results['rms'] < 0.001:
            results['status'] = 'silent'
            return results
        
        # FFT analysis
        fft = np.fft.rfft(audio_data)
        freqs = np.fft.rfftfreq(len(audio_data), 1/self.sample_rate)
        magnitude = np.abs(fft)
        
        # === DETAILED FREQUENCY BAND ANALYSIS ===
        
        # Define frequency bands
        bands = {
            'sub_bass': (20, 60),
            'bass': (60, 250),
            'low_mid': (250, 500),
            'mid': (500, 2000),
            'high_mid': (2000, 4000),
            'presence': (4000, 6000),
            'brilliance': (6000, 10000),
            'high': (10000, 15000),
            'very_high': (15000, 18000),
            'ultrasonic_low': (18000, 19000),
            'ultrasonic_mid': (19000, 20000),
            'ultrasonic_high': (20000, 22000),
        }
        
        band_energy = {}
        for band_name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs < high)
            band_energy[band_name] = float(np.sum(magnitude[mask]))
        
        results['band_energy'] = band_energy
        
        # === ULTRASONIC ANALYSIS ===
        
        # Total ultrasonic energy (18-22 kHz)
        ultrasonic_mask = (freqs >= 18000) & (freqs <= 22000)
        ultrasonic_energy = float(np.sum(magnitude[ultrasonic_mask]))
        
        # Voice frequency energy (300-3400 Hz)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        voice_energy = float(np.sum(magnitude[voice_mask]))
        
        # Total audible energy (20-18000 Hz)
        audible_mask = (freqs >= 20) & (freqs < 18000)
        audible_energy = float(np.sum(magnitude[audible_mask]))
        
        results['ultrasonic_energy'] = ultrasonic_energy
        results['voice_energy'] = voice_energy
        results['audible_energy'] = audible_energy
        
        # Calculate ratios
        results['ultrasonic_to_voice_ratio'] = (
            ultrasonic_energy / voice_energy if voice_energy > 0 else 0
        )
        results['ultrasonic_to_audible_ratio'] = (
            ultrasonic_energy / audible_energy if audible_energy > 0 else 0
        )
        
        # === FIND PEAK FREQUENCIES IN ULTRASONIC RANGE ===
        
        ultrasonic_freqs = freqs[ultrasonic_mask]
        ultrasonic_mags = magnitude[ultrasonic_mask]
        
        peak_frequencies = []
        if len(ultrasonic_mags) > 0 and np.max(ultrasonic_mags) > 10:
            # Find peaks (local maxima)
            for i in range(1, len(ultrasonic_mags) - 1):
                if (ultrasonic_mags[i] > ultrasonic_mags[i-1] and 
                    ultrasonic_mags[i] > ultrasonic_mags[i+1] and
                    ultrasonic_mags[i] > np.mean(ultrasonic_mags) * 2):
                    peak_frequencies.append({
                        'frequency': float(ultrasonic_freqs[i]),
                        'magnitude': float(ultrasonic_mags[i])
                    })
            
            # Sort by magnitude and keep top 5
            peak_frequencies.sort(key=lambda x: x['magnitude'], reverse=True)
            peak_frequencies = peak_frequencies[:5]
        
        results['ultrasonic_peaks'] = peak_frequencies
        
        # === IDENTIFY LIKELY SOURCE ===
        
        likely_sources = []
        if peak_frequencies:
            dominant_freq = peak_frequencies[0]['frequency']
            for (low, high), source in self.KNOWN_SOURCES.items():
                if low <= dominant_freq <= high:
                    likely_sources.append(source)
        
        results['likely_sources'] = likely_sources
        
        # === THREAT ASSESSMENT ===
        
        ratio_threshold = self.profile['ultrasonic_ratio_threshold']
        absolute_threshold = self.profile['ultrasonic_absolute_threshold']
        
        results['ultrasonic_suspicious'] = False
        results['threat_level'] = 'none'
        results['threat_reasons'] = []
        
        ratio = results['ultrasonic_to_voice_ratio']
        
        # Check against thresholds
        if ratio > ratio_threshold and ultrasonic_energy > absolute_threshold:
            results['ultrasonic_suspicious'] = True
            results['threat_reasons'].append(
                f"High ultrasonic ratio: {ratio:.2f} (threshold: {ratio_threshold})"
            )
            
            # Determine threat level based on severity
            if ratio > ratio_threshold * 3:
                results['threat_level'] = 'high'
            elif ratio > ratio_threshold * 1.5:
                results['threat_level'] = 'medium'
            else:
                results['threat_level'] = 'low'
        
        # Check for specific attack patterns
        if peak_frequencies:
            dominant_freq = peak_frequencies[0]['frequency']
            
            # DolphinAttack typically uses very specific frequencies
            if 19500 <= dominant_freq <= 20500:
                results['threat_reasons'].append(
                    f"Frequency {dominant_freq:.0f}Hz matches DolphinAttack range"
                )
                if results['threat_level'] == 'none':
                    results['threat_level'] = 'low'
                    results['ultrasonic_suspicious'] = True
        
        # === PATTERN ANALYSIS ===
        
        self.ultrasonic_history.append({
            'timestamp': timestamp,
            'energy': ultrasonic_energy,
            'ratio': ratio,
            'peaks': [p['frequency'] for p in peak_frequencies]
        })
        
        # Analyze patterns over time
        if len(self.ultrasonic_history) >= 10:
            recent = list(self.ultrasonic_history)[-10:]
            
            # Check for continuous ultrasonic presence
            high_energy_count = sum(1 for r in recent if r['energy'] > absolute_threshold)
            if high_energy_count >= 8:
                results['pattern'] = 'continuous'
                results['threat_reasons'].append(
                    f"Continuous ultrasonic presence ({high_energy_count}/10 samples)"
                )
            elif high_energy_count >= 4:
                results['pattern'] = 'intermittent'
            else:
                results['pattern'] = 'sporadic'
            
            # Check for consistent frequency (indicates deliberate signal)
            if peak_frequencies:
                recent_peaks = [r['peaks'] for r in recent if r['peaks']]
                if len(recent_peaks) >= 5:
                    all_peaks = [p for peaks in recent_peaks for p in peaks]
                    if all_peaks:
                        freq_std = np.std(all_peaks)
                        if freq_std < 500:  # Very consistent frequency
                            results['threat_reasons'].append(
                                f"Consistent frequency detected (std: {freq_std:.0f}Hz)"
                            )
                            if results['threat_level'] in ['none', 'low']:
                                results['threat_level'] = 'medium'
                                results['ultrasonic_suspicious'] = True
        
        # === REPLAY DETECTION ===
        
        audio_hash = hashlib.md5(audio_data.tobytes()).hexdigest()
        results['replay_detected'] = audio_hash in self.audio_hashes
        self.audio_hashes.append(audio_hash)
        
        if results['replay_detected']:
            results['threat_reasons'].append("Exact audio replay detected")
            results['threat_level'] = 'high'
        
        # === LOG DETAILED ENTRY ===
        
        if results['ultrasonic_suspicious'] or results['replay_detected']:
            self.detailed_log.append({
                'timestamp': results['datetime'],
                'threat_level': results['threat_level'],
                'ultrasonic_energy': ultrasonic_energy,
                'ratio': ratio,
                'peak_frequencies': peak_frequencies,
                'likely_sources': likely_sources,
                'reasons': results['threat_reasons'],
                'pattern': results.get('pattern', 'unknown')
            })
        
        return results
    
    def get_detailed_log(self):
        """Get detailed threat log"""
        return list(self.detailed_log)
    
    def export_log(self, filepath):
        """Export detailed log to JSON file"""
        log_data = {
            'export_time': datetime.now().isoformat(),
            'sensitivity': self.sensitivity,
            'profile': self.profile,
            'events': self.get_detailed_log()
        }
        
        with open(filepath, 'w') as f:
            json.dump(log_data, f, indent=2)
        
        return len(log_data['events'])
    
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
# OTHER SENSORS (Same as before, included for completeness)
# =============================================================================

class RealWiFiSensor:
    """Read real WiFi signal information"""
    
    def __init__(self, sensitivity='medium'):
        self.rssi_history = deque(maxlen=100)
        self.last_data = None
        self.interface = self._find_wifi_interface()
        self.profile = SENSITIVITY_PROFILES.get(sensitivity, SENSITIVITY_PROFILES['medium'])
        
    def _find_wifi_interface(self):
        try:
            wireless_path = Path('/proc/net/wireless')
            if wireless_path.exists():
                content = wireless_path.read_text()
                for line in content.split('\n')[2:]:
                    if line.strip():
                        return line.split()[0].rstrip(':')
        except Exception:
            pass
        
        try:
            net_path = Path('/sys/class/net')
            for iface in net_path.iterdir():
                if (iface / 'wireless').exists():
                    return iface.name
        except Exception:
            pass
            
        return None
    
    def read_data(self):
        data = {
            'interface': self.interface,
            'ssid': None,
            'rssi': None,
            'quality': None,
            'rx_packets': 0,
            'tx_packets': 0,
            'timestamp': time.time()
        }
        
        try:
            with open('/proc/net/wireless', 'r') as f:
                for line in f.readlines()[2:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        data['interface'] = parts[0].rstrip(':')
                        data['quality'] = float(parts[2].rstrip('.'))
                        data['rssi'] = int(float(parts[3].rstrip('.')))
        except Exception:
            pass
        
        if self.interface:
            try:
                result = subprocess.run(
                    ['iwconfig', self.interface],
                    capture_output=True, text=True, timeout=2
                )
                if 'ESSID:"' in result.stdout:
                    start = result.stdout.find('ESSID:"') + 7
                    end = result.stdout.find('"', start)
                    if start > 6 and end > start:
                        data['ssid'] = result.stdout[start:end]
            except Exception:
                pass
        
        try:
            with open('/proc/net/dev', 'r') as f:
                for line in f.readlines()[2:]:
                    parts = line.split()
                    if len(parts) >= 10:
                        iface = parts[0].rstrip(':')
                        if iface == self.interface:
                            data['rx_packets'] = int(parts[2])
                            data['tx_packets'] = int(parts[10])
        except Exception:
            pass
            
        return data
    
    def check_anomalies(self, data):
        threats = []
        
        if data['rssi'] is not None:
            self.rssi_history.append(data['rssi'])
            
            if len(self.rssi_history) > 10:
                rssi_std = np.std(list(self.rssi_history)[-10:])
                if rssi_std < 0.5:
                    threats.append(('WiFi', 'Suspiciously stable RSSI'))
            
            if self.last_data and self.last_data['rssi']:
                rssi_change = abs(data['rssi'] - self.last_data['rssi'])
                if rssi_change > self.profile['rssi_change_threshold']:
                    threats.append(('WiFi', f'Sudden RSSI change: {rssi_change} dB'))
        
        self.last_data = data
        return threats


class RealBluetoothSensor:
    """Read real Bluetooth device data"""
    
    def __init__(self, sensitivity='medium'):
        self.device_history = {}
        self.scan_available = self._check_bluetooth()
        self.profile = SENSITIVITY_PROFILES.get(sensitivity, SENSITIVITY_PROFILES['medium'])
        
    def _check_bluetooth(self):
        try:
            result = subprocess.run(['which', 'hcitool'], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def scan_devices(self, duration=1):
        devices = []
        if not self.scan_available:
            return devices
            
        try:
            result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=2)
            if 'UP RUNNING' not in result.stdout:
                return devices
        except Exception:
            return devices
        
        try:
            result = subprocess.run(
                ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
                capture_output=True, text=True, timeout=duration+2
            )
            
            seen = set()
            for line in result.stdout.split('\n'):
                if ':' in line:
                    parts = line.strip().split(' ', 1)
                    mac = parts[0]
                    if mac not in seen and len(mac) == 17:
                        devices.append({
                            'mac': mac,
                            'name': parts[1] if len(parts) > 1 else 'Unknown',
                            'timestamp': time.time()
                        })
                        seen.add(mac)
        except Exception:
            pass
            
        return devices
    
    def check_rssi_anomaly(self, mac, rssi, timestamp):
        if rssi is None:
            return False, None
            
        if mac not in self.device_history:
            self.device_history[mac] = [(timestamp, rssi)]
            return False, None
        
        history = self.device_history[mac]
        if history:
            last_ts, last_rssi = history[-1]
            time_diff = max(timestamp - last_ts, 0.001)
            rssi_diff = abs(rssi - last_rssi)
            max_change = time_diff * 5 + self.profile['rssi_change_threshold']
            
            if rssi_diff > max_change:
                history.append((timestamp, rssi))
                return True, f"RSSI teleportation: {rssi_diff:.0f}dB in {time_diff:.1f}s"
        
        history.append((timestamp, rssi))
        if len(history) > 100:
            history.pop(0)
            
        return False, None


# =============================================================================
# MAIN ENHANCED DETECTOR
# =============================================================================

class EnhancedSignalInjectionDetector:
    """Enhanced detection system with detailed analysis"""
    
    def __init__(self, sensitivity='medium', log_file=None):
        self.sensitivity = sensitivity
        self.log_file = log_file
        
        print(f"Initializing Enhanced Signal Injection Detector")
        print(f"Sensitivity: {sensitivity} - {SENSITIVITY_PROFILES[sensitivity]['description']}")
        print()
        
        # Initialize sensors
        self.wifi = RealWiFiSensor(sensitivity)
        self.bluetooth = RealBluetoothSensor(sensitivity)
        self.audio = EnhancedAudioSensor(sensitivity=sensitivity)
        
        # State
        self.threat_log = deque(maxlen=1000)
        self.start_time = time.time()
        self.sample_count = 0
        
    def initialize(self):
        status = {}
        
        status['wifi'] = self.wifi.interface is not None
        print(f"  {'✓' if status['wifi'] else '✗'} WiFi sensor ({self.wifi.interface or 'not found'})")
        
        status['bluetooth'] = self.bluetooth.scan_available
        print(f"  {'✓' if status['bluetooth'] else '✗'} Bluetooth sensor")
        
        status['audio'] = self.audio.start()
        print(f"  {'✓' if status['audio'] else '✗'} Audio sensor (microphone)")
        
        print()
        return status
    
    def collect_and_analyze(self):
        timestamp = time.time()
        threats = []
        
        data = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'sensitivity': self.sensitivity,
            'wifi': {},
            'bluetooth': {},
            'audio': {}
        }
        
        # WiFi
        wifi_data = self.wifi.read_data()
        data['wifi'] = wifi_data
        wifi_threats = self.wifi.check_anomalies(wifi_data)
        threats.extend(wifi_threats)
        
        # Bluetooth (less frequent)
        if self.sample_count % 10 == 0 and self.bluetooth.scan_available:
            devices = self.bluetooth.scan_devices(duration=1)
            data['bluetooth'] = {'devices': devices, 'count': len(devices)}
        
        # Audio (detailed analysis)
        audio_sample = self.audio.get_sample()
        if audio_sample is not None:
            audio_analysis = self.audio.analyze(audio_sample)
            data['audio'] = audio_analysis
            
            if audio_analysis and audio_analysis.get('ultrasonic_suspicious'):
                threat_msg = f"Ultrasonic detected (ratio: {audio_analysis.get('ultrasonic_to_voice_ratio', 0):.2f})"
                if audio_analysis.get('ultrasonic_peaks'):
                    peak_freq = audio_analysis['ultrasonic_peaks'][0]['frequency']
                    threat_msg += f" @ {peak_freq:.0f}Hz"
                if audio_analysis.get('likely_sources'):
                    threat_msg += f" [Likely: {audio_analysis['likely_sources'][0]}]"
                threats.append(('Audio', threat_msg))
                
            if audio_analysis and audio_analysis.get('replay_detected'):
                threats.append(('Audio', 'Audio replay attack detected'))
        
        # Risk level
        threat_count = len(threats)
        if threat_count >= 3:
            data['risk_level'] = 'CRITICAL'
        elif threat_count >= 2:
            data['risk_level'] = 'HIGH'
        elif threat_count >= 1:
            data['risk_level'] = 'MEDIUM'
        else:
            data['risk_level'] = 'LOW'
        
        data['threats'] = threats
        self.sample_count += 1
        
        return data
    
    def display_dashboard(self, data):
        os.system('clear' if os.name != 'nt' else 'cls')
        
        # Header
        print("╔" + "═" * 74 + "╗")
        print("║" + " " * 14 + "ENHANCED SIGNAL INJECTION DETECTOR" + " " * 25 + "║")
        sens_info = f"Sensitivity: {self.sensitivity.upper()}"
        print(f"║  {data['datetime'][:19]}   {sens_info}   Sample #{self.sample_count}" + " " * 10 + "║")
        print("╚" + "═" * 74 + "╝")
        print()
        
        # WiFi
        wifi = data.get('wifi', {})
        print("┌─ WiFi STATUS " + "─" * 60 + "┐")
        if wifi.get('ssid'):
            print(f"│  SSID: {wifi['ssid']:<66}│")
            print(f"│  Signal: {wifi.get('rssi', 'N/A')} dBm   Quality: {wifi.get('quality', 'N/A')}" + " " * 42 + "│")
        else:
            print("│  No WiFi connection" + " " * 54 + "│")
        print("└" + "─" * 74 + "┘")
        print()
        
        # Audio - Detailed
        audio = data.get('audio', {})
        print("┌─ AUDIO ANALYSIS " + "─" * 57 + "┐")
        
        if audio and audio.get('status') != 'silent':
            # Basic levels
            print(f"│  Level: RMS={audio.get('rms', 0):.4f}  Peak={audio.get('peak', 0):.4f}" + " " * 40 + "│")
            
            # Ultrasonic details
            ratio = audio.get('ultrasonic_to_voice_ratio', 0)
            energy = audio.get('ultrasonic_energy', 0)
            print(f"│  Ultrasonic: Energy={energy:.1f}  Ratio={ratio:.3f}" + " " * 38 + "│")
            
            # Peak frequencies
            peaks = audio.get('ultrasonic_peaks', [])
            if peaks:
                peak_str = ", ".join([f"{p['frequency']:.0f}Hz" for p in peaks[:3]])
                print(f"│  Peak Frequencies: {peak_str}" + " " * (53 - len(peak_str)) + "│")
            
            # Likely sources
            sources = audio.get('likely_sources', [])
            if sources:
                print(f"│  Likely Source: {sources[0]}" + " " * (56 - len(sources[0])) + "│")
            
            # Pattern
            pattern = audio.get('pattern', '')
            if pattern:
                print(f"│  Pattern: {pattern}" + " " * (62 - len(pattern)) + "│")
            
            # Threat reasons
            reasons = audio.get('threat_reasons', [])
            if reasons:
                print("│  " + "─" * 72 + "│")
                for reason in reasons[:3]:
                    reason_display = reason[:68]
                    print(f"│  ⚠ {reason_display}" + " " * (69 - len(reason_display)) + "│")
        else:
            status = audio.get('status', 'no data')
            print(f"│  Status: {status}" + " " * (63 - len(status)) + "│")
        
        print("└" + "─" * 74 + "┘")
        print()
        
        # Frequency bands (if available)
        if audio and 'band_energy' in audio:
            bands = audio['band_energy']
            print("┌─ FREQUENCY SPECTRUM " + "─" * 53 + "┐")
            
            # Show ultrasonic bands specifically
            ultra_low = bands.get('ultrasonic_low', 0)
            ultra_mid = bands.get('ultrasonic_mid', 0)
            ultra_high = bands.get('ultrasonic_high', 0)
            
            # Create visual bar
            max_val = max(ultra_low, ultra_mid, ultra_high, 1)
            bar_low = "█" * int(ultra_low / max_val * 20) if max_val > 0 else ""
            bar_mid = "█" * int(ultra_mid / max_val * 20) if max_val > 0 else ""
            bar_high = "█" * int(ultra_high / max_val * 20) if max_val > 0 else ""
            
            print(f"│  18-19kHz: {bar_low:<20} {ultra_low:>10.1f}" + " " * 28 + "│")
            print(f"│  19-20kHz: {bar_mid:<20} {ultra_mid:>10.1f}" + " " * 28 + "│")
            print(f"│  20-22kHz: {bar_high:<20} {ultra_high:>10.1f}" + " " * 28 + "│")
            
            print("└" + "─" * 74 + "┘")
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
        
        print("┌─ THREAT ASSESSMENT " + "─" * 54 + "┐")
        print(f"│  Risk Level: {color}{data['risk_level']}{reset}" + " " * (59 - len(data['risk_level'])) + "│")
        print(f"│  Active Threats: {len(data['threats'])}   Total Logged: {len(self.audio.detailed_log)}" + " " * 32 + "│")
        print("│" + " " * 74 + "│")
        
        if data['threats']:
            for threat_type, message in data['threats'][:4]:
                line = f"│  🚨 [{threat_type}] {message}"
                # Truncate if too long
                if len(line) > 73:
                    line = line[:70] + "..."
                padding = 75 - len(line) + 4
                print(line + " " * max(0, padding) + "│")
        else:
            print("│  ✅ All sensors normal" + " " * 51 + "│")
        
        print("└" + "─" * 74 + "┘")
        print()
        
        # Recent threat log
        recent_threats = list(self.audio.detailed_log)[-3:]
        if recent_threats:
            print("┌─ RECENT THREAT LOG " + "─" * 54 + "┐")
            for entry in recent_threats:
                ts = entry['timestamp'][11:19]
                level = entry['threat_level']
                ratio = entry.get('ratio', 0)
                freq = entry['peak_frequencies'][0]['frequency'] if entry.get('peak_frequencies') else 0
                line = f"│  [{ts}] {level.upper()}: ratio={ratio:.2f} @ {freq:.0f}Hz"
                print(line + " " * (74 - len(line)) + "│")
            print("└" + "─" * 74 + "┘")
            print()
        
        print(f"  Sensitivity: {self.sensitivity} | Press Ctrl+C to stop | --sensitivity [low/medium/high/paranoid]")
    
    def run(self, interval=1.0):
        try:
            while True:
                data = self.collect_and_analyze()
                self.display_dashboard(data)
                
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
    
    def cleanup(self):
        # Export log if requested
        if self.log_file:
            count = self.audio.export_log(self.log_file)
            print(f"Exported {count} events to {self.log_file}")
        
        self.audio.stop()
        
        # Summary
        print(f"\n=== Session Summary ===")
        print(f"Duration: {time.time() - self.start_time:.0f} seconds")
        print(f"Samples: {self.sample_count}")
        print(f"Threats logged: {len(self.audio.detailed_log)}")
        
        if self.audio.detailed_log:
            print("\nRecent threats:")
            for entry in list(self.audio.detailed_log)[-5:]:
                print(f"  [{entry['timestamp'][:19]}] {entry['threat_level'].upper()}")
                for reason in entry['reasons'][:2]:
                    print(f"      → {reason}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Enhanced Signal Injection Detection System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sensitivity Levels:
    low      - Only obvious attacks (ratio > 0.8)
    medium   - Balanced detection (ratio > 0.4) [DEFAULT]
    high     - Sensitive (ratio > 0.2, may have false positives)
    paranoid - Maximum sensitivity (ratio > 0.1)

Examples:
    python3 %(prog)s
    python3 %(prog)s --sensitivity low
    python3 %(prog)s --sensitivity paranoid --log-file threats.json
        """
    )
    parser.add_argument('--sensitivity', '-s', 
                        choices=['low', 'medium', 'high', 'paranoid'],
                        default='medium',
                        help='Detection sensitivity level')
    parser.add_argument('--log-file', '-l',
                        help='Export detailed threat log to JSON file')
    parser.add_argument('--interval', '-i', type=float, default=1.0,
                        help='Monitoring interval in seconds')
    
    args = parser.parse_args()
    
    print("=" * 76)
    print("  ENHANCED SIGNAL INJECTION DETECTION SYSTEM")
    print("=" * 76)
    print()
    
    detector = EnhancedSignalInjectionDetector(
        sensitivity=args.sensitivity,
        log_file=args.log_file
    )
    
    status = detector.initialize()
    
    if not status.get('audio'):
        print("⚠ Audio sensor not available. Install pyaudio:")
        print("    pip install pyaudio --break-system-packages")
        print()
    
    print("Starting monitoring...")
    time.sleep(1)
    
    detector.run(interval=args.interval)


if __name__ == "__main__":
    main()