#!/usr/bin/env python3
"""
Attack Source Detector
======================

Specifically designed to detect:
1. Bluetooth devices with accurate distance estimation
2. Hidden speakers projecting audio (including Live Listen abuse)
3. Vehicle transducers being used for ultrasonic attacks

Requirements:
    pip install bleak numpy scipy sounddevice --break-system-packages

Usage:
    python attack_source_detector.py --scan          # Full scan
    python attack_source_detector.py --bluetooth     # BT only
    python attack_source_detector.py --car           # Car transducer detection
    python attack_source_detector.py --monitor       # Continuous monitoring
"""

import asyncio
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from enum import Enum
import json
import time
import sys
import os

# ============================================================================
# SECTION 1: BLUETOOTH DEVICE DISTANCE DETECTION
# ============================================================================

"""
HOW BLUETOOTH DISTANCE ESTIMATION WORKS:
========================================

RSSI (Received Signal Strength Indicator) is measured in dBm.
Typical values:
    -30 dBm = Excellent (very close, ~1m)
    -50 dBm = Good (~2-3m)  
    -60 dBm = Fair (~5-10m)
    -70 dBm = Weak (~10-15m)
    -80 dBm = Very Weak (~15-20m)
    -90 dBm = Unusable (>20m)

Distance Formula (Log-Distance Path Loss Model):
    distance = 10 ^ ((TxPower - RSSI) / (10 * n))

Where:
    TxPower = Expected RSSI at 1 meter (typically -59 dBm)
    n = Path loss exponent:
        - 2.0 = Free space (outdoors, no obstacles)
        - 2.5 = Light indoor
        - 3.0 = Indoor with walls
        - 4.0 = Dense indoor/obstacles
"""

@dataclass
class BluetoothDevice:
    """Detected Bluetooth device"""
    address: str
    name: Optional[str]
    rssi: int                    # dBm
    distance_m: float            # Estimated meters
    device_type: str             # speaker, phone, vehicle, etc.
    manufacturer: Optional[str]
    threat_level: str            # low, medium, high
    is_speaker: bool
    is_vehicle: bool
    services: List[str] = field(default_factory=list)
    last_seen: str = ""


class BluetoothDistanceScanner:
    """
    Scans for Bluetooth devices and estimates distance
    """
    
    # Calibration values (adjust based on your environment)
    TX_POWER = -59          # Expected RSSI at 1 meter
    PATH_LOSS_EXP = 2.5     # Path loss exponent (2.5 for typical indoor)
    
    # Device classification keywords
    SPEAKER_KEYWORDS = [
        'speaker', 'soundbar', 'audio', 'jbl', 'bose', 'sonos', 'harman',
        'marshall', 'beats', 'ue boom', 'anker', 'soundcore', 'sony srs',
        'flip', 'charge', 'pulse', 'boom', 'megaboom', 'wonderboom',
        'homepod', 'echo', 'alexa', 'google home', 'nest', 'soundlink'
    ]
    
    VEHICLE_KEYWORDS = [
        'car', 'auto', 'ford', 'sync', 'chevy', 'mylink', 'toyota', 'entune',
        'honda', 'handsfreelink', 'bmw', 'idrive', 'audi', 'mmi', 'mercedes',
        'mbux', 'vw', 'volkswagen', 'nissan', 'kia', 'uvo', 'hyundai',
        'bluelink', 'lexus', 'enform', 'infiniti', 'acura', 'cadillac', 'cue',
        'jeep', 'uconnect', 'chrysler', 'dodge', 'ram', 'mazda', 'volvo', 
        'sensus', 'tesla', 'rivian', 'lucid',
        # ===== SUBARU STARLINK COMPREHENSIVE =====
        'subaru', 'starlink', 'subaru bt', 'subaru_bt', 'subarubt',
        # Subaru Models
        'outback', 'forester', 'crosstrek', 'impreza', 'legacy', 'ascent',
        'wrx', 'sti', 'brz', 'solterra', 'baja', 'tribeca', 'xv',
        # Subaru Infotainment Suppliers
        'harman kardon', 'harman-kardon', 'harmankardon', 'hk audio',
        'denso', 'denso ten', 'denso-ten', 'densoten', 'denso cp1',
        'fujitsu ten', 'fujitsu-ten', 'fujitsuten', 'ften', 'f10', 'd10',
        'clarion',
        # Subaru System Names
        'eyesight', 'x-mode', 'xmode', 'si-drive', 'sidrive',
        'mysubaru', 'subaru connected'
    ]
    
    # ===== SUBARU-SPECIFIC BLUETOOTH NAME PATTERNS =====
    SUBARU_BT_PATTERNS = [
        'subaru bt',           # Standard Subaru Bluetooth name
        'subaru_bt',
        'subarubt',
        'subaru bluetooth',
        'starlink',            # STARLINK system
        'outback',             # Model-specific names
        'forester',
        'crosstrek',
        'impreza',
        'legacy',
        'ascent',
        'wrx',
        'brz',
        'solterra'
    ]
    
    # Manufacturer OUI lookup (first 3 bytes of MAC)
    MANUFACTURER_OUI = {
        # Apple
        'AC:37:43': 'Apple', '00:1A:7D': 'Apple', '7C:D1:C3': 'Apple',
        '88:E9:FE': 'Apple', 'DC:A4:CA': 'Apple', '98:D6:BB': 'Apple',
        '00:25:00': 'Apple', 'F4:F5:D8': 'Apple', '3C:06:30': 'Apple',
        # Google
        'F4:F5:D8': 'Google', '94:EB:2C': 'Google', '54:60:09': 'Google',
        # Samsung
        'FC:A8:9A': 'Samsung', '84:D8:1B': 'Samsung', '50:01:BB': 'Samsung',
        # Audio manufacturers (HIGH THREAT)
        '00:09:A7': 'JBL/Harman', '04:FE:31': 'Bose', '00:0C:8A': 'Bose',
        '88:C6:26': 'Bose', '2C:41:A1': 'Bose', '00:1D:DF': 'Harman',
        'B8:F6:53': 'Harman', 'AC:89:95': 'Sonos', '00:0E:58': 'Sonos',
        '54:2A:1B': 'Sonos', '78:28:CA': 'Sonos',
        
        # ===== SUBARU INFOTAINMENT SUPPLIERS =====
        # Harman International (Subaru Harman Kardon systems 2017+)
        '00:1D:DF': 'Harman/Subaru', 'B8:F6:53': 'Harman/Subaru',
        '00:0A:07': 'Harman', '00:24:B8': 'Harman', '68:84:7E': 'Harman',
        '74:5E:1C': 'Harman', 'A4:77:33': 'Harman', 'F4:4E:FD': 'Harman',
        '8C:DE:52': 'Harman', 'D0:8A:55': 'Harman', '00:26:B4': 'Harman',
        
        # Denso / Denso Ten (Subaru Denso CP1 systems)
        '00:1E:B6': 'Denso', '00:1B:B9': 'Denso', '00:17:CA': 'Denso',
        '00:1F:57': 'Denso', '04:E6:76': 'Denso', '38:A4:ED': 'Denso',
        '40:B0:34': 'Denso', '58:76:75': 'Denso', '6C:0E:E6': 'Denso',
        '70:1A:B8': 'Denso', '7C:03:AB': 'Denso', '84:C7:EA': 'Denso',
        '94:8B:C1': 'Denso', 'A0:6F:AA': 'Denso', 'A8:54:B2': 'Denso',
        'B0:10:41': 'Denso', 'B8:9A:CD': 'Denso', 'C4:4E:AC': 'Denso',
        'E8:DB:84': 'Denso', 'F0:27:65': 'Denso', '00:04:3E': 'Denso',
        
        # Fujitsu Ten / Denso Ten (Older Subaru systems pre-2017)
        '00:1E:4C': 'Fujitsu Ten/Subaru', '00:1A:E8': 'Fujitsu Ten',
        '00:0D:2A': 'Fujitsu Ten', '34:C7:31': 'Fujitsu Ten',
        '00:26:E4': 'Fujitsu Ten', '48:F8:B3': 'Fujitsu Ten',
        
        # Clarion (Some Subaru models)
        '00:02:37': 'Clarion/Subaru', '00:07:04': 'Clarion',
        '00:15:AC': 'Clarion', '00:19:43': 'Clarion', '00:1C:56': 'Clarion',
        '00:1E:52': 'Clarion', '00:22:61': 'Clarion', '00:24:A8': 'Clarion',
        '1C:48:CE': 'Clarion', '48:46:FB': 'Clarion', '90:E7:C4': 'Clarion',
        'D4:21:22': 'Clarion',
        
        # Panasonic Automotive (Some Subaru systems)
        '00:13:BA': 'Panasonic Auto', '00:1C:25': 'Panasonic',
        '00:80:45': 'Panasonic', '08:EB:ED': 'Panasonic',
        '34:FC:EF': 'Panasonic', '4C:BB:58': 'Panasonic',
        '58:D5:6E': 'Panasonic', 'A4:08:EA': 'Panasonic',
        
        # Pioneer (Aftermarket Subaru)
        '00:1A:E2': 'Pioneer', '00:22:09': 'Pioneer', '74:5F:00': 'Pioneer',
        'A8:B9:B3': 'Pioneer', 'DC:90:88': 'Pioneer',
        
        # Alpine (Aftermarket Subaru)
        '00:04:CE': 'Alpine', '30:14:4A': 'Alpine', '78:52:62': 'Alpine',
        
        # Wistron (Subaru WiFi modules - seen as "Winstron Device")
        '00:26:2D': 'Wistron/Subaru', '28:E3:47': 'Wistron',
        '74:E5:43': 'Wistron', '90:4C:E5': 'Wistron', 'D0:DF:9A': 'Wistron',
        
        # Generic Automotive Bluetooth Modules
        '00:07:80': 'Automotive BT', '00:12:37': 'Automotive BT',
        '00:1B:DC': 'Automotive BT', '00:23:01': 'Automotive BT',
        
        # ===== OTHER VEHICLE MANUFACTURERS =====
        # Vehicle (MEDIUM THREAT)
        '00:1D:A5': 'Ford SYNC', '00:26:B4': 'Ford', '00:0E:B2': 'Honda',
        '00:1C:B3': 'Toyota', '00:24:7E': 'Toyota', '7C:79:E8': 'BMW',
        '00:0E:8F': 'Audi', 'D8:5D:4C': 'Mercedes',
        '00:14:3E': 'Toyota/Lexus', '00:1E:AE': 'Toyota',
        '00:1A:C1': 'Honda/Acura', '00:22:A0': 'Mazda',
        '00:1E:75': 'Nissan', '00:1F:9D': 'Hyundai/Kia',
    }
    
    def __init__(self, tx_power: int = None, path_loss_exp: float = None):
        if tx_power:
            self.TX_POWER = tx_power
        if path_loss_exp:
            self.PATH_LOSS_EXP = path_loss_exp
        
        self.devices: Dict[str, BluetoothDevice] = {}
    
    def estimate_distance(self, rssi: int) -> float:
        """
        Estimate distance from RSSI value
        
        Uses Log-Distance Path Loss Model:
        distance = 10 ^ ((TxPower - RSSI) / (10 * n))
        """
        if rssi >= 0:
            return 0.0
        
        ratio = (self.TX_POWER - rssi) / (10 * self.PATH_LOSS_EXP)
        distance = 10 ** ratio
        
        return round(distance, 2)
    
    def get_manufacturer(self, address: str) -> Optional[str]:
        """Look up manufacturer from MAC address OUI"""
        oui = address[:8].upper()
        return self.MANUFACTURER_OUI.get(oui)
    
    def classify_device(self, name: str, address: str, 
                       manufacturer: str) -> Tuple[str, str, bool, bool]:
        """
        Classify device and assess threat level
        
        Returns: (device_type, threat_level, is_speaker, is_vehicle)
        """
        name_lower = (name or "").lower()
        mfr_lower = (manufacturer or "").lower()
        
        # Check for speakers (HIGH THREAT)
        is_speaker = any(kw in name_lower for kw in self.SPEAKER_KEYWORDS)
        if not is_speaker and manufacturer:
            is_speaker = any(kw in mfr_lower for kw in ['jbl', 'bose', 'sonos', 'harman'])
        
        # ===== ENHANCED SUBARU DETECTION =====
        is_subaru = False
        
        # Check for Subaru-specific Bluetooth names
        if hasattr(self, 'SUBARU_BT_PATTERNS'):
            is_subaru = any(pattern in name_lower for pattern in self.SUBARU_BT_PATTERNS)
        
        # Check for Subaru infotainment suppliers in manufacturer
        subaru_suppliers = ['denso', 'fujitsu', 'clarion', 'wistron', 'harman']
        if manufacturer and any(sup in mfr_lower for sup in subaru_suppliers):
            # If it's a Harman device, check if it's automotive (not just speaker)
            if 'subaru' in mfr_lower or 'auto' in mfr_lower:
                is_subaru = True
            elif 'denso' in mfr_lower or 'fujitsu' in mfr_lower or 'clarion' in mfr_lower:
                is_subaru = True  # These are primarily automotive
            elif 'wistron' in mfr_lower:
                is_subaru = True  # Wistron makes Subaru WiFi modules
        
        # Check for vehicles (MEDIUM THREAT)  
        is_vehicle = any(kw in name_lower for kw in self.VEHICLE_KEYWORDS)
        if not is_vehicle and manufacturer:
            is_vehicle = any(kw in mfr_lower for kw in ['ford', 'honda', 'toyota', 'bmw', 'denso', 'fujitsu', 'clarion'])
        
        # Subaru is a vehicle
        if is_subaru:
            is_vehicle = True
        
        # Determine type and threat
        if is_speaker:
            return 'SPEAKER', 'HIGH', True, False
        elif is_subaru:
            return 'SUBARU', 'MEDIUM', False, True  # Specific Subaru type
        elif is_vehicle:
            return 'VEHICLE', 'MEDIUM', False, True
        elif not name:
            return 'UNKNOWN', 'MEDIUM', False, False  # Unnamed = suspicious
        elif any(x in name_lower for x in ['phone', 'iphone', 'android', 'pixel']):
            return 'PHONE', 'LOW', False, False
        elif any(x in name_lower for x in ['airpods', 'buds', 'headphone']):
            return 'HEADPHONES', 'LOW', False, False
        elif any(x in name_lower for x in ['watch', 'band', 'fitbit', 'garmin']):
            return 'WEARABLE', 'LOW', False, False
        elif any(x in name_lower for x in ['macbook', 'laptop', 'pc', 'computer']):
            return 'COMPUTER', 'LOW', False, False
        else:
            return 'UNKNOWN', 'LOW', False, False
    
    async def scan(self, duration: float = 10.0) -> List[BluetoothDevice]:
        """
        Scan for BLE devices
        
        Args:
            duration: Scan duration in seconds
            
        Returns:
            List of detected devices sorted by threat/distance
        """
        try:
            from bleak import BleakScanner
        except ImportError:
            print("ERROR: bleak not installed")
            print("Run: pip install bleak --break-system-packages")
            return []
        
        print(f"\n🔍 Scanning for Bluetooth devices ({duration}s)...")
        
        try:
            discovered = await BleakScanner.discover(timeout=duration, return_adv=True)
        except Exception as e:
            print(f"Scan error: {e}")
            return []
        
        results = []
        now = datetime.now().isoformat()
        
        for address, (device, adv_data) in discovered.items():
            rssi = adv_data.rssi
            distance = self.estimate_distance(rssi)
            manufacturer = self.get_manufacturer(address)
            
            device_type, threat_level, is_speaker, is_vehicle = self.classify_device(
                device.name, address, manufacturer
            )
            
            bt_dev = BluetoothDevice(
                address=address,
                name=device.name,
                rssi=rssi,
                distance_m=distance,
                device_type=device_type,
                manufacturer=manufacturer,
                threat_level=threat_level,
                is_speaker=is_speaker,
                is_vehicle=is_vehicle,
                services=[str(s) for s in (adv_data.service_uuids or [])],
                last_seen=now
            )
            
            self.devices[address] = bt_dev
            results.append(bt_dev)
        
        # Sort: HIGH threat first, then by distance
        threat_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        results.sort(key=lambda x: (threat_order.get(x.threat_level, 2), x.distance_m))
        
        return results
    
    def print_results(self, devices: List[BluetoothDevice]):
        """Print formatted scan results"""
        
        print("\n" + "=" * 75)
        print("  BLUETOOTH DEVICE SCAN RESULTS")
        print("=" * 75)
        
        # Header
        print(f"\n{'THREAT':<8} {'NAME':<25} {'TYPE':<12} {'DIST':<8} {'RSSI':<10}")
        print("-" * 75)
        
        speakers = []
        vehicles = []
        subarus = []
        
        for dev in devices:
            name = (dev.name or f"[{dev.address}]")[:24]
            
            # Threat indicator
            if dev.threat_level == 'HIGH':
                threat_icon = "🔴 HIGH"
                speakers.append(dev)
            elif dev.threat_level == 'MEDIUM':
                threat_icon = "🟡 MED"
                if dev.is_vehicle:
                    vehicles.append(dev)
                    # Check if it's specifically a Subaru
                    if dev.device_type == 'SUBARU':
                        subarus.append(dev)
            else:
                threat_icon = "🟢 LOW"
            
            print(f"{threat_icon:<8} {name:<25} {dev.device_type:<12} "
                  f"{dev.distance_m:>5.1f}m  {dev.rssi:>4}dBm")
        
        print("-" * 75)
        print(f"Total devices: {len(devices)}")
        
        # Warnings
        if speakers:
            print("\n" + "⚠️ " * 20)
            print("⚠️  WARNING: POTENTIAL ATTACK SOURCES DETECTED!")
            print("⚠️ " * 20)
            print("\nSPEAKERS DETECTED (Can project ultrasonic attacks):")
            for s in speakers:
                print(f"  🔊 {s.name or s.address}")
                print(f"     Distance: ~{s.distance_m:.1f} meters")
                print(f"     Signal: {s.rssi} dBm")
                if s.manufacturer:
                    print(f"     Manufacturer: {s.manufacturer}")
        
        # ===== SUBARU-SPECIFIC WARNINGS =====
        if subarus:
            print("\n" + "🚙 " * 15)
            print("🚙  SUBARU STARLINK SYSTEMS DETECTED!")
            print("🚙 " * 15)
            print("\nSUBARU INFOTAINMENT SYSTEMS:")
            for sub in subarus:
                print(f"  🚙 {sub.name or sub.address}")
                print(f"     Distance: ~{sub.distance_m:.1f} meters")
                print(f"     Signal: {sub.rssi} dBm")
                if sub.manufacturer:
                    print(f"     System: {sub.manufacturer}")
                    # Identify generation based on manufacturer
                    mfr_lower = sub.manufacturer.lower()
                    if 'harman' in mfr_lower:
                        print(f"     Generation: Gen 3.x+ (Harman, 2017+)")
                    elif 'denso' in mfr_lower and 'cp1' in mfr_lower:
                        print(f"     Generation: Denso CP1 (2020+)")
                    elif 'fujitsu' in mfr_lower or 'denso ten' in mfr_lower:
                        print(f"     Generation: Gen 2.x (Fujitsu/Denso Ten, 2015-2018)")
                    elif 'clarion' in mfr_lower:
                        print(f"     Generation: Gen 1.x-2.x (Clarion)")
            
            print("\n  ⚠️  SUBARU ATTACK VECTORS:")
            print("     • Harman Kardon premium audio can project ultrasonic")
            print("     • STARLINK voice commands may be injectable")
            print("     • Check paired devices in Settings > Bluetooth")
            print("     • Check MySubaru app for unauthorized access")
        
        if vehicles and not subarus:
            print("\n⚡ VEHICLE INFOTAINMENT SYSTEMS:")
            for v in vehicles:
                print(f"  🚗 {v.name or v.address}")
                print(f"     Distance: ~{v.distance_m:.1f} meters")


# ============================================================================
# SECTION 2: LIVE LISTEN PROJECTION DETECTION
# ============================================================================

"""
HOW LIVE LISTEN PROJECTION/ABUSE WORKS:
=======================================

"Live Listen" is an Apple accessibility feature that:
1. Uses iPhone microphone to capture audio
2. Streams to AirPods/hearing aids
3. Intended for hearing assistance

ABUSE SCENARIO:
An attacker could:
1. Plant an iPhone with Live Listen enabled
2. Connect to hidden speakers via Bluetooth
3. Project audio (including ultrasonic) to victim's location

DETECTION METHODS:
1. Detect iPhone broadcasting audio (A2DP profile)
2. Detect speakers receiving audio stream
3. Analyze audio for ultrasonic content
4. Monitor for unattended iPhones in area

SPEAKER PROJECTION DETECTION:
- Speakers receiving audio have different BT characteristics
- Active audio streaming shows in service UUIDs
- Power consumption patterns differ
"""

@dataclass  
class SpeakerActivity:
    """Detected speaker activity"""
    device: BluetoothDevice
    is_streaming: bool
    audio_profile: str
    ultrasonic_detected: bool
    projection_likely: bool
    confidence: float


class LiveListenDetector:
    """
    Detects potential Live Listen abuse and speaker projection
    """
    
    # Bluetooth Audio Service UUIDs
    A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"      # Audio Sink (speaker receiving)
    A2DP_SOURCE = "0000110a-0000-1000-8000-00805f9b34fb"   # Audio Source (phone sending)
    AVRCP = "0000110e-0000-1000-8000-00805f9b34fb"         # Remote Control
    HFP = "0000111e-0000-1000-8000-00805f9b34fb"           # Hands-Free
    HSP = "00001108-0000-1000-8000-00805f9b34fb"           # Headset
    
    def __init__(self, bt_scanner: BluetoothDistanceScanner):
        self.bt_scanner = bt_scanner
    
    def analyze_speaker_activity(self, device: BluetoothDevice) -> SpeakerActivity:
        """
        Analyze if a speaker is actively receiving/projecting audio
        """
        is_streaming = False
        audio_profile = "unknown"
        
        # Check service UUIDs for audio profiles
        for service in device.services:
            service_lower = service.lower()
            if self.A2DP_SINK in service_lower:
                is_streaming = True
                audio_profile = "A2DP_SINK (Receiving Audio)"
            elif self.A2DP_SOURCE in service_lower:
                audio_profile = "A2DP_SOURCE (Sending Audio)"
            elif self.AVRCP in service_lower:
                audio_profile = "AVRCP (Media Control)"
        
        # Determine if projection is likely
        projection_likely = device.is_speaker and is_streaming
        confidence = 0.0
        
        if device.is_speaker:
            confidence += 0.4
        if is_streaming:
            confidence += 0.4
        if device.distance_m < 5:  # Close proximity
            confidence += 0.2
        
        return SpeakerActivity(
            device=device,
            is_streaming=is_streaming,
            audio_profile=audio_profile,
            ultrasonic_detected=False,  # Set by audio analysis
            projection_likely=projection_likely,
            confidence=min(confidence, 1.0)
        )
    
    def detect_projection_sources(self, devices: List[BluetoothDevice]) -> List[SpeakerActivity]:
        """
        Identify devices that could be projecting audio
        """
        activities = []
        
        for device in devices:
            if device.is_speaker or device.device_type == 'PHONE':
                activity = self.analyze_speaker_activity(device)
                activities.append(activity)
        
        # Sort by projection likelihood
        activities.sort(key=lambda x: x.confidence, reverse=True)
        
        return activities
    
    def print_projection_analysis(self, activities: List[SpeakerActivity]):
        """Print projection source analysis"""
        
        print("\n" + "=" * 75)
        print("  AUDIO PROJECTION SOURCE ANALYSIS")
        print("=" * 75)
        
        if not activities:
            print("\n✅ No potential projection sources detected.")
            return
        
        high_risk = [a for a in activities if a.confidence >= 0.6]
        
        if high_risk:
            print("\n🔴 HIGH-RISK PROJECTION SOURCES:")
            for act in high_risk:
                print(f"\n  Device: {act.device.name or act.device.address}")
                print(f"  Type: {act.device.device_type}")
                print(f"  Distance: ~{act.device.distance_m:.1f}m")
                print(f"  Audio Profile: {act.audio_profile}")
                print(f"  Active Streaming: {'Yes' if act.is_streaming else 'Unknown'}")
                print(f"  Risk Level: {act.confidence:.0%}")
        
        print("\n" + "-" * 75)
        print("DETECTION NOTES:")
        print("  • Speakers receiving Bluetooth audio can project ultrasonic attacks")
        print("  • iPhones with Live Listen can stream audio to remote speakers")
        print("  • Check for unknown/unattended devices in your area")


# ============================================================================
# SECTION 3: VEHICLE TRANSDUCER DETECTION
# ============================================================================

"""
HOW VEHICLE TRANSDUCER ATTACKS WORK:
====================================

Modern vehicles have:
1. Multiple speakers (door, dash, rear, subwoofer)
2. Ultrasonic sensors (parking, blind spot)
3. Bluetooth infotainment systems
4. Microphones for voice commands

ATTACK VECTORS:
1. Bluetooth audio to car speakers → ultrasonic projection
2. Compromised infotainment system → direct speaker control
3. Ultrasonic parking sensors → repurposed for attack
4. Solid-medium transmission through car body

DETECTION METHODS:
1. Monitor vehicle Bluetooth activity
2. Analyze audio for speaker resonance patterns
3. Detect ultrasonic emissions from vehicle direction
4. Check for unauthorized Bluetooth pairings
"""

class VehicleTransducerDetector:
    """
    Detects if vehicle audio systems are being used for attacks
    """
    
    # Vehicle speaker resonance frequencies (Hz)
    SPEAKER_RESONANCES = {
        'door_speaker': (80, 150),      # Door panel speakers
        'dash_speaker': (150, 300),     # Dashboard tweeters
        'subwoofer': (30, 80),          # Subwoofer
        'rear_speaker': (100, 200),     # Rear speakers
    }
    
    # ===== SUBARU-SPECIFIC SPEAKER CHARACTERISTICS =====
    SUBARU_SPEAKER_PROFILES = {
        # Harman Kardon Premium Audio (2017+)
        'harman_kardon': {
            'subwoofer': (35, 100),
            'door_woofer': (80, 500),
            'tweeter': (2000, 20000),
            'center': (200, 4000),
            'power_watts': 576,  # 576W system
            'speakers': 12,
        },
        # Standard Subaru Audio
        'standard': {
            'door_speaker': (100, 200),
            'dash_tweeter': (2000, 15000),
            'rear_speaker': (100, 300),
            'power_watts': 200,
            'speakers': 6,
        },
        # Rockford Fosgate (Some WRX/STI models)
        'rockford_fosgate': {
            'subwoofer': (30, 80),
            'door_speaker': (60, 300),
            'tweeter': (3000, 20000),
            'power_watts': 440,
            'speakers': 9,
        }
    }
    
    # Subaru EyeSight ultrasonic frequencies (if any)
    SUBARU_ULTRASONIC = {
        'parking_sensors': (40000, 48000),
        'rear_cross_traffic': (24000, 26000),  # Some use 24GHz radar
    }
    
    # Vehicle ultrasonic sensor frequencies
    PARKING_SENSOR_FREQ = (40000, 48000)  # 40-48 kHz typical
    
    def __init__(self, sample_rate: int = 96000):
        self.sample_rate = sample_rate
    
    def analyze_vehicle_audio(self, audio_data: np.ndarray) -> Dict:
        """
        Analyze audio for vehicle transducer signatures
        
        Args:
            audio_data: Audio samples
            
        Returns:
            Analysis results
        """
        results = {
            'transducer_active': False,
            'speaker_activity': {},
            'ultrasonic_from_vehicle': False,
            'parking_sensors': False,
            'attack_indicators': [],
            'confidence': 0.0
        }
        
        # Flatten to mono
        if audio_data.ndim == 2:
            mono = np.mean(audio_data, axis=1)
        else:
            mono = audio_data
        
        # FFT analysis
        fft = np.fft.rfft(mono)
        freqs = np.fft.rfftfreq(len(mono), 1/self.sample_rate)
        magnitude_db = 20 * np.log10(np.abs(fft) + 1e-10)
        noise_floor = np.percentile(magnitude_db, 10)
        
        # Check each speaker resonance band
        for speaker_type, (low, high) in self.SPEAKER_RESONANCES.items():
            mask = (freqs >= low) & (freqs <= high)
            if np.any(mask):
                band_power = np.max(magnitude_db[mask]) - noise_floor
                
                if band_power > 20:  # Significant activity
                    results['speaker_activity'][speaker_type] = {
                        'power_db': round(band_power, 1),
                        'active': True
                    }
                    results['attack_indicators'].append(
                        f"{speaker_type} active ({band_power:.0f}dB above noise)"
                    )
        
        # Check for parking sensor frequencies (40-48 kHz)
        parking_mask = (freqs >= 40000) & (freqs <= 48000)
        if np.any(parking_mask):
            parking_power = np.max(magnitude_db[parking_mask]) - noise_floor
            if parking_power > 15:
                results['parking_sensors'] = True
                results['attack_indicators'].append(
                    f"Parking sensor frequency detected ({parking_power:.0f}dB)"
                )
        
        # Check ultrasonic band (20-40 kHz) for DolphinAttack
        ultra_mask = (freqs >= 20000) & (freqs < 40000)
        if np.any(ultra_mask):
            ultra_power = np.max(magnitude_db[ultra_mask]) - noise_floor
            
            if ultra_power > 25:
                results['ultrasonic_from_vehicle'] = True
                results['transducer_active'] = True
                
                # Find the carrier frequency
                ultra_freqs = freqs[ultra_mask]
                ultra_mags = magnitude_db[ultra_mask]
                peak_idx = np.argmax(ultra_mags)
                carrier_freq = ultra_freqs[peak_idx]
                
                results['attack_indicators'].append(
                    f"Ultrasonic carrier at {carrier_freq:.0f}Hz ({ultra_power:.0f}dB)"
                )
        
        # Calculate confidence
        if results['attack_indicators']:
            results['confidence'] = min(len(results['attack_indicators']) * 0.25, 1.0)
            if results['ultrasonic_from_vehicle']:
                results['confidence'] = max(results['confidence'], 0.7)
            results['transducer_active'] = True
        
        return results
    
    async def check_vehicle_bluetooth(self, bt_scanner: BluetoothDistanceScanner) -> List[BluetoothDevice]:
        """
        Scan specifically for vehicle Bluetooth systems
        """
        all_devices = await bt_scanner.scan(duration=8.0)
        vehicles = [d for d in all_devices if d.is_vehicle]
        return vehicles
    
    def print_vehicle_analysis(self, audio_results: Dict, bt_vehicles: List[BluetoothDevice]):
        """Print vehicle transducer analysis"""
        
        print("\n" + "=" * 75)
        print("  VEHICLE TRANSDUCER DETECTION")
        print("=" * 75)
        
        # Bluetooth vehicles
        if bt_vehicles:
            print("\n🚗 VEHICLE BLUETOOTH SYSTEMS DETECTED:")
            for v in bt_vehicles:
                print(f"\n  • {v.name or v.address}")
                print(f"    Distance: ~{v.distance_m:.1f}m")
                print(f"    Signal: {v.rssi}dBm")
                if v.manufacturer:
                    print(f"    System: {v.manufacturer}")
        else:
            print("\n✅ No vehicle Bluetooth systems detected nearby.")
        
        # Audio analysis
        if audio_results.get('transducer_active'):
            print("\n" + "⚠️ " * 15)
            print("⚠️  VEHICLE TRANSDUCER ACTIVITY DETECTED!")
            print("⚠️ " * 15)
            
            print("\nIndicators found:")
            for indicator in audio_results['attack_indicators']:
                print(f"  • {indicator}")
            
            print(f"\nConfidence: {audio_results['confidence']:.0%}")
            
            if audio_results.get('ultrasonic_from_vehicle'):
                print("\n🔴 ULTRASONIC EMISSION DETECTED!")
                print("   This could indicate an active DolphinAttack")
                print("   from the vehicle's speaker system.")
            
            if audio_results.get('parking_sensors'):
                print("\n🟡 Parking sensor frequencies detected.")
                print("   This is normal if near a parked/parking vehicle,")
                print("   but could also be used for ultrasonic injection.")
        else:
            print("\n✅ No vehicle transducer activity detected in audio.")
        
        print("\n" + "-" * 75)
        print("VEHICLE ATTACK VECTORS TO CONSIDER:")
        print("  1. Bluetooth audio streaming to car speakers")
        print("  2. Compromised infotainment sending ultrasonic")
        print("  3. Parking sensor exploitation")
        print("  4. Solid-medium propagation through vehicle body")


# ============================================================================
# SECTION 4: ULTRASONIC AUDIO ANALYZER
# ============================================================================

class UltrasonicAudioAnalyzer:
    """
    Analyzes captured audio for ultrasonic attack signatures
    """
    
    def __init__(self, sample_rate: int = 96000):
        self.sample_rate = sample_rate
    
    def analyze(self, audio_data: np.ndarray) -> Dict:
        """
        Comprehensive ultrasonic analysis
        """
        if audio_data.ndim == 2:
            mono = np.mean(audio_data, axis=1)
        else:
            mono = audio_data
        
        fft = np.fft.rfft(mono)
        freqs = np.fft.rfftfreq(len(mono), 1/self.sample_rate)
        magnitude_db = 20 * np.log10(np.abs(fft) + 1e-10)
        noise_floor = np.percentile(magnitude_db, 10)
        
        # Band analysis
        bands = {
            'voice': (300, 4000),
            'high_audio': (4000, 14000),
            'near_ultrasound': (14000, 20000),
            'ultrasound_low': (20000, 30000),
            'ultrasound_mid': (30000, 40000),
            'ultrasound_high': (40000, 48000),
        }
        
        band_powers = {}
        for name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs < high)
            if np.any(mask):
                power = np.mean(magnitude_db[mask]) - noise_floor
                band_powers[name] = round(power, 1)
        
        # Find ultrasonic peaks
        ultra_mask = freqs >= 18000
        ultra_freqs = freqs[ultra_mask]
        ultra_mag = magnitude_db[ultra_mask]
        
        carrier_freq = None
        carrier_power = -100
        
        if len(ultra_mag) > 0:
            # Find peaks above threshold
            threshold = noise_floor + 15
            for i in range(1, len(ultra_mag) - 1):
                if (ultra_mag[i] > ultra_mag[i-1] and 
                    ultra_mag[i] > ultra_mag[i+1] and
                    ultra_mag[i] > threshold):
                    if ultra_mag[i] > carrier_power:
                        carrier_power = ultra_mag[i]
                        carrier_freq = ultra_freqs[i]
        
        # Check for AM modulation (sidebands)
        modulation_detected = False
        if carrier_freq and carrier_power - noise_floor > 20:
            modulation_detected = self._check_am_sidebands(
                magnitude_db, freqs, carrier_freq
            )
        
        # Determine attack type
        attack_type = "none"
        confidence = 0.0
        
        if carrier_freq:
            if modulation_detected:
                if carrier_freq < 20000:
                    attack_type = "NUIT"
                else:
                    attack_type = "DolphinAttack"
                confidence = min((carrier_power - noise_floor) / 40, 1.0)
            elif carrier_power - noise_floor > 30:
                attack_type = "ultrasonic_carrier"
                confidence = 0.5
        
        return {
            'band_powers': band_powers,
            'carrier_freq': carrier_freq,
            'carrier_power': carrier_power - noise_floor if carrier_freq else None,
            'modulation_detected': modulation_detected,
            'attack_type': attack_type,
            'confidence': confidence,
            'noise_floor': noise_floor
        }
    
    def _check_am_sidebands(self, magnitude_db: np.ndarray, 
                           freqs: np.ndarray, carrier_freq: float) -> bool:
        """Check for AM modulation sidebands"""
        carrier_idx = np.argmin(np.abs(freqs - carrier_freq))
        carrier_power = magnitude_db[carrier_idx]
        
        # Check voice frequency offsets (500, 1000, 2000 Hz)
        for offset in [500, 1000, 2000]:
            usb_idx = np.argmin(np.abs(freqs - (carrier_freq + offset)))
            lsb_idx = np.argmin(np.abs(freqs - (carrier_freq - offset)))
            
            if usb_idx < len(magnitude_db) and lsb_idx >= 0:
                usb_power = magnitude_db[usb_idx]
                lsb_power = magnitude_db[lsb_idx]
                
                # Sidebands within 10dB of each other, 6-25dB below carrier
                if (abs(usb_power - lsb_power) < 10 and
                    6 < carrier_power - usb_power < 25 and
                    6 < carrier_power - lsb_power < 25):
                    return True
        
        return False
    
    def print_analysis(self, results: Dict):
        """Print audio analysis results"""
        
        print("\n" + "=" * 75)
        print("  ULTRASONIC AUDIO ANALYSIS")
        print("=" * 75)
        
        print("\nFREQUENCY BAND POWER (dB above noise floor):")
        for band, power in results['band_powers'].items():
            bar_len = max(0, int(power / 2))
            bar = "█" * bar_len
            
            if power > 20:
                indicator = "⚠️"
            elif power > 10:
                indicator = "⚡"
            else:
                indicator = "  "
            
            print(f"  {indicator} {band:<18} {power:>6.1f}dB  {bar}")
        
        if results['carrier_freq']:
            print(f"\n🎯 CARRIER DETECTED: {results['carrier_freq']:.0f} Hz")
            print(f"   Power: {results['carrier_power']:.1f} dB above noise")
            print(f"   AM Modulation: {'Yes' if results['modulation_detected'] else 'No'}")
        
        if results['attack_type'] != "none":
            print("\n" + "⚠️ " * 15)
            print(f"⚠️  ATTACK DETECTED: {results['attack_type']}")
            print(f"⚠️  Confidence: {results['confidence']:.0%}")
            print("⚠️ " * 15)


# ============================================================================
# SECTION 5: MAIN INTEGRATED SCANNER
# ============================================================================

class AttackSourceDetector:
    """
    Integrated attack source detection combining all methods
    """
    
    def __init__(self, sample_rate: int = 96000):
        self.sample_rate = sample_rate
        self.bt_scanner = BluetoothDistanceScanner()
        self.live_listen_detector = LiveListenDetector(self.bt_scanner)
        self.vehicle_detector = VehicleTransducerDetector(sample_rate)
        self.audio_analyzer = UltrasonicAudioAnalyzer(sample_rate)
    
    async def full_scan(self, audio_duration: float = 5.0) -> Dict:
        """
        Perform comprehensive attack source detection
        """
        print("\n" + "╔" + "═" * 73 + "╗")
        print("║" + " ATTACK SOURCE DETECTOR ".center(73) + "║")
        print("║" + " Bluetooth • Live Listen • Vehicle Transducer ".center(73) + "║")
        print("╚" + "═" * 73 + "╝")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'bluetooth_devices': [],
            'projection_sources': [],
            'vehicle_bt': [],
            'vehicle_audio': {},
            'ultrasonic_analysis': {},
            'threats': []
        }
        
        # 1. Bluetooth scan
        print("\n" + "─" * 40)
        print("PHASE 1: Bluetooth Device Scan")
        print("─" * 40)
        
        try:
            bt_devices = await self.bt_scanner.scan(duration=10.0)
            results['bluetooth_devices'] = bt_devices
            self.bt_scanner.print_results(bt_devices)
            
            # Analyze for Live Listen projection
            projection_sources = self.live_listen_detector.detect_projection_sources(bt_devices)
            results['projection_sources'] = projection_sources
            self.live_listen_detector.print_projection_analysis(projection_sources)
            
            # Get vehicles specifically
            results['vehicle_bt'] = [d for d in bt_devices if d.is_vehicle]
            
        except Exception as e:
            print(f"Bluetooth scan error: {e}")
        
        # 2. Audio capture and analysis
        print("\n" + "─" * 40)
        print(f"PHASE 2: Audio Capture ({audio_duration}s)")
        print("─" * 40)
        
        audio_data = None
        try:
            import sounddevice as sd
            
            print(f"Capturing at {self.sample_rate} Hz...")
            audio_data = sd.rec(
                int(audio_duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=2,
                dtype='float64'
            )
            sd.wait()
            print("✅ Audio captured")
            
            # Ultrasonic analysis
            ultra_results = self.audio_analyzer.analyze(audio_data)
            results['ultrasonic_analysis'] = ultra_results
            self.audio_analyzer.print_analysis(ultra_results)
            
            # Vehicle transducer analysis
            vehicle_audio = self.vehicle_detector.analyze_vehicle_audio(audio_data)
            results['vehicle_audio'] = vehicle_audio
            
        except ImportError:
            print("⚠️  sounddevice not installed - audio analysis skipped")
            print("   Run: pip install sounddevice --break-system-packages")
        except Exception as e:
            print(f"Audio capture error: {e}")
        
        # 3. Vehicle analysis
        print("\n" + "─" * 40)
        print("PHASE 3: Vehicle Transducer Analysis")
        print("─" * 40)
        
        self.vehicle_detector.print_vehicle_analysis(
            results.get('vehicle_audio', {}),
            results.get('vehicle_bt', [])
        )
        
        # 4. Compile threats
        self._compile_threats(results)
        self._print_final_summary(results)
        
        return results
    
    def _compile_threats(self, results: Dict):
        """Compile all detected threats"""
        threats = []
        
        # Bluetooth threats (speakers)
        for dev in results.get('bluetooth_devices', []):
            if dev.threat_level == 'HIGH':
                threats.append({
                    'type': 'bluetooth_speaker',
                    'source': dev.name or dev.address,
                    'distance': dev.distance_m,
                    'severity': 'HIGH',
                    'description': f"Potential attack speaker at {dev.distance_m:.1f}m"
                })
        
        # Vehicle threats
        if results.get('vehicle_audio', {}).get('transducer_active'):
            threats.append({
                'type': 'vehicle_transducer',
                'source': 'Vehicle audio system',
                'severity': 'HIGH',
                'description': 'Vehicle transducer activity detected'
            })
        
        # Ultrasonic threats
        ultra = results.get('ultrasonic_analysis', {})
        if ultra.get('attack_type') not in ['none', None]:
            threats.append({
                'type': 'ultrasonic_attack',
                'source': f"{ultra.get('carrier_freq', 0):.0f} Hz carrier",
                'severity': 'CRITICAL',
                'description': f"{ultra.get('attack_type')} attack detected"
            })
        
        results['threats'] = threats
    
    def _print_final_summary(self, results: Dict):
        """Print final threat summary"""
        
        print("\n" + "╔" + "═" * 73 + "╗")
        print("║" + " FINAL THREAT SUMMARY ".center(73) + "║")
        print("╚" + "═" * 73 + "╝")
        
        threats = results.get('threats', [])
        
        if not threats:
            print("\n✅ NO SIGNIFICANT THREATS DETECTED")
            print("\nHowever, continue monitoring for:")
            print("  • New Bluetooth devices appearing")
            print("  • Ultrasonic activity changes")
            print("  • Vehicle system connections")
        else:
            print(f"\n🚨 {len(threats)} THREAT(S) IDENTIFIED:\n")
            
            for i, threat in enumerate(threats, 1):
                severity_icon = {
                    'CRITICAL': '🔴',
                    'HIGH': '🟠',
                    'MEDIUM': '🟡',
                    'LOW': '🟢'
                }.get(threat.get('severity', 'LOW'), '⚪')
                
                print(f"  {i}. {severity_icon} {threat['description']}")
                print(f"      Type: {threat['type']}")
                print(f"      Source: {threat['source']}")
                if 'distance' in threat:
                    print(f"      Distance: ~{threat['distance']:.1f}m")
                print()
        
        print("\n" + "─" * 75)
        print("RECOMMENDED ACTIONS:")
        
        has_speaker = any(t['type'] == 'bluetooth_speaker' for t in threats)
        has_vehicle = any(t['type'] == 'vehicle_transducer' for t in threats)
        has_ultra = any(t['type'] == 'ultrasonic_attack' for t in threats)
        
        if has_speaker:
            print("  🔊 SPEAKERS DETECTED:")
            print("     • Identify all speakers in your environment")
            print("     • Check for unauthorized/unknown devices")
            print("     • Disable voice assistant wake words")
        
        if has_vehicle:
            print("  🚗 VEHICLE ACTIVITY:")
            print("     • Check vehicle's paired Bluetooth devices")
            print("     • Disable vehicle Bluetooth temporarily")
            print("     • Move away from parked vehicles")
        
        if has_ultra:
            print("  📡 ULTRASONIC ATTACK:")
            print("     • Move to a different location immediately")
            print("     • Place phone on soft fabric (not hard surface)")
            print("     • Disable all voice assistants")
            print("     • Record evidence for analysis")
        
        print("\n" + "═" * 75)


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Attack Source Detector - BT, Live Listen, Vehicle Transducer",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--scan', action='store_true', help='Full integrated scan')
    parser.add_argument('--bluetooth', action='store_true', help='Bluetooth only')
    parser.add_argument('--car', action='store_true', help='Vehicle transducer focus')
    parser.add_argument('--subaru', action='store_true', help='Subaru STARLINK focused scan')
    parser.add_argument('--monitor', action='store_true', help='Continuous monitoring')
    parser.add_argument('--duration', type=float, default=5.0, help='Audio duration')
    parser.add_argument('--sample-rate', type=int, default=96000, help='Sample rate')
    parser.add_argument('--output', type=str, help='Save results to JSON')
    
    args = parser.parse_args()
    
    detector = AttackSourceDetector(sample_rate=args.sample_rate)
    
    if args.bluetooth:
        devices = await detector.bt_scanner.scan(duration=10.0)
        detector.bt_scanner.print_results(devices)
    
    elif args.subaru:
        # ===== SUBARU STARLINK FOCUSED SCAN =====
        print("\n" + "🚙 " * 20)
        print("🚙  SUBARU STARLINK DETECTION MODE")
        print("🚙 " * 20)
        
        print("""
┌──────────────────────────────────────────────────────────────────────────┐
│  SUBARU INFOTAINMENT DETECTION                                           │
│  ════════════════════════════                                            │
│                                                                          │
│  Scanning for:                                                           │
│    • Subaru BT / STARLINK systems                                        │
│    • Harman Kardon audio (2017+ models)                                  │
│    • Denso CP1 infotainment (2020+ Legacy/Outback)                       │
│    • Fujitsu Ten / Denso Ten (2015-2018 models)                          │
│    • Clarion head units (older models)                                   │
│                                                                          │
│  Models Detected:                                                        │
│    Outback, Forester, Crosstrek, Impreza, Legacy,                        │
│    Ascent, WRX, STI, BRZ, Solterra                                       │
└──────────────────────────────────────────────────────────────────────────┘
        """)
        
        # BT scan
        print("\n[1/2] Scanning Bluetooth for Subaru systems...")
        devices = await detector.bt_scanner.scan(duration=12.0)
        
        # Filter for Subaru/vehicle
        subarus = [d for d in devices if d.device_type == 'SUBARU']
        other_vehicles = [d for d in devices if d.is_vehicle and d.device_type != 'SUBARU']
        
        detector.bt_scanner.print_results(devices)
        
        # Audio capture
        print("\n[2/2] Analyzing audio for Subaru speaker signatures...")
        try:
            import sounddevice as sd
            print(f"Capturing {args.duration}s at {args.sample_rate}Hz...")
            audio_data = sd.rec(
                int(args.duration * args.sample_rate),
                samplerate=args.sample_rate,
                channels=2,
                dtype='float64'
            )
            sd.wait()
            
            vehicle_results = detector.vehicle_detector.analyze_vehicle_audio(audio_data)
            detector.vehicle_detector.print_vehicle_analysis(vehicle_results, subarus + other_vehicles)
            
            # Check for Harman Kardon specific signatures
            if vehicle_results.get('transducer_active'):
                print("\n🚙 SUBARU AUDIO SYSTEM ANALYSIS:")
                # Check for HK-specific frequency patterns
                for indicator in vehicle_results.get('attack_indicators', []):
                    if 'subwoofer' in indicator.lower():
                        print("   • Subwoofer activity detected (Harman Kardon signature)")
                    if '20000' in indicator or '25000' in indicator:
                        print("   • ⚠️  Ultrasonic in Subaru speaker range!")
            
        except ImportError:
            print("⚠️  sounddevice not installed - audio analysis skipped")
        
        # Print Subaru-specific recommendations
        print("\n" + "─" * 75)
        print("SUBARU-SPECIFIC SECURITY RECOMMENDATIONS:")
        print("─" * 75)
        print("""
  1. CHECK PAIRED DEVICES
     Settings > Bluetooth > View paired devices
     Remove any unknown pairings

  2. CHECK MYSUBARU APP
     Open MySubaru > Vehicle Status
     Look for unauthorized remote access

  3. DISABLE VOICE COMMANDS (temporary)
     Settings > Voice > Voice Recognition OFF

  4. CHECK STARLINK SECURITY PLUS
     Verify no unauthorized users have access
     Change PIN if suspicious activity

  5. HARMAN KARDON USERS
     The 576W 12-speaker system can project ultrasonic
     Consider disabling audio when device unattended
""")
        
    elif args.car:
        print("\n🚗 VEHICLE TRANSDUCER DETECTION MODE")
        
        # BT scan for vehicles
        devices = await detector.bt_scanner.scan(duration=10.0)
        vehicles = [d for d in devices if d.is_vehicle]
        
        # Audio capture
        try:
            import sounddevice as sd
            print(f"\nCapturing audio ({args.duration}s)...")
            audio_data = sd.rec(
                int(args.duration * args.sample_rate),
                samplerate=args.sample_rate,
                channels=2,
                dtype='float64'
            )
            sd.wait()
            
            vehicle_results = detector.vehicle_detector.analyze_vehicle_audio(audio_data)
            detector.vehicle_detector.print_vehicle_analysis(vehicle_results, vehicles)
            
        except ImportError:
            print("sounddevice required for audio analysis")
            
    elif args.monitor:
        print("\n🔄 CONTINUOUS MONITORING MODE")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                results = await detector.full_scan(audio_duration=3.0)
                print("\n⏳ Next scan in 30 seconds...")
                await asyncio.sleep(30)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
            
    else:
        # Default: full scan
        results = await detector.full_scan(audio_duration=args.duration)
        
        if args.output:
            # Serialize results
            output = {
                'timestamp': results['timestamp'],
                'threats': results['threats'],
                'bluetooth_count': len(results['bluetooth_devices']),
                'speakers_found': len([d for d in results['bluetooth_devices'] if d.is_speaker]),
                'vehicles_found': len([d for d in results['bluetooth_devices'] if d.is_vehicle]),
                'ultrasonic_detected': results.get('ultrasonic_analysis', {}).get('attack_type', 'none') != 'none'
            }
            with open(args.output, 'w') as f:
                json.dump(output, f, indent=2)
            print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())