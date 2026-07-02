#!/usr/bin/env python3
"""
================================================================================
KALI SPOOFER DETECTOR - FIXED VERSION
================================================================================

Fixed issues:
- Better interface detection
- Multiple monitor mode methods
- Handles airmon-ng failures
- Works without airodump-ng (fallback to iw)
- Better error handling

USAGE:
    sudo python3 kali_spoofer_fixed.py
    sudo python3 kali_spoofer_fixed.py -i wlan0
    sudo python3 kali_spoofer_fixed.py -i wlan0 -t "Biru"

================================================================================
"""

import os
import sys
import time
import subprocess
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import argparse
import signal


# =============================================================================
# MAC VENDOR DATABASE
# =============================================================================

MAC_VENDORS = {
    "00:1E:58": "D-Link", "00:1F:33": "Netgear", "00:22:6B": "Cisco-Linksys",
    "14:CC:20": "TP-Link", "18:D6:C7": "TP-Link", "30:B5:C2": "TP-Link",
    "34:97:F6": "ASUSTek", "40:16:7E": "ASUSTek", "50:C7:BF": "TP-Link",
    "78:8A:20": "Ubiquiti", "84:16:F9": "TP-Link", "A4:2B:B0": "TP-Link",
    "C4:6E:1F": "TP-Link", "C8:3A:35": "Tenda", "E8:94:F6": "TP-Link",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "24:0A:C4": "Espressif", "30:AE:A4": "Espressif", "5C:CF:7F": "Espressif",
    "00:0C:29": "VMware", "00:50:56": "VMware", "08:00:27": "VirtualBox",
    "00:C0:CA": "Alfa",
}

def get_vendor(mac):
    """Get vendor from MAC address"""
    if not mac:
        return "Unknown"
    prefix = mac[:8].upper()
    return MAC_VENDORS.get(prefix, "Unknown")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def run_cmd(cmd, timeout=30, shell=True):
    """Run shell command safely"""
    try:
        if isinstance(cmd, list):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        else:
            result = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out", 1
    except FileNotFoundError as e:
        return f"Command not found: {e}", 1
    except Exception as e:
        return str(e), 1


def check_root():
    """Check if running as root"""
    if os.geteuid() != 0:
        print("\n\033[91m[ERROR] This script must be run as root!\033[0m")
        print("\nUsage: sudo python3 kali_spoofer_fixed.py\n")
        sys.exit(1)


def check_tools():
    """Check which tools are available"""
    tools = {
        'airmon-ng': False,
        'airodump-ng': False,
        'iw': False,
        'iwlist': False,
        'iwconfig': False,
        'ip': False,
    }
    
    for tool in tools:
        output, code = run_cmd(f"which {tool}")
        tools[tool] = code == 0
    
    return tools


# =============================================================================
# INTERFACE FUNCTIONS
# =============================================================================

def find_wireless_interfaces():
    """Find all wireless interfaces"""
    interfaces = []
    
    # Method 1: Check /sys/class/net/*/wireless
    try:
        for iface_path in Path('/sys/class/net').iterdir():
            if (iface_path / 'wireless').exists():
                interfaces.append(iface_path.name)
    except Exception as e:
        print(f"  Warning: Could not check /sys/class/net: {e}")
    
    # Method 2: Use iw dev
    output, code = run_cmd("iw dev 2>/dev/null")
    if code == 0:
        for line in output.split('\n'):
            if 'Interface' in line:
                parts = line.split()
                if len(parts) >= 2:
                    iface = parts[-1]
                    if iface not in interfaces:
                        interfaces.append(iface)
    
    # Method 3: Use iwconfig
    output, code = run_cmd("iwconfig 2>/dev/null")
    if code == 0:
        for line in output.split('\n'):
            if 'IEEE 802.11' in line or 'Mode:' in line:
                parts = line.split()
                if parts:
                    iface = parts[0]
                    if iface not in interfaces and not iface.startswith(' '):
                        interfaces.append(iface)
    
    return interfaces


def get_interface_mode(interface):
    """Get current mode of interface"""
    output, _ = run_cmd(f"iwconfig {interface} 2>/dev/null")
    
    if 'Mode:Monitor' in output:
        return 'monitor'
    elif 'Mode:Managed' in output:
        return 'managed'
    else:
        return 'unknown'


def enable_monitor_mode(interface, tools):
    """Enable monitor mode using available methods"""
    print(f"\n  Enabling monitor mode on {interface}...")
    
    # Check current mode
    current_mode = get_interface_mode(interface)
    if current_mode == 'monitor':
        print(f"  \033[92m✓ {interface} already in monitor mode\033[0m")
        return interface
    
    # Kill interfering processes
    print("  Killing interfering processes...")
    run_cmd("systemctl stop NetworkManager 2>/dev/null")
    run_cmd("systemctl stop wpa_supplicant 2>/dev/null")
    run_cmd("killall wpa_supplicant 2>/dev/null")
    run_cmd("killall dhclient 2>/dev/null")
    
    if tools.get('airmon-ng'):
        run_cmd("airmon-ng check kill 2>/dev/null")
    
    time.sleep(1)
    
    # Method 1: Try airmon-ng
    if tools.get('airmon-ng'):
        print("  Trying airmon-ng...")
        output, code = run_cmd(f"airmon-ng start {interface} 2>&1")
        
        # Check for created monitor interface
        for suffix in ['mon', '']:
            test_iface = f"{interface}{suffix}" if suffix else interface
            if Path(f'/sys/class/net/{test_iface}').exists():
                if get_interface_mode(test_iface) == 'monitor':
                    print(f"  \033[92m✓ Monitor mode enabled: {test_iface}\033[0m")
                    return test_iface
        
        # Check if wlan0mon was created
        if Path('/sys/class/net/wlan0mon').exists():
            if get_interface_mode('wlan0mon') == 'monitor':
                print(f"  \033[92m✓ Monitor mode enabled: wlan0mon\033[0m")
                return 'wlan0mon'
    
    # Method 2: Try iw
    if tools.get('iw'):
        print("  Trying iw...")
        run_cmd(f"ip link set {interface} down")
        time.sleep(0.5)
        output, code = run_cmd(f"iw dev {interface} set type monitor")
        run_cmd(f"ip link set {interface} up")
        time.sleep(0.5)
        
        if get_interface_mode(interface) == 'monitor':
            print(f"  \033[92m✓ Monitor mode enabled: {interface}\033[0m")
            return interface
    
    # Method 3: Try iwconfig
    if tools.get('iwconfig'):
        print("  Trying iwconfig...")
        run_cmd(f"ifconfig {interface} down 2>/dev/null || ip link set {interface} down")
        time.sleep(0.5)
        run_cmd(f"iwconfig {interface} mode monitor")
        run_cmd(f"ifconfig {interface} up 2>/dev/null || ip link set {interface} up")
        time.sleep(0.5)
        
        if get_interface_mode(interface) == 'monitor':
            print(f"  \033[92m✓ Monitor mode enabled: {interface}\033[0m")
            return interface
    
    print(f"  \033[91m✗ Failed to enable monitor mode on {interface}\033[0m")
    print("\n  Possible solutions:")
    print("    1. Try a different interface")
    print("    2. Check if your adapter supports monitor mode:")
    print(f"       iw phy phy0 info | grep monitor")
    print("    3. Try manually:")
    print(f"       sudo ip link set {interface} down")
    print(f"       sudo iw dev {interface} set type monitor")
    print(f"       sudo ip link set {interface} up")
    
    return None


def disable_monitor_mode(interface, original_interface, tools):
    """Restore interface to managed mode"""
    print(f"\n  Restoring {original_interface}...")
    
    if tools.get('airmon-ng'):
        run_cmd(f"airmon-ng stop {interface} 2>/dev/null")
    
    if interface != original_interface:
        # If we created a mon interface, try to delete it
        run_cmd(f"iw dev {interface} del 2>/dev/null")
    else:
        # Restore to managed mode
        run_cmd(f"ip link set {interface} down 2>/dev/null")
        run_cmd(f"iw dev {interface} set type managed 2>/dev/null")
        run_cmd(f"ip link set {interface} up 2>/dev/null")
    
    # Restart network services
    run_cmd("systemctl start NetworkManager 2>/dev/null")
    
    print("  \033[92m✓ Interface restored\033[0m")


# =============================================================================
# SCANNING FUNCTIONS
# =============================================================================

def scan_with_airodump(interface, duration=30):
    """Scan using airodump-ng"""
    output_dir = f"/tmp/wifi_scan_{int(time.time())}"
    os.makedirs(output_dir, exist_ok=True)
    output_file = f"{output_dir}/scan"
    
    print(f"\n  Scanning with airodump-ng for {duration} seconds...")
    print("  (You should see networks appearing)\n")
    
    # Run airodump-ng with output to file
    cmd = f"timeout {duration} airodump-ng {interface} -w {output_file} --output-format csv --write-interval 1 2>&1"
    
    process = subprocess.Popen(
        cmd, shell=True, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid
    )
    
    # Wait and show progress
    start_time = time.time()
    try:
        while time.time() - start_time < duration:
            elapsed = int(time.time() - start_time)
            remaining = duration - elapsed
            pct = int(elapsed / duration * 100)
            bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
            print(f"\r  [{bar}] {pct}% ({remaining}s remaining)", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except:
            pass
    
    print("\n")
    
    # Find CSV file
    csv_files = list(Path(output_dir).glob("*.csv"))
    if not csv_files:
        print("  \033[93mNo CSV file created by airodump-ng\033[0m")
        return [], []
    
    csv_file = str(csv_files[0])
    return parse_airodump_csv(csv_file)


def scan_with_iw(interface, duration=30):
    """Scan using iw (fallback method)"""
    print(f"\n  Scanning with iw for {duration} seconds...")
    
    access_points = []
    seen_bssids = set()
    
    start_time = time.time()
    scan_count = 0
    
    while time.time() - start_time < duration:
        # Trigger scan
        run_cmd(f"iw dev {interface} scan trigger 2>/dev/null")
        time.sleep(2)
        
        # Get results
        output, code = run_cmd(f"iw dev {interface} scan dump 2>/dev/null")
        
        if code == 0:
            current_ap = {}
            
            for line in output.split('\n'):
                line = line.strip()
                
                if line.startswith('BSS '):
                    # Save previous AP
                    if current_ap and current_ap.get('bssid') not in seen_bssids:
                        seen_bssids.add(current_ap['bssid'])
                        access_points.append(current_ap)
                    
                    # Start new AP
                    match = re.search(r'BSS ([0-9a-fA-F:]{17})', line)
                    if match:
                        current_ap = {
                            'bssid': match.group(1).upper(),
                            'essid': '',
                            'channel': '',
                            'power': '',
                            'privacy': '',
                            'vendor': get_vendor(match.group(1))
                        }
                
                elif 'SSID:' in line:
                    ssid = line.split('SSID:', 1)[1].strip()
                    if current_ap:
                        current_ap['essid'] = ssid
                
                elif 'signal:' in line:
                    match = re.search(r'signal:\s*([-\d.]+)', line)
                    if match and current_ap:
                        current_ap['power'] = match.group(1)
                
                elif 'primary channel:' in line or 'DS Parameter set: channel' in line:
                    match = re.search(r'(\d+)', line)
                    if match and current_ap:
                        current_ap['channel'] = match.group(1)
                
                elif 'RSN:' in line or 'WPA:' in line:
                    if current_ap:
                        current_ap['privacy'] = 'WPA2' if 'RSN' in line else 'WPA'
                
                elif 'WEP:' in line:
                    if current_ap:
                        current_ap['privacy'] = 'WEP'
            
            # Save last AP
            if current_ap and current_ap.get('bssid') not in seen_bssids:
                seen_bssids.add(current_ap['bssid'])
                access_points.append(current_ap)
        
        scan_count += 1
        elapsed = int(time.time() - start_time)
        pct = int(elapsed / duration * 100)
        bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
        print(f"\r  [{bar}] {pct}% - Found {len(access_points)} APs", end="", flush=True)
    
    print("\n")
    return access_points, []


def scan_with_iwlist(interface, duration=30):
    """Scan using iwlist (another fallback)"""
    print(f"\n  Scanning with iwlist for {duration} seconds...")
    
    access_points = []
    seen_bssids = set()
    
    start_time = time.time()
    
    while time.time() - start_time < duration:
        output, code = run_cmd(f"iwlist {interface} scan 2>/dev/null")
        
        if code == 0:
            current_ap = {}
            
            for line in output.split('\n'):
                line = line.strip()
                
                if 'Cell' in line and 'Address:' in line:
                    # Save previous
                    if current_ap and current_ap.get('bssid') not in seen_bssids:
                        seen_bssids.add(current_ap['bssid'])
                        access_points.append(current_ap)
                    
                    match = re.search(r'Address:\s*([0-9A-Fa-f:]{17})', line)
                    if match:
                        current_ap = {
                            'bssid': match.group(1).upper(),
                            'essid': '',
                            'channel': '',
                            'power': '',
                            'privacy': '',
                            'vendor': get_vendor(match.group(1))
                        }
                
                elif 'ESSID:' in line:
                    match = re.search(r'ESSID:"([^"]*)"', line)
                    if match and current_ap:
                        current_ap['essid'] = match.group(1)
                
                elif 'Signal level' in line:
                    match = re.search(r'Signal level[=:](-?\d+)', line)
                    if match and current_ap:
                        current_ap['power'] = match.group(1)
                
                elif 'Channel:' in line:
                    match = re.search(r'Channel:(\d+)', line)
                    if match and current_ap:
                        current_ap['channel'] = match.group(1)
                
                elif 'Encryption key:on' in line:
                    if current_ap:
                        current_ap['privacy'] = 'WPA/WPA2'
                elif 'Encryption key:off' in line:
                    if current_ap:
                        current_ap['privacy'] = 'OPN'
            
            # Save last
            if current_ap and current_ap.get('bssid') not in seen_bssids:
                seen_bssids.add(current_ap['bssid'])
                access_points.append(current_ap)
        
        elapsed = int(time.time() - start_time)
        pct = int(elapsed / duration * 100)
        bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
        print(f"\r  [{bar}] {pct}% - Found {len(access_points)} APs", end="", flush=True)
        
        time.sleep(3)
    
    print("\n")
    return access_points, []


def parse_airodump_csv(csv_file):
    """Parse airodump-ng CSV output"""
    access_points = []
    clients = []
    
    try:
        with open(csv_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"  Error reading CSV: {e}")
        return [], []
    
    # Split into AP and client sections
    parts = content.split('Station MAC')
    ap_section = parts[0] if parts else ""
    client_section = parts[1] if len(parts) > 1 else ""
    
    # Parse APs
    for line in ap_section.split('\n'):
        line = line.strip()
        if not line or 'BSSID' in line or line.startswith('#'):
            continue
        
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 14:
            continue
        
        bssid = parts[0]
        if not re.match(r'^[0-9A-Fa-f:]{17}$', bssid):
            continue
        
        ap = {
            'bssid': bssid.upper(),
            'channel': parts[3] if len(parts) > 3 else '',
            'privacy': parts[5] if len(parts) > 5 else '',
            'power': parts[8] if len(parts) > 8 else '',
            'essid': parts[13] if len(parts) > 13 else '',
            'vendor': get_vendor(bssid)
        }
        
        access_points.append(ap)
    
    # Parse clients
    for line in client_section.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 6:
            continue
        
        client_mac = parts[0]
        if not re.match(r'^[0-9A-Fa-f:]{17}$', client_mac):
            continue
        
        client = {
            'mac': client_mac.upper(),
            'power': parts[3] if len(parts) > 3 else '',
            'bssid': parts[5] if len(parts) > 5 else '',
            'probes': parts[6] if len(parts) > 6 else '',
            'vendor': get_vendor(client_mac)
        }
        
        clients.append(client)
    
    return access_points, clients


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================

def find_hidden_networks(access_points):
    """Find hidden networks"""
    return [ap for ap in access_points if not ap.get('essid') or ap['essid'].isspace()]


def find_evil_twins(access_points):
    """Find potential evil twins (same SSID, different BSSID)"""
    by_ssid = defaultdict(list)
    
    for ap in access_points:
        if ap.get('essid'):
            by_ssid[ap['essid']].append(ap)
    
    return {ssid: aps for ssid, aps in by_ssid.items() if len(aps) > 1}


def find_suspicious_aps(access_points):
    """Find suspicious access points"""
    suspicious = []
    
    for ap in access_points:
        reasons = []
        
        # Very strong signal
        try:
            power = int(ap.get('power', -100))
            if power > -30 and power != 0:
                reasons.append(f"Very strong signal ({power} dBm)")
        except:
            pass
        
        # Open network
        privacy = ap.get('privacy', '').upper()
        if privacy == 'OPN' or privacy == '' or 'OPEN' in privacy:
            reasons.append("No encryption (open network)")
        
        # Suspicious vendor
        vendor = ap.get('vendor', '').lower()
        suspicious_vendors = ['raspberry', 'espressif', 'vmware', 'virtualbox', 'alfa']
        if any(v in vendor for v in suspicious_vendors):
            reasons.append(f"Suspicious vendor: {ap.get('vendor')}")
        
        if reasons:
            ap['suspicious_reasons'] = reasons
            suspicious.append(ap)
    
    return suspicious


# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

def print_banner():
    print("\n\033[95m" + "=" * 70)
    print("  KALI SPOOFER DETECTOR - FIXED VERSION")
    print("=" * 70 + "\033[0m\n")


def print_section(title):
    print(f"\n\033[96m┌─ {title} " + "─" * (66 - len(title)) + "┐\033[0m")


def print_end():
    print("\033[96m└" + "─" * 68 + "┘\033[0m")


def print_aps(access_points, title="ACCESS POINTS"):
    """Print access points table"""
    print_section(title)
    
    if not access_points:
        print("  No access points found")
        print_end()
        return
    
    print(f"  {'BSSID':<18} {'PWR':<6} {'CH':<4} {'ENC':<10} {'ESSID':<20} {'VENDOR':<12}")
    print("  " + "-" * 75)
    
    for ap in access_points[:40]:
        essid = ap.get('essid', '') or '\033[93m<HIDDEN>\033[0m'
        essid_display = essid[:20] if not '<HIDDEN>' in essid else essid
        
        print(f"  {ap.get('bssid', 'N/A'):<18} "
              f"{ap.get('power', 'N/A'):<6} "
              f"{ap.get('channel', 'N/A'):<4} "
              f"{ap.get('privacy', 'N/A'):<10} "
              f"{essid_display:<20} "
              f"{ap.get('vendor', 'Unknown')[:12]:<12}")
    
    if len(access_points) > 40:
        print(f"\n  ... and {len(access_points) - 40} more")
    
    print_end()


def print_evil_twins(evil_twins, your_bssid=None):
    """Print evil twin detection"""
    print_section("EVIL TWIN DETECTION")
    
    if not evil_twins:
        print("  \033[92m✓ No duplicate SSIDs found\033[0m")
        print_end()
        return
    
    for ssid, aps in evil_twins.items():
        print(f"\n  \033[91m⚠ SSID: \"{ssid}\" has {len(aps)} access points!\033[0m\n")
        
        for ap in aps:
            is_yours = ""
            if your_bssid and ap['bssid'].upper() == your_bssid.upper():
                is_yours = " \033[92m← YOUR ROUTER\033[0m"
            else:
                is_yours = " \033[91m← CHECK THIS!\033[0m"
            
            print(f"    BSSID: {ap['bssid']}{is_yours}")
            print(f"    Power: {ap.get('power', 'N/A')} dBm | "
                  f"Channel: {ap.get('channel', 'N/A')} | "
                  f"Vendor: {ap.get('vendor', 'Unknown')}")
            print()
    
    print_end()


def print_hidden(hidden_aps):
    """Print hidden networks"""
    print_section("HIDDEN NETWORKS")
    
    if not hidden_aps:
        print("  \033[92m✓ No hidden networks detected\033[0m")
        print_end()
        return
    
    print(f"  \033[91m⚠ Found {len(hidden_aps)} hidden network(s)!\033[0m\n")
    
    for ap in hidden_aps:
        print(f"    BSSID: {ap['bssid']}")
        print(f"    Power: {ap.get('power', 'N/A')} dBm | "
              f"Channel: {ap.get('channel', 'N/A')} | "
              f"Vendor: {ap.get('vendor', 'Unknown')}")
        print()
    
    print("  To reveal hidden SSID:")
    print("    sudo aireplay-ng -0 5 -a <BSSID> <interface>")
    
    print_end()


def print_suspicious(suspicious_aps):
    """Print suspicious APs"""
    print_section("SUSPICIOUS ACCESS POINTS")
    
    if not suspicious_aps:
        print("  \033[92m✓ No obviously suspicious APs\033[0m")
        print_end()
        return
    
    for ap in suspicious_aps:
        print(f"\n  \033[91m⚠ {ap['bssid']}\033[0m - {ap.get('essid') or '<HIDDEN>'}")
        for reason in ap.get('suspicious_reasons', []):
            print(f"    └─ \033[93m{reason}\033[0m")
    
    print_end()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Kali Spoofer Detector - Fixed')
    parser.add_argument('-i', '--interface', help='Wireless interface (auto-detect if not specified)')
    parser.add_argument('-t', '--target-ssid', help='Target SSID to focus on')
    parser.add_argument('-d', '--duration', type=int, default=30, help='Scan duration (default: 30)')
    parser.add_argument('--your-bssid', help='Your router BSSID for comparison')
    parser.add_argument('--no-monitor', action='store_true', help='Skip monitor mode (use managed mode scanning)')
    
    args = parser.parse_args()
    
    print_banner()
    
    # Check root
    check_root()
    
    # Check available tools
    print("Checking available tools...")
    tools = check_tools()
    for tool, available in tools.items():
        status = "\033[92m✓\033[0m" if available else "\033[91m✗\033[0m"
        print(f"  {status} {tool}")
    
    # Find interfaces
    print("\nFinding wireless interfaces...")
    interfaces = find_wireless_interfaces()
    
    if not interfaces:
        print("\033[91mNo wireless interfaces found!\033[0m")
        print("\nTry:")
        print("  1. Check if WiFi adapter is connected")
        print("  2. Run: ip link show")
        print("  3. Run: iw dev")
        sys.exit(1)
    
    print(f"  Found: {interfaces}")
    
    # Select interface
    interface = args.interface
    if not interface:
        interface = interfaces[0]
        print(f"  Using: {interface}")
    elif interface not in interfaces:
        # Check if it's a monitor interface
        if not Path(f'/sys/class/net/{interface}').exists():
            print(f"\033[91mInterface {interface} not found!\033[0m")
            print(f"Available: {interfaces}")
            sys.exit(1)
    
    original_interface = interface
    mon_interface = interface
    
    try:
        # Enable monitor mode (unless --no-monitor)
        if not args.no_monitor:
            mon_interface = enable_monitor_mode(interface, tools)
            if not mon_interface:
                print("\n\033[93mFalling back to managed mode scanning...\033[0m")
                mon_interface = interface
                args.no_monitor = True
        
        # Scan
        print_section("SCANNING NETWORKS")
        
        access_points = []
        clients = []
        
        if not args.no_monitor and tools.get('airodump-ng'):
            access_points, clients = scan_with_airodump(mon_interface, args.duration)
        
        if not access_points and tools.get('iw'):
            access_points, clients = scan_with_iw(mon_interface, args.duration)
        
        if not access_points and tools.get('iwlist'):
            access_points, clients = scan_with_iwlist(interface, args.duration)
        
        if not access_points:
            print("\033[91mNo networks found! Check your adapter.\033[0m")
            return
        
        print(f"  Found {len(access_points)} access points")
        print_end()
        
        # Filter by target SSID if specified
        if args.target_ssid:
            target_aps = [ap for ap in access_points 
                         if ap.get('essid') == args.target_ssid or not ap.get('essid')]
            print(f"\n  Filtered to {len(target_aps)} APs matching '{args.target_ssid}' or hidden")
        else:
            target_aps = access_points
        
        # Display results
        print_aps(target_aps, "DETECTED ACCESS POINTS")
        
        hidden = find_hidden_networks(target_aps)
        print_hidden(hidden)
        
        evil_twins = find_evil_twins(target_aps)
        print_evil_twins(evil_twins, args.your_bssid)
        
        suspicious = find_suspicious_aps(target_aps)
        print_suspicious(suspicious)
        
        # Summary
        print_section("SUMMARY")
        print(f"  Total APs: {len(access_points)}")
        print(f"  Hidden networks: {len(hidden)}")
        print(f"  Duplicate SSIDs (possible evil twins): {len(evil_twins)}")
        print(f"  Suspicious APs: {len(suspicious)}")
        
        if hidden or evil_twins or suspicious:
            print(f"\n  \033[91m⚠ POTENTIAL THREATS DETECTED!\033[0m")
        else:
            print(f"\n  \033[92m✓ No obvious threats detected\033[0m")
        
        print_end()
        
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user")
    
    finally:
        # Cleanup
        if not args.no_monitor and mon_interface != original_interface:
            disable_monitor_mode(mon_interface, original_interface, tools)
        elif not args.no_monitor:
            # Restore managed mode
            print("\n  Restoring managed mode...")
            run_cmd(f"ip link set {interface} down")
            run_cmd(f"iw dev {interface} set type managed")
            run_cmd(f"ip link set {interface} up")
            run_cmd("systemctl start NetworkManager 2>/dev/null")
            print("  \033[92m✓ Done\033[0m")


if __name__ == "__main__":
    main()