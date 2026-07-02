#!/usr/bin/env python3
"""
Signal Injection Detection App
Interactive demonstration of multi-sensor security monitoring

Features:
- Real-time sensor simulation
- Visual threat dashboard
- Attack scenario testing
- Comprehensive threat reporting
"""

import numpy as np
from collections import deque
from datetime import datetime
import hashlib
import time
import random
import os
import sys

# ======================
# CORE DETECTION CLASSES
# ======================

class CSIInjectionDetector:
    def __init__(self):
        self.packet_timestamps = deque(maxlen=1000)
        self.packet_hashes = deque(maxlen=1000)
        self.csi_amplitudes = deque(maxlen=1000)
        
    def check_replay_attack(self, packet_data, timestamp):
        packet_hash = hashlib.sha256(packet_data).hexdigest()
        if packet_hash in self.packet_hashes:
            return True, "Duplicate packet detected (replay attack)"
        self.packet_hashes.append(packet_hash)
        self.packet_timestamps.append(timestamp)
        if len(self.packet_timestamps) > 100:
            intervals = np.diff(list(self.packet_timestamps)[-100:])
            timing_std = np.std(intervals)
            if timing_std < 0.001:
                return True, "Suspiciously regular packet timing"
        return False, None
    
    def check_physics_plausibility(self, heart_rate, confidence, csi_amplitude):
        issues = []
        if heart_rate < 30 or heart_rate > 200:
            issues.append(f"Implausible heart rate: {heart_rate} BPM")
        if len(self.csi_amplitudes) > 10:
            recent_amps = list(self.csi_amplitudes)[-10:]
            max_change = max(abs(np.diff(recent_amps)))
            if max_change > 50:
                issues.append(f"Sudden amplitude change: {max_change:.1f}")
        self.csi_amplitudes.append(csi_amplitude)
        if confidence > 0.8 and csi_amplitude < 10:
            issues.append("High confidence with weak signal")
        return len(issues) > 0, issues


class TouchInjectionDetector:
    def __init__(self):
        self.touch_events = deque(maxlen=100)
        self.em_readings = deque(maxlen=100)
        self.accel_readings = deque(maxlen=100)
        
    def detect_em_touch_correlation(self, em_level, touch_occurred, timestamp):
        self.em_readings.append((timestamp, em_level))
        self.touch_events.append((timestamp, touch_occurred))
        if len(self.em_readings) < 50:
            return False, None
        em_data = np.array([e[1] for e in list(self.em_readings)[-50:]])
        touch_data = np.array([t[1] for t in list(self.touch_events)[-50:]])
        if np.std(em_data) > 0 and np.std(touch_data) > 0:
            correlation = np.corrcoef(em_data, touch_data)[0, 1]
            if abs(correlation) > 0.6:
                return True, f"EM-touch correlation: {correlation:.2f}"
        return False, None
    
    def validate_touch_physics(self, pressure, size, duration_ms):
        issues = []
        if pressure < 0.05 or pressure > 0.95:
            issues.append(f"Suspicious pressure: {pressure:.2f}")
        if size < 5 or size > 100:
            issues.append(f"Unusual touch size: {size}px")
        if duration_ms < 10:
            issues.append(f"Touch too brief: {duration_ms}ms")
        return len(issues) > 0, issues


class BLESpoofingDetector:
    def __init__(self):
        self.device_history = {}
        self.mac_profiles = {}
        
    def check_rssi_teleportation(self, mac, current_rssi, timestamp):
        if mac not in self.device_history:
            self.device_history[mac] = [(timestamp, current_rssi)]
            return False, None
        history = self.device_history[mac]
        if len(history) > 0:
            last_ts, last_rssi = history[-1]
            time_diff = max(timestamp - last_ts, 0.001)
            rssi_diff = abs(current_rssi - last_rssi)
            max_change = time_diff * 5
            if rssi_diff > max_change + 10:
                return True, f"RSSI teleportation: {rssi_diff:.0f}dB in {time_diff:.1f}s"
        history.append((timestamp, current_rssi))
        if len(history) > 100:
            history.pop(0)
        return False, None
    
    def fingerprint_device(self, mac, advertisement_data):
        fingerprint = {
            'adv_length': len(advertisement_data),
            'adv_hash': hashlib.md5(advertisement_data).hexdigest()[:8]
        }
        if mac not in self.mac_profiles:
            self.mac_profiles[mac] = fingerprint
            return False, None
        known_fp = self.mac_profiles[mac]
        if fingerprint['adv_hash'] != known_fp['adv_hash']:
            return True, "Device fingerprint changed (possible clone)"
        return False, None


class AudioInjectionDetector:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.audio_hashes = deque(maxlen=100)
        
    def detect_ultrasonic_injection(self, audio_data):
        fft = np.fft.rfft(audio_data)
        freqs = np.fft.rfftfreq(len(audio_data), 1/self.sample_rate)
        magnitude = np.abs(fft)
        ultrasonic_mask = (freqs >= 20000) & (freqs <= 24000)
        ultrasonic_energy = np.sum(magnitude[ultrasonic_mask])
        audible_mask = (freqs >= 300) & (freqs <= 3400)
        audible_energy = np.sum(magnitude[audible_mask])
        if audible_energy > 0 and ultrasonic_energy > audible_energy * 0.1:
            return True, f"Ultrasonic signal detected"
        return False, None
    
    def detect_audio_replay(self, audio_segment):
        audio_hash = hashlib.md5(audio_segment.tobytes()).hexdigest()
        if audio_hash in self.audio_hashes:
            return True, "Audio replay detected"
        self.audio_hashes.append(audio_hash)
        return False, None


class GPSSpoofingDetector:
    def __init__(self):
        self.location_history = deque(maxlen=100)
        
    def check_location_jump(self, lat, lon, timestamp):
        if len(self.location_history) == 0:
            self.location_history.append((timestamp, lat, lon))
            return False, None
        last_ts, last_lat, last_lon = self.location_history[-1]
        time_diff = max(timestamp - last_ts, 0.001)
        # Approximate distance in meters
        lat_diff = abs(lat - last_lat) * 111000
        lon_diff = abs(lon - last_lon) * 111000 * np.cos(np.radians(lat))
        distance = np.sqrt(lat_diff**2 + lon_diff**2)
        speed = distance / time_diff  # m/s
        # Max realistic speed ~100 m/s (360 km/h)
        if speed > 100:
            return True, f"GPS teleportation: {speed:.0f} m/s"
        self.location_history.append((timestamp, lat, lon))
        return False, None


# ======================
# MULTI-SENSOR FUSION
# ======================

class MultiSensorFusionDetector:
    def __init__(self):
        self.csi_detector = CSIInjectionDetector()
        self.touch_detector = TouchInjectionDetector()
        self.ble_detector = BLESpoofingDetector()
        self.audio_detector = AudioInjectionDetector()
        self.gps_detector = GPSSpoofingDetector()
        
    def validate_heartbeat(self, csi_hr, camera_hr, smartwatch_hr):
        sources = {'csi': csi_hr, 'camera': camera_hr, 'smartwatch': smartwatch_hr}
        valid_sources = {k: v for k, v in sources.items() if v is not None}
        if len(valid_sources) < 2:
            return None, "Insufficient sources"
        values = list(valid_sources.values())
        mean_hr = np.mean(values)
        max_deviation = max([abs(v - mean_hr) for v in values])
        if max_deviation > 10:
            outliers = [k for k, v in valid_sources.items() if abs(v - mean_hr) > 10]
            return True, f"HR mismatch: {outliers} spoofed"
        return False, None
    
    def comprehensive_check(self, sensor_data):
        threats = []
        
        # CSI injection
        if 'csi_packet' in sensor_data:
            is_threat, msg = self.csi_detector.check_replay_attack(
                sensor_data['csi_packet'],
                sensor_data.get('timestamp', time.time())
            )
            if is_threat:
                threats.append(('CSI Injection', msg))
        
        # Touch injection
        if 'touch_event' in sensor_data and 'em_level' in sensor_data:
            is_threat, msg = self.touch_detector.detect_em_touch_correlation(
                sensor_data['em_level'],
                sensor_data['touch_event'],
                sensor_data.get('timestamp', time.time())
            )
            if is_threat:
                threats.append(('Touch Injection', msg))
        
        # BLE spoofing
        if 'ble_mac' in sensor_data and 'ble_rssi' in sensor_data:
            is_threat, msg = self.ble_detector.check_rssi_teleportation(
                sensor_data['ble_mac'],
                sensor_data['ble_rssi'],
                sensor_data.get('timestamp', time.time())
            )
            if is_threat:
                threats.append(('BLE Spoofing', msg))
        
        # Audio injection
        if 'audio_data' in sensor_data:
            is_threat, msg = self.audio_detector.detect_ultrasonic_injection(
                sensor_data['audio_data']
            )
            if is_threat:
                threats.append(('Audio Injection', msg))
        
        # GPS spoofing
        if all(k in sensor_data for k in ['gps_lat', 'gps_lon']):
            is_threat, msg = self.gps_detector.check_location_jump(
                sensor_data['gps_lat'],
                sensor_data['gps_lon'],
                sensor_data.get('timestamp', time.time())
            )
            if is_threat:
                threats.append(('GPS Spoofing', msg))
        
        # Cross-validation
        if all(k in sensor_data for k in ['csi_hr', 'camera_hr']):
            is_threat, msg = self.validate_heartbeat(
                sensor_data.get('csi_hr'),
                sensor_data.get('camera_hr'),
                sensor_data.get('smartwatch_hr')
            )
            if is_threat:
                threats.append(('Cross-validation', msg))
        
        return {
            'timestamp': datetime.now().isoformat(),
            'threat_detected': len(threats) > 0,
            'threat_count': len(threats),
            'threats': threats,
            'risk_level': 'HIGH' if len(threats) >= 2 else ('MEDIUM' if len(threats) == 1 else 'LOW')
        }


# ======================
# SENSOR SIMULATOR
# ======================

class SensorSimulator:
    """Simulates realistic and attack sensor data"""
    
    def __init__(self):
        self.base_hr = 72
        self.base_lat = 43.6532
        self.base_lon = -79.3832
        self.ble_mac = 'aa:bb:cc:dd:ee:ff'
        self.base_rssi = -65
        self.packet_counter = 0
        
    def generate_normal_data(self):
        """Generate realistic sensor data"""
        self.packet_counter += 1
        hr_variation = random.gauss(0, 2)
        
        return {
            'timestamp': time.time(),
            'csi_packet': f'csi_packet_{self.packet_counter}_{random.random()}'.encode(),
            'csi_hr': self.base_hr + hr_variation,
            'camera_hr': self.base_hr + hr_variation + random.gauss(0, 1),
            'smartwatch_hr': self.base_hr + hr_variation + random.gauss(0, 1.5),
            'touch_event': random.random() > 0.9,
            'em_level': random.gauss(45, 5),
            'ble_mac': self.ble_mac,
            'ble_rssi': self.base_rssi + random.gauss(0, 2),
            'gps_lat': self.base_lat + random.gauss(0, 0.00001),
            'gps_lon': self.base_lon + random.gauss(0, 0.00001),
            'audio_data': np.random.normal(0, 0.1, 1000)
        }
    
    def generate_csi_replay_attack(self):
        """Generate CSI replay attack data"""
        data = self.generate_normal_data()
        # Use same packet (replay)
        data['csi_packet'] = b'replayed_csi_packet_static'
        return data
    
    def generate_touch_injection_attack(self):
        """Generate EM touch injection attack"""
        data = self.generate_normal_data()
        # High correlation between EM and touch
        data['touch_event'] = True
        data['em_level'] = 95.0  # Spike
        return data
    
    def generate_ble_spoofing_attack(self):
        """Generate BLE RSSI teleportation"""
        data = self.generate_normal_data()
        # Sudden RSSI jump
        data['ble_rssi'] = -30  # Jump from -65 to -30
        return data
    
    def generate_audio_injection_attack(self):
        """Generate ultrasonic audio attack"""
        data = self.generate_normal_data()
        # Add ultrasonic component
        t = np.arange(1000) / 16000
        ultrasonic = np.sin(2 * np.pi * 22000 * t) * 0.5
        data['audio_data'] = np.random.normal(0, 0.1, 1000) + ultrasonic
        return data
    
    def generate_gps_spoofing_attack(self):
        """Generate GPS location jump"""
        data = self.generate_normal_data()
        # Teleport to different location
        data['gps_lat'] = self.base_lat + 0.1  # ~11km jump
        data['gps_lon'] = self.base_lon + 0.1
        return data
    
    def generate_heartrate_mismatch_attack(self):
        """Generate mismatched heartrate data"""
        data = self.generate_normal_data()
        # CSI shows different HR than camera/watch
        data['csi_hr'] = 120  # While others show ~72
        return data
    
    def generate_multi_vector_attack(self):
        """Generate combined attack"""
        data = self.generate_normal_data()
        data['csi_packet'] = b'replayed_csi_packet_static'
        data['ble_rssi'] = -25
        data['csi_hr'] = 110
        t = np.arange(1000) / 16000
        data['audio_data'] += np.sin(2 * np.pi * 21000 * t) * 0.3
        return data


# ======================
# VISUAL INTERFACE
# ======================

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "SIGNAL INJECTION DETECTION SYSTEM" + " " * 18 + "║")
    print("║" + " " * 20 + "Security Monitoring Dashboard" + " " * 18 + "║")
    print("╚" + "═" * 68 + "╝")
    print()

def print_sensor_status(data):
    print("┌─ SENSOR STATUS " + "─" * 52 + "┐")
    print(f"│  CSI Heart Rate:    {data.get('csi_hr', 0):>6.1f} BPM" + " " * 35 + "│")
    print(f"│  Camera Heart Rate: {data.get('camera_hr', 0):>6.1f} BPM" + " " * 35 + "│")
    print(f"│  Watch Heart Rate:  {data.get('smartwatch_hr', 0):>6.1f} BPM" + " " * 35 + "│")
    print(f"│  BLE RSSI:          {data.get('ble_rssi', 0):>6.1f} dBm" + " " * 35 + "│")
    print(f"│  EM Level:          {data.get('em_level', 0):>6.1f}" + " " * 40 + "│")
    print(f"│  GPS:               {data.get('gps_lat', 0):.4f}, {data.get('gps_lon', 0):.4f}" + " " * 22 + "│")
    print("└" + "─" * 68 + "┘")
    print()

def get_risk_color(level):
    colors = {'LOW': '\033[92m', 'MEDIUM': '\033[93m', 'HIGH': '\033[91m'}
    return colors.get(level, '')

def print_threat_report(result):
    reset = '\033[0m'
    color = get_risk_color(result['risk_level'])
    
    print("┌─ THREAT ASSESSMENT " + "─" * 48 + "┐")
    
    level_display = f"{color}{result['risk_level']}{reset}"
    padding = 68 - len(f"│  Risk Level: {result['risk_level']}") - 1
    print(f"│  Risk Level: {level_display}" + " " * (padding + len(color) + len(reset)) + "│")
    
    print(f"│  Threats Detected: {result['threat_count']}" + " " * 45 + "│")
    print("│" + " " * 68 + "│")
    
    if result['threats']:
        for threat_type, message in result['threats']:
            line = f"│  ⚠  {threat_type}: {message}"
            padding = 69 - len(line)
            print(line + " " * padding + "│")
    else:
        print("│  ✓  No threats detected" + " " * 43 + "│")
    
    print("└" + "─" * 68 + "┘")
    print()

def print_menu():
    print("┌─ SIMULATION OPTIONS " + "─" * 47 + "┐")
    print("│  [1] Normal Sensor Data                                            │")
    print("│  [2] CSI Replay Attack                                              │")
    print("│  [3] Touch Injection Attack                                         │")
    print("│  [4] BLE Spoofing Attack                                            │")
    print("│  [5] Audio (Ultrasonic) Injection                                   │")
    print("│  [6] GPS Spoofing Attack                                            │")
    print("│  [7] Heartrate Mismatch Attack                                      │")
    print("│  [8] Multi-Vector Attack (Combined)                                 │")
    print("│  [9] Run Continuous Simulation                                      │")
    print("│  [0] Exit                                                           │")
    print("└" + "─" * 68 + "┘")
    print()

def run_single_test(detector, simulator, attack_type):
    generators = {
        '1': ('Normal Data', simulator.generate_normal_data),
        '2': ('CSI Replay Attack', simulator.generate_csi_replay_attack),
        '3': ('Touch Injection', simulator.generate_touch_injection_attack),
        '4': ('BLE Spoofing', simulator.generate_ble_spoofing_attack),
        '5': ('Audio Injection', simulator.generate_audio_injection_attack),
        '6': ('GPS Spoofing', simulator.generate_gps_spoofing_attack),
        '7': ('HR Mismatch', simulator.generate_heartrate_mismatch_attack),
        '8': ('Multi-Vector', simulator.generate_multi_vector_attack),
    }
    
    if attack_type not in generators:
        return
    
    name, generator = generators[attack_type]
    
    clear_screen()
    print_header()
    print(f"  Testing: {name}")
    print("  " + "=" * 50)
    print()
    
    # For attacks that need history, run a few normal cycles first
    if attack_type != '1':
        for _ in range(5):
            normal_data = simulator.generate_normal_data()
            detector.comprehensive_check(normal_data)
            time.sleep(0.05)
    
    # Now run the test
    data = generator()
    result = detector.comprehensive_check(data)
    
    print_sensor_status(data)
    print_threat_report(result)
    
    input("  Press Enter to continue...")

def run_continuous_simulation(detector, simulator):
    """Run continuous mixed simulation"""
    clear_screen()
    print_header()
    print("  Continuous Simulation Mode")
    print("  Press Ctrl+C to stop")
    print()
    
    attack_generators = [
        simulator.generate_csi_replay_attack,
        simulator.generate_touch_injection_attack,
        simulator.generate_ble_spoofing_attack,
        simulator.generate_audio_injection_attack,
        simulator.generate_gps_spoofing_attack,
        simulator.generate_heartrate_mismatch_attack,
    ]
    
    cycle = 0
    threats_detected = 0
    
    try:
        while True:
            cycle += 1
            
            # 70% normal, 30% attack
            if random.random() < 0.7:
                data = simulator.generate_normal_data()
                scenario = "Normal"
            else:
                generator = random.choice(attack_generators)
                data = generator()
                scenario = "Attack"
            
            result = detector.comprehensive_check(data)
            
            if result['threat_detected']:
                threats_detected += 1
            
            # Update display
            clear_screen()
            print_header()
            print(f"  Continuous Simulation - Cycle {cycle}")
            print(f"  Total Threats Detected: {threats_detected}")
            print(f"  Current Scenario: {scenario}")
            print("  Press Ctrl+C to stop")
            print()
            
            print_sensor_status(data)
            print_threat_report(result)
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print()
        print("  Simulation stopped.")
        print(f"  Total cycles: {cycle}")
        print(f"  Threats detected: {threats_detected}")
        input("  Press Enter to continue...")

def main():
    detector = MultiSensorFusionDetector()
    simulator = SensorSimulator()
    
    while True:
        clear_screen()
        print_header()
        print_menu()
        
        choice = input("  Select option: ").strip()
        
        if choice == '0':
            clear_screen()
            print("  Thank you for using Signal Injection Detection System")
            print()
            break
        elif choice == '9':
            run_continuous_simulation(detector, simulator)
            # Reset detector after simulation
            detector = MultiSensorFusionDetector()
            simulator = SensorSimulator()
        elif choice in '12345678':
            run_single_test(detector, simulator, choice)
            # Reset detector for fresh test
            detector = MultiSensorFusionDetector()
            simulator = SensorSimulator()
        else:
            print("  Invalid option. Press Enter to continue...")
            input()

if __name__ == "__main__":
    main()