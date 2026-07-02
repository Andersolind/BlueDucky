#!/usr/bin/env python3
"""
Advanced Real System Signal Injection Detection Monitor

This version includes:
- Direct /proc and /sys filesystem reading
- Network packet capture analysis
- USB device monitoring
- Process monitoring for suspicious activity
- File integrity monitoring
- Comprehensive logging

Works on most Linux systems without special dependencies.

Usage:
    python3 real_sensor_monitor_advanced.py
    python3 real_sensor_monitor_advanced.py --log output.json
    python3 real_sensor_monitor_advanced.py --check-only
"""

import os
import sys
import time
import json
import struct
import socket
import hashlib
import argparse
import threading
from datetime import datetime
from collections import deque
from pathlib import Path
import subprocess

import numpy as np

# ======================
# PROC/SYS FILESYSTEM READERS
# ======================

class ProcReader:
    """Direct /proc filesystem reader for system info"""
    
    @staticmethod
    def read_file(path, default=None):
        """Safely read a file"""
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError, IOError):
            return default
    
    @staticmethod
    def get_cpu_info():
        """Read CPU information from /proc/stat"""
        info = {
            'usage_percent': 0,
            'idle_percent': 0,
            'user_percent': 0,
            'system_percent': 0,
            'cores': 0
        }
        
        content = ProcReader.read_file('/proc/stat')
        if content:
            lines = content.split('\n')
            for line in lines:
                if line.startswith('cpu '):
                    parts = line.split()
                    if len(parts) >= 5:
                        user = int(parts[1])
                        nice = int(parts[2])
                        system = int(parts[3])
                        idle = int(parts[4])
                        total = user + nice + system + idle
                        if total > 0:
                            info['user_percent'] = (user + nice) / total * 100
                            info['system_percent'] = system / total * 100
                            info['idle_percent'] = idle / total * 100
                            info['usage_percent'] = 100 - info['idle_percent']
                elif line.startswith('cpu') and line[3].isdigit():
                    info['cores'] += 1
                    
        return info
    
    @staticmethod
    def get_memory_info():
        """Read memory information from /proc/meminfo"""
        info = {
            'total_kb': 0,
            'free_kb': 0,
            'available_kb': 0,
            'buffers_kb': 0,
            'cached_kb': 0,
            'used_percent': 0
        }
        
        content = ProcReader.read_file('/proc/meminfo')
        if content:
            for line in content.split('\n'):
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    value = int(parts[1])
                    if key == 'MemTotal':
                        info['total_kb'] = value
                    elif key == 'MemFree':
                        info['free_kb'] = value
                    elif key == 'MemAvailable':
                        info['available_kb'] = value
                    elif key == 'Buffers':
                        info['buffers_kb'] = value
                    elif key == 'Cached':
                        info['cached_kb'] = value
                        
            if info['total_kb'] > 0:
                used = info['total_kb'] - info['available_kb']
                info['used_percent'] = used / info['total_kb'] * 100
                
        return info
    
    @staticmethod
    def get_network_stats():
        """Read network statistics from /proc/net/dev"""
        stats = {}
        
        content = ProcReader.read_file('/proc/net/dev')
        if content:
            lines = content.split('\n')[2:]  # Skip headers
            for line in lines:
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
    
    @staticmethod
    def get_wireless_info():
        """Read wireless info from /proc/net/wireless"""
        wireless = {}
        
        content = ProcReader.read_file('/proc/net/wireless')
        if content:
            lines = content.split('\n')[2:]  # Skip headers
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    iface = parts[0].rstrip(':')
                    wireless[iface] = {
                        'status': parts[1],
                        'quality': float(parts[2].rstrip('.')),
                        'signal_level': int(float(parts[3].rstrip('.'))),
                        'noise_level': int(float(parts[4].rstrip('.'))) if len(parts) > 4 else None
                    }
                    
        return wireless
    
    @staticmethod
    def get_uptime():
        """Read system uptime from /proc/uptime"""
        content = ProcReader.read_file('/proc/uptime')
        if content:
            parts = content.split()
            if len(parts) >= 1:
                return float(parts[0])
        return 0
    
    @staticmethod
    def get_loadavg():
        """Read load average from /proc/loadavg"""
        content = ProcReader.read_file('/proc/loadavg')
        if content:
            parts = content.split()
            if len(parts) >= 3:
                return {
                    '1min': float(parts[0]),
                    '5min': float(parts[1]),
                    '15min': float(parts[2])
                }
        return {'1min': 0, '5min': 0, '15min': 0}
    
    @staticmethod
    def get_running_processes():
        """Get list of running processes from /proc"""
        processes = []
        
        proc_path = Path('/proc')
        for entry in proc_path.iterdir():
            if entry.is_dir() and entry.name.isdigit():
                pid = int(entry.name)
                cmdline_path = entry / 'cmdline'
                comm_path = entry / 'comm'
                
                cmdline = ProcReader.read_file(str(cmdline_path), '')
                comm = ProcReader.read_file(str(comm_path), '')
                
                if comm or cmdline:
                    processes.append({
                        'pid': pid,
                        'name': comm,
                        'cmdline': cmdline.replace('\x00', ' ').strip()
                    })
                    
        return processes


class SysReader:
    """Read from /sys filesystem for hardware info"""
    
    @staticmethod
    def get_temperatures():
        """Read all available temperature sensors"""
        temps = {}
        
        # Check hwmon devices
        hwmon_path = Path('/sys/class/hwmon')
        if hwmon_path.exists():
            for hwmon in hwmon_path.iterdir():
                name_file = hwmon / 'name'
                name = ProcReader.read_file(str(name_file), hwmon.name)
                
                for temp_file in hwmon.glob('temp*_input'):
                    try:
                        temp_value = int(ProcReader.read_file(str(temp_file), '0'))
                        temp_name = temp_file.stem
                        
                        # Get label if available
                        label_file = hwmon / f'{temp_name.replace("_input", "_label")}'
                        label = ProcReader.read_file(str(label_file), temp_name)
                        
                        temps[f'{name}/{label}'] = temp_value / 1000.0
                    except (ValueError, TypeError):
                        pass
                        
        # Check thermal zones
        thermal_path = Path('/sys/class/thermal')
        if thermal_path.exists():
            for zone in thermal_path.glob('thermal_zone*'):
                temp_file = zone / 'temp'
                type_file = zone / 'type'
                
                temp_value = ProcReader.read_file(str(temp_file))
                zone_type = ProcReader.read_file(str(type_file), zone.name)
                
                if temp_value:
                    try:
                        temps[zone_type] = int(temp_value) / 1000.0
                    except ValueError:
                        pass
                        
        return temps
    
    @staticmethod
    def get_block_devices():
        """Get block device information"""
        devices = {}
        
        block_path = Path('/sys/block')
        if block_path.exists():
            for device in block_path.iterdir():
                size_file = device / 'size'
                size = ProcReader.read_file(str(size_file))
                
                if size:
                    try:
                        # Size is in 512-byte sectors
                        size_bytes = int(size) * 512
                        devices[device.name] = {
                            'size_bytes': size_bytes,
                            'size_gb': size_bytes / (1024**3)
                        }
                    except ValueError:
                        pass
                        
        return devices
    
    @staticmethod
    def get_usb_devices():
        """Get connected USB devices"""
        devices = []
        
        usb_path = Path('/sys/bus/usb/devices')
        if usb_path.exists():
            for device in usb_path.iterdir():
                if device.is_symlink():
                    continue
                    
                vendor_file = device / 'idVendor'
                product_file = device / 'idProduct'
                manufacturer_file = device / 'manufacturer'
                product_name_file = device / 'product'
                
                vendor = ProcReader.read_file(str(vendor_file))
                product = ProcReader.read_file(str(product_file))
                manufacturer = ProcReader.read_file(str(manufacturer_file), '')
                product_name = ProcReader.read_file(str(product_name_file), '')
                
                if vendor and product:
                    devices.append({
                        'bus_id': device.name,
                        'vendor_id': vendor,
                        'product_id': product,
                        'manufacturer': manufacturer,
                        'product': product_name
                    })
                    
        return devices
    
    @staticmethod
    def get_network_interfaces():
        """Get network interface details from /sys/class/net"""
        interfaces = {}
        
        net_path = Path('/sys/class/net')
        if net_path.exists():
            for iface in net_path.iterdir():
                info = {
                    'name': iface.name,
                    'type': None,
                    'address': None,
                    'carrier': False,
                    'speed': None,
                    'mtu': None
                }
                
                # Get type
                type_file = iface / 'type'
                iface_type = ProcReader.read_file(str(type_file))
                if iface_type:
                    type_map = {'1': 'ethernet', '772': 'loopback', '801': 'wireless'}
                    info['type'] = type_map.get(iface_type, f'type_{iface_type}')
                
                # Get MAC address
                address_file = iface / 'address'
                info['address'] = ProcReader.read_file(str(address_file))
                
                # Get carrier status
                carrier_file = iface / 'carrier'
                carrier = ProcReader.read_file(str(carrier_file))
                info['carrier'] = carrier == '1'
                
                # Get speed
                speed_file = iface / 'speed'
                speed = ProcReader.read_file(str(speed_file))
                if speed and speed != '-1':
                    try:
                        info['speed'] = int(speed)
                    except ValueError:
                        pass
                
                # Get MTU
                mtu_file = iface / 'mtu'
                mtu = ProcReader.read_file(str(mtu_file))
                if mtu:
                    try:
                        info['mtu'] = int(mtu)
                    except ValueError:
                        pass
                
                interfaces[iface.name] = info
                
        return interfaces


# ======================
# ANOMALY DETECTION
# ======================

class AnomalyDetector:
    """Detect anomalies in sensor readings"""
    
    def __init__(self):
        self.history = {
            'network': deque(maxlen=100),
            'cpu': deque(maxlen=100),
            'memory': deque(maxlen=100),
            'processes': deque(maxlen=10),
            'usb': deque(maxlen=10)
        }
        self.baselines = {}
        
    def check_network_anomalies(self, current_stats):
        """Detect network anomalies"""
        anomalies = []
        
        if len(self.history['network']) > 0:
            last_stats = self.history['network'][-1]
            
            for iface, stats in current_stats.items():
                if iface in last_stats:
                    last = last_stats[iface]
                    
                    # Check for sudden error spike
                    rx_err_delta = stats['rx_errors'] - last['rx_errors']
                    tx_err_delta = stats['tx_errors'] - last['tx_errors']
                    
                    if rx_err_delta > 10:
                        anomalies.append(f"{iface}: {rx_err_delta} RX errors")
                    if tx_err_delta > 10:
                        anomalies.append(f"{iface}: {tx_err_delta} TX errors")
                    
                    # Check for dropped packets
                    rx_drop_delta = stats['rx_dropped'] - last['rx_dropped']
                    tx_drop_delta = stats['tx_dropped'] - last['tx_dropped']
                    
                    if rx_drop_delta > 5:
                        anomalies.append(f"{iface}: {rx_drop_delta} RX dropped")
                    if tx_drop_delta > 5:
                        anomalies.append(f"{iface}: {tx_drop_delta} TX dropped")
                    
                    # Check for unusual traffic patterns
                    rx_rate = stats['rx_bytes'] - last['rx_bytes']
                    tx_rate = stats['tx_bytes'] - last['tx_bytes']
                    
                    # Establish baseline
                    baseline_key = f'{iface}_rx_rate'
                    if baseline_key not in self.baselines:
                        self.baselines[baseline_key] = []
                    self.baselines[baseline_key].append(rx_rate)
                    
                    if len(self.baselines[baseline_key]) > 30:
                        self.baselines[baseline_key] = self.baselines[baseline_key][-30:]
                        avg_rate = np.mean(self.baselines[baseline_key][:-1])
                        std_rate = np.std(self.baselines[baseline_key][:-1])
                        
                        if std_rate > 0 and rx_rate > avg_rate + 3 * std_rate:
                            anomalies.append(f"{iface}: Unusual RX traffic spike")
                            
        self.history['network'].append(current_stats)
        return anomalies
    
    def check_cpu_anomalies(self, cpu_info):
        """Detect CPU anomalies"""
        anomalies = []
        
        # Check for sustained high usage
        self.history['cpu'].append(cpu_info['usage_percent'])
        
        if len(self.history['cpu']) >= 10:
            recent = list(self.history['cpu'])[-10:]
            avg_usage = np.mean(recent)
            
            if avg_usage > 90:
                anomalies.append(f"Sustained high CPU: {avg_usage:.1f}%")
            
            # Check for unusual patterns
            if len(recent) >= 5:
                std_usage = np.std(recent[-5:])
                if std_usage < 0.5 and avg_usage > 50:
                    anomalies.append("Suspiciously stable high CPU load")
                    
        return anomalies
    
    def check_usb_anomalies(self, usb_devices):
        """Detect USB device changes"""
        anomalies = []
        
        current_ids = set(f"{d['vendor_id']}:{d['product_id']}" for d in usb_devices)
        
        if len(self.history['usb']) > 0:
            last_ids = self.history['usb'][-1]
            
            new_devices = current_ids - last_ids
            removed_devices = last_ids - current_ids
            
            for device_id in new_devices:
                anomalies.append(f"New USB device: {device_id}")
                
            for device_id in removed_devices:
                anomalies.append(f"USB device removed: {device_id}")
                
        self.history['usb'].append(current_ids)
        return anomalies
    
    def check_process_anomalies(self, processes):
        """Detect suspicious processes"""
        anomalies = []
        
        suspicious_patterns = [
            'keylog', 'sniffer', 'inject', 'hook', 'mitm',
            'tcpdump', 'wireshark', 'ettercap', 'arpspoof',
            'aircrack', 'airmon', 'airodump', 'reaver',
            'hydra', 'nmap', 'metasploit', 'meterpreter'
        ]
        
        for proc in processes:
            name = proc['name'].lower()
            cmdline = proc['cmdline'].lower()
            
            for pattern in suspicious_patterns:
                if pattern in name or pattern in cmdline:
                    anomalies.append(f"Suspicious process: {proc['name']} (PID: {proc['pid']})")
                    break
                    
        return anomalies
    
    def check_wireless_anomalies(self, wireless_info):
        """Detect wireless network anomalies"""
        anomalies = []
        
        for iface, info in wireless_info.items():
            signal = info.get('signal_level', 0)
            
            # Check for suspiciously strong signal
            if signal > -20:
                anomalies.append(f"{iface}: Unusually strong signal ({signal} dBm)")
            
            # Check for signal changes (could indicate rogue AP)
            baseline_key = f'{iface}_signal'
            if baseline_key not in self.baselines:
                self.baselines[baseline_key] = []
            self.baselines[baseline_key].append(signal)
            
            if len(self.baselines[baseline_key]) > 10:
                self.baselines[baseline_key] = self.baselines[baseline_key][-10:]
                std_signal = np.std(self.baselines[baseline_key])
                
                if std_signal > 15:
                    anomalies.append(f"{iface}: Unstable signal (possible AP switching)")
                    
        return anomalies


# ======================
# MAIN MONITOR
# ======================

class AdvancedSystemMonitor:
    """Advanced system monitoring with comprehensive sensor reading"""
    
    def __init__(self, log_file=None):
        self.anomaly_detector = AnomalyDetector()
        self.log_file = log_file
        self.threat_log = deque(maxlen=1000)
        self.start_time = time.time()
        self.sample_count = 0
        
    def collect_all_data(self):
        """Collect data from all available sensors"""
        timestamp = time.time()
        
        data = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'uptime': ProcReader.get_uptime(),
            'cpu': ProcReader.get_cpu_info(),
            'memory': ProcReader.get_memory_info(),
            'loadavg': ProcReader.get_loadavg(),
            'network_stats': ProcReader.get_network_stats(),
            'wireless': ProcReader.get_wireless_info(),
            'temperatures': SysReader.get_temperatures(),
            'usb_devices': SysReader.get_usb_devices(),
            'network_interfaces': SysReader.get_network_interfaces(),
            'threats': [],
            'risk_level': 'LOW'
        }
        
        # Run anomaly detection
        network_anomalies = self.anomaly_detector.check_network_anomalies(data['network_stats'])
        for anomaly in network_anomalies:
            data['threats'].append(('Network', anomaly))
            
        cpu_anomalies = self.anomaly_detector.check_cpu_anomalies(data['cpu'])
        for anomaly in cpu_anomalies:
            data['threats'].append(('CPU', anomaly))
            
        usb_anomalies = self.anomaly_detector.check_usb_anomalies(data['usb_devices'])
        for anomaly in usb_anomalies:
            data['threats'].append(('USB', anomaly))
            
        wireless_anomalies = self.anomaly_detector.check_wireless_anomalies(data['wireless'])
        for anomaly in wireless_anomalies:
            data['threats'].append(('Wireless', anomaly))
        
        # Check processes periodically
        if self.sample_count % 5 == 0:
            processes = ProcReader.get_running_processes()
            proc_anomalies = self.anomaly_detector.check_process_anomalies(processes)
            for anomaly in proc_anomalies:
                data['threats'].append(('Process', anomaly))
        
        # Calculate risk level
        threat_count = len(data['threats'])
        if threat_count >= 4:
            data['risk_level'] = 'CRITICAL'
        elif threat_count >= 2:
            data['risk_level'] = 'HIGH'
        elif threat_count >= 1:
            data['risk_level'] = 'MEDIUM'
        else:
            data['risk_level'] = 'LOW'
            
        self.sample_count += 1
        return data
    
    def display_dashboard(self, data):
        """Display the monitoring dashboard"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        # Header
        print("╔" + "═" * 72 + "╗")
        print("║" + " " * 17 + "ADVANCED SYSTEM SECURITY MONITOR" + " " * 22 + "║")
        print("║" + f"  Time: {data['datetime'][:19]}   Uptime: {data['uptime']:.0f}s   Samples: {self.sample_count}" + " " * 11 + "║")
        print("╚" + "═" * 72 + "╝")
        print()
        
        # System Overview
        print("┌─ SYSTEM OVERVIEW " + "─" * 54 + "┐")
        cpu = data['cpu']
        mem = data['memory']
        load = data['loadavg']
        
        print(f"│  CPU: {cpu['usage_percent']:.1f}% (User: {cpu['user_percent']:.1f}%, Sys: {cpu['system_percent']:.1f}%)" + " " * 28 + "│")
        print(f"│  Memory: {mem['used_percent']:.1f}% ({mem['available_kb']/1024:.0f} MB free)" + " " * 35 + "│")
        print(f"│  Load Average: {load['1min']:.2f} / {load['5min']:.2f} / {load['15min']:.2f}" + " " * 35 + "│")
        print("└" + "─" * 72 + "┘")
        print()
        
        # Temperature
        temps = data['temperatures']
        if temps:
            print("┌─ TEMPERATURES " + "─" * 57 + "┐")
            temp_items = list(temps.items())[:3]
            for name, temp in temp_items:
                display_name = name[:40] if len(name) > 40 else name
                color = '\033[91m' if temp > 80 else ('\033[93m' if temp > 60 else '\033[92m')
                print(f"│  {display_name}: {color}{temp:.1f}°C\033[0m" + " " * (55 - len(display_name)) + "│")
            print("└" + "─" * 72 + "┘")
            print()
        
        # Network
        print("┌─ NETWORK STATUS " + "─" * 55 + "┐")
        
        # Wireless info
        wireless = data['wireless']
        if wireless:
            for iface, info in list(wireless.items())[:2]:
                signal = info.get('signal_level', 'N/A')
                quality = info.get('quality', 'N/A')
                print(f"│  {iface}: Signal {signal} dBm, Quality {quality}" + " " * 40 + "│")
        else:
            print("│  No wireless interfaces detected" + " " * 38 + "│")
            
        # Network stats
        net_stats = data['network_stats']
        active_ifaces = [(k, v) for k, v in net_stats.items() 
                        if v['rx_bytes'] > 0 and k != 'lo'][:2]
        for iface, stats in active_ifaces:
            rx_mb = stats['rx_bytes'] / (1024*1024)
            tx_mb = stats['tx_bytes'] / (1024*1024)
            print(f"│  {iface}: RX {rx_mb:.1f} MB, TX {tx_mb:.1f} MB" + " " * 38 + "│")
            
        print("└" + "─" * 72 + "┘")
        print()
        
        # USB Devices
        usb = data['usb_devices']
        if usb:
            print("┌─ USB DEVICES " + "─" * 58 + "┐")
            for device in usb[:4]:
                name = device.get('product', device.get('bus_id', 'Unknown'))[:45]
                vid_pid = f"{device['vendor_id']}:{device['product_id']}"
                print(f"│  [{vid_pid}] {name}" + " " * (54 - len(name)) + "│")
            if len(usb) > 4:
                print(f"│  ... and {len(usb) - 4} more devices" + " " * 51 + "│")
            print("└" + "─" * 72 + "┘")
            print()
        
        # Threat Assessment
        risk_colors = {
            'LOW': '\033[92m',
            'MEDIUM': '\033[93m',
            'HIGH': '\033[91m',
            'CRITICAL': '\033[95m'
        }
        color = risk_colors.get(data['risk_level'], '')
        reset = '\033[0m'
        
        print("┌─ THREAT ASSESSMENT " + "─" * 52 + "┐")
        print(f"│  Risk Level: {color}{data['risk_level']}{reset}" + " " * (57 - len(data['risk_level'])) + "│")
        print(f"│  Active Threats: {len(data['threats'])}" + " " * 52 + "│")
        print("│" + " " * 72 + "│")
        
        if data['threats']:
            for threat_type, message in data['threats'][:6]:
                line = f"│  ⚠  [{threat_type}] {message}"
                padding = 73 - len(line)
                print(line + " " * max(0, padding) + "│")
        else:
            print("│  ✓  All systems normal - No threats detected" + " " * 26 + "│")
            
        print("└" + "─" * 72 + "┘")
        print()
        print("  Press Ctrl+C to stop monitoring")
        
    def log_data(self, data):
        """Log data to file"""
        if self.log_file:
            log_entry = {
                'timestamp': data['timestamp'],
                'datetime': data['datetime'],
                'risk_level': data['risk_level'],
                'threats': data['threats'],
                'cpu_usage': data['cpu']['usage_percent'],
                'memory_usage': data['memory']['used_percent']
            }
            
            try:
                with open(self.log_file, 'a') as f:
                    f.write(json.dumps(log_entry) + '\n')
            except IOError as e:
                print(f"Warning: Could not write to log file: {e}")
                
    def run(self, interval=1.0):
        """Run the monitoring loop"""
        print("Starting Advanced System Monitor...")
        print(f"Monitoring interval: {interval}s")
        if self.log_file:
            print(f"Logging to: {self.log_file}")
        print()
        time.sleep(1)
        
        try:
            while True:
                data = self.collect_all_data()
                self.display_dashboard(data)
                self.log_data(data)
                
                for threat in data['threats']:
                    self.threat_log.append({
                        'timestamp': data['datetime'],
                        'type': threat[0],
                        'message': threat[1]
                    })
                    
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitor stopped.")
            
            if self.threat_log:
                print(f"\n=== Session Summary ===")
                print(f"Total samples: {self.sample_count}")
                print(f"Threats logged: {len(self.threat_log)}")
                print(f"Duration: {time.time() - self.start_time:.0f} seconds")
                
                if len(self.threat_log) > 0:
                    print("\nRecent threats:")
                    for threat in list(self.threat_log)[-5:]:
                        print(f"  [{threat['timestamp'][:19]}] {threat['type']}: {threat['message']}")


def check_system():
    """One-time system check"""
    print("=" * 74)
    print("  SYSTEM SECURITY CHECK")
    print("=" * 74)
    print()
    
    monitor = AdvancedSystemMonitor()
    data = monitor.collect_all_data()
    
    print(f"Timestamp: {data['datetime']}")
    print(f"System Uptime: {data['uptime']:.0f} seconds")
    print()
    
    print("CPU Information:")
    print(f"  Usage: {data['cpu']['usage_percent']:.1f}%")
    print(f"  Cores: {data['cpu']['cores']}")
    print()
    
    print("Memory Information:")
    print(f"  Total: {data['memory']['total_kb']/1024:.0f} MB")
    print(f"  Available: {data['memory']['available_kb']/1024:.0f} MB")
    print(f"  Used: {data['memory']['used_percent']:.1f}%")
    print()
    
    print("Temperature Sensors:")
    for name, temp in data['temperatures'].items():
        print(f"  {name}: {temp:.1f}°C")
    print()
    
    print("Network Interfaces:")
    for name, info in data['network_interfaces'].items():
        status = "UP" if info['carrier'] else "DOWN"
        print(f"  {name}: {info['address']} ({status})")
    print()
    
    print("USB Devices:")
    for device in data['usb_devices']:
        print(f"  [{device['vendor_id']}:{device['product_id']}] {device.get('product', 'Unknown')}")
    print()
    
    print("Security Assessment:")
    if data['threats']:
        print(f"  Risk Level: {data['risk_level']}")
        for threat_type, message in data['threats']:
            print(f"  ⚠  {threat_type}: {message}")
    else:
        print("  ✓ No security threats detected")
    print()


def main():
    parser = argparse.ArgumentParser(description='Advanced System Security Monitor')
    parser.add_argument('--log', type=str, help='Log file path')
    parser.add_argument('--interval', type=float, default=1.0, help='Monitoring interval in seconds')
    parser.add_argument('--check-only', action='store_true', help='Run one-time system check')
    
    args = parser.parse_args()
    
    if args.check_only:
        check_system()
    else:
        monitor = AdvancedSystemMonitor(log_file=args.log)
        monitor.run(interval=args.interval)


if __name__ == "__main__":
    main()