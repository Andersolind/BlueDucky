#!/usr/bin/env python3
"""
================================================================================
REVEAL ALL HIDDEN WIFI NETWORKS
================================================================================

Scans for ALL hidden networks and attempts to reveal their SSIDs.

USAGE:
    sudo python3 reveal_all_hidden.py
    sudo python3 reveal_all_hidden.py --aggressive   # Use deauth to force reveal
    sudo python3 reveal_all_hidden.py --scan-time 60 # Longer scan

================================================================================
"""

import os
import sys
import time
import subprocess
import re
import signal
from pathlib import Path
from collections import defaultdict
import argparse


# MAC Vendor database
MAC_VENDORS = {
    "F0:21:E0": "Shenzhen Bilian",
    "00:1E:58": "D-Link", "00:1F:33": "Netgear", "00:22:6B": "Cisco-Linksys",
    "14:CC:20": "TP-Link", "18:D6:C7": "TP-Link", "30:B5:C2": "TP-Link",
    "34:97:F6": "ASUSTek", "40:16:7E": "ASUSTek", "50:C7:BF": "TP-Link",
    "78:8A:20": "Ubiquiti", "84:16:F9": "TP-Link", "E8:94:F6": "TP-Link",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", 
    "E4:5F:01": "Raspberry Pi", "24:0A:C4": "Espressif", 
    "30:AE:A4": "Espressif", "5C:CF:7F": "Espressif",
    "00:0C:29": "VMware", "00:50:56": "VMware", "08:00:27": "VirtualBox",
    "00:C0:CA": "Alfa", "C8:3A:35": "Tenda", "1C:3B:F3": "Huawei",
    "AC:84:C6": "TP-Link", "C4:6E:1F": "TP-Link", "F4:F2:6D": "TP-Link",
}

def get_vendor(mac):
    if not mac:
        return "Unknown"
    prefix = mac[:8].upper()
    return MAC_VENDORS.get(prefix, "Unknown")


def run_cmd(cmd, timeout=60):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, 
                               text=True, timeout=timeout)
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "Timeout", 1
    except Exception as e:
        return str(e), 1


def check_root():
    if os.geteuid() != 0:
        print("\n\033[91m[!] Must run as root: sudo python3 reveal_all_hidden.py\033[0m\n")
        sys.exit(1)


def find_interface():
    """Find wireless interface"""
    # Try iw dev first
    output, _ = run_cmd("iw dev 2>/dev/null")
    for line in output.split('\n'):
        if 'Interface' in line:
            return line.split()[-1]
    
    # Fallback to /sys
    for iface in Path('/sys/class/net').iterdir():
        if (iface / 'wireless').exists():
            return iface.name
    
    return None


def enable_monitor(interface):
    """Enable monitor mode"""
    print(f"[*] Enabling monitor mode on {interface}...")
    
    # Check if already in monitor
    output, _ = run_cmd(f"iwconfig {interface} 2>/dev/null")
    if 'Mode:Monitor' in output:
        print(f"[+] Already in monitor mode: {interface}")
        return interface
    
    # Kill interfering processes
    run_cmd("systemctl stop NetworkManager 2>/dev/null")
    run_cmd("airmon-ng check kill 2>/dev/null")
    time.sleep(1)
    
    # Try airmon-ng
    run_cmd(f"airmon-ng start {interface} 2>/dev/null")
    
    # Check for monitor interface
    for test_if in [f"{interface}mon", "wlan0mon", interface]:
        if Path(f'/sys/class/net/{test_if}').exists():
            output, _ = run_cmd(f"iwconfig {test_if} 2>/dev/null")
            if 'Mode:Monitor' in output:
                print(f"[+] Monitor mode: {test_if}")
                return test_if
    
    # Manual method
    run_cmd(f"ip link set {interface} down")
    run_cmd(f"iw dev {interface} set type monitor")
    run_cmd(f"ip link set {interface} up")
    
    output, _ = run_cmd(f"iwconfig {interface} 2>/dev/null")
    if 'Mode:Monitor' in output:
        print(f"[+] Monitor mode: {interface}")
        return interface
    
    print("[!] Failed to enable monitor mode")
    return None


def scan_all_networks(mon_interface, duration=30):
    """Scan for all networks including hidden"""
    print(f"\n[*] Scanning all channels for {duration} seconds...")
    print("[*] Looking for hidden networks...\n")
    
    output_dir = f"/tmp/hidden_scan_{int(time.time())}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Run airodump-ng
    cmd = f"timeout {duration} airodump-ng {mon_interface} -w {output_dir}/scan --output-format csv 2>/dev/null"
    
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE, preexec_fn=os.setsid)
    
    # Progress bar
    for i in range(duration):
        pct = int((i+1) / duration * 100)
        bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
        print(f"\r  [{bar}] {pct}%", end="", flush=True)
        time.sleep(1)
    
    print("\n")
    
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except:
        pass
    
    # Parse results
    networks = {'all': [], 'hidden': [], 'visible': []}
    
    csv_files = list(Path(output_dir).glob("*.csv"))
    if not csv_files:
        print("[!] No scan results - trying alternative method...")
        return scan_with_iw(mon_interface, duration)
    
    try:
        with open(csv_files[0], 'r', errors='ignore') as f:
            content = f.read()
        
        # Parse AP section (before "Station MAC")
        ap_section = content.split('Station MAC')[0] if 'Station MAC' in content else content
        
        for line in ap_section.split('\n'):
            line = line.strip()
            if not line or 'BSSID' in line:
                continue
            
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 14:
                continue
            
            bssid = parts[0]
            if not re.match(r'^[0-9A-Fa-f:]{17}$', bssid):
                continue
            
            ap = {
                'bssid': bssid.upper(),
                'channel': parts[3] if len(parts) > 3 else '?',
                'privacy': parts[5] if len(parts) > 5 else '',
                'power': parts[8] if len(parts) > 8 else '?',
                'essid': parts[13] if len(parts) > 13 else '',
                'vendor': get_vendor(bssid),
                'is_hidden': False
            }
            
            # Check if hidden
            if not ap['essid'] or ap['essid'].isspace() or len(ap['essid']) == 0:
                ap['is_hidden'] = True
                ap['essid'] = '<HIDDEN>'
                networks['hidden'].append(ap)
            else:
                networks['visible'].append(ap)
            
            networks['all'].append(ap)
            
    except Exception as e:
        print(f"[!] Error parsing results: {e}")
    
    return networks


def scan_with_iw(mon_interface, duration=30):
    """Fallback scan using iw"""
    print("[*] Using iw scan (fallback method)...")
    
    networks = {'all': [], 'hidden': [], 'visible': []}
    seen = set()
    
    start = time.time()
    while time.time() - start < duration:
        run_cmd(f"iw dev {mon_interface} scan trigger 2>/dev/null")
        time.sleep(2)
        
        output, _ = run_cmd(f"iw dev {mon_interface} scan dump 2>/dev/null")
        
        current_ap = {}
        for line in output.split('\n'):
            line = line.strip()
            
            if line.startswith('BSS '):
                if current_ap and current_ap.get('bssid') not in seen:
                    seen.add(current_ap['bssid'])
                    
                    if current_ap.get('is_hidden'):
                        networks['hidden'].append(current_ap)
                    else:
                        networks['visible'].append(current_ap)
                    networks['all'].append(current_ap)
                
                match = re.search(r'BSS ([0-9a-fA-F:]{17})', line)
                if match:
                    current_ap = {
                        'bssid': match.group(1).upper(),
                        'essid': '',
                        'channel': '?',
                        'power': '?',
                        'privacy': '',
                        'vendor': get_vendor(match.group(1)),
                        'is_hidden': True  # Assume hidden until SSID found
                    }
            
            elif 'SSID:' in line and current_ap:
                ssid = line.split('SSID:', 1)[1].strip()
                if ssid:
                    current_ap['essid'] = ssid
                    current_ap['is_hidden'] = False
                else:
                    current_ap['essid'] = '<HIDDEN>'
            
            elif 'signal:' in line and current_ap:
                match = re.search(r'signal:\s*([-\d.]+)', line)
                if match:
                    current_ap['power'] = match.group(1)
            
            elif ('primary channel:' in line or 'DS Parameter set: channel' in line) and current_ap:
                match = re.search(r'(\d+)', line)
                if match:
                    current_ap['channel'] = match.group(1)
        
        # Don't forget last one
        if current_ap and current_ap.get('bssid') not in seen:
            seen.add(current_ap['bssid'])
            if current_ap.get('is_hidden'):
                networks['hidden'].append(current_ap)
            else:
                networks['visible'].append(current_ap)
            networks['all'].append(current_ap)
        
        elapsed = int(time.time() - start)
        print(f"\r  Scanning... {elapsed}/{duration}s - Found {len(networks['all'])} APs, {len(networks['hidden'])} hidden", end="", flush=True)
    
    print("\n")
    return networks


def reveal_hidden_ssid(mon_interface, hidden_ap, aggressive=False):
    """Try to reveal a hidden SSID"""
    bssid = hidden_ap['bssid']
    channel = hidden_ap['channel']
    
    if channel == '?' or not channel:
        return None
    
    # Set channel
    run_cmd(f"iw dev {mon_interface} set channel {channel}")
    
    output_dir = f"/tmp/reveal_{bssid.replace(':', '')}_{int(time.time())}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Start capture
    airodump_cmd = f"airodump-ng -c {channel} --bssid {bssid} -w {output_dir}/cap {mon_interface} 2>/dev/null"
    airodump_proc = subprocess.Popen(airodump_cmd, shell=True, 
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     preexec_fn=os.setsid)
    
    revealed = None
    
    try:
        # If aggressive mode, send deauth
        if aggressive:
            time.sleep(2)
            run_cmd(f"aireplay-ng -0 5 -a {bssid} {mon_interface} 2>/dev/null", timeout=15)
            time.sleep(3)
        else:
            # Just wait passively
            time.sleep(5)
        
        # Check CSV for revealed SSID
        csv_files = list(Path(output_dir).glob("*.csv"))
        if csv_files:
            with open(csv_files[0], 'r', errors='ignore') as f:
                for line in f:
                    if bssid.upper() in line.upper():
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) > 13:
                            ssid = parts[13]
                            if ssid and not ssid.isspace() and ssid != '<HIDDEN>':
                                revealed = ssid
                                break
    except:
        pass
    finally:
        try:
            os.killpg(os.getpgid(airodump_proc.pid), signal.SIGTERM)
        except:
            pass
    
    return revealed


def print_results(networks, revealed_ssids):
    """Print scan results"""
    
    print("\n" + "=" * 75)
    print("  SCAN RESULTS")
    print("=" * 75)
    
    # Summary
    print(f"\n  Total networks found: {len(networks['all'])}")
    print(f"  Visible networks: {len(networks['visible'])}")
    print(f"  Hidden networks: {len(networks['hidden'])}")
    
    # All networks
    print("\n" + "-" * 75)
    print("  ALL NETWORKS")
    print("-" * 75)
    print(f"  {'BSSID':<18} {'CH':<4} {'PWR':<6} {'ENC':<10} {'SSID':<20} {'VENDOR'}")
    print("  " + "-" * 73)
    
    for ap in sorted(networks['all'], key=lambda x: x.get('is_hidden', False), reverse=True):
        bssid = ap['bssid']
        
        # Check if we revealed this one
        if bssid in revealed_ssids and revealed_ssids[bssid]:
            ssid = f"\033[92m{revealed_ssids[bssid]}\033[0m (revealed)"
        elif ap['is_hidden']:
            ssid = "\033[91m<HIDDEN>\033[0m"
        else:
            ssid = ap['essid'][:20]
        
        vendor = ap['vendor'][:15]
        
        # Highlight suspicious vendors
        suspicious = ['raspberry', 'espressif', 'vmware', 'virtualbox', 'alfa', 'bilian']
        if any(s in vendor.lower() for s in suspicious):
            vendor = f"\033[93m{vendor}\033[0m"
        
        print(f"  {bssid:<18} {ap['channel']:<4} {ap['power']:<6} "
              f"{ap['privacy']:<10} {ssid:<20} {vendor}")
    
    # Hidden networks detail
    if networks['hidden']:
        print("\n" + "-" * 75)
        print("  HIDDEN NETWORKS DETAIL")
        print("-" * 75)
        
        for ap in networks['hidden']:
            bssid = ap['bssid']
            print(f"\n  \033[93m■ {bssid}\033[0m")
            print(f"    Channel: {ap['channel']}")
            print(f"    Power: {ap['power']} dBm")
            print(f"    Encryption: {ap['privacy']}")
            print(f"    Vendor: {ap['vendor']}")
            
            if bssid in revealed_ssids and revealed_ssids[bssid]:
                print(f"    \033[92m✓ REVEALED SSID: {revealed_ssids[bssid]}\033[0m")
            else:
                print(f"    \033[91m✗ SSID: Still hidden\033[0m")
                print(f"    → To reveal: sudo aireplay-ng -0 10 -a {bssid} <monitor_interface>")


def restore(mon_interface, original_interface):
    """Restore interface"""
    print("\n[*] Restoring interface...")
    run_cmd(f"airmon-ng stop {mon_interface} 2>/dev/null")
    run_cmd(f"ip link set {original_interface} down 2>/dev/null")
    run_cmd(f"iw dev {original_interface} set type managed 2>/dev/null")
    run_cmd(f"ip link set {original_interface} up 2>/dev/null")
    run_cmd("systemctl start NetworkManager 2>/dev/null")
    print("[+] Done")


def main():
    parser = argparse.ArgumentParser(description='Reveal All Hidden WiFi Networks')
    parser.add_argument('-i', '--interface', help='Wireless interface')
    parser.add_argument('-t', '--scan-time', type=int, default=30, help='Scan duration')
    parser.add_argument('-a', '--aggressive', action='store_true', 
                        help='Use deauth to force SSID reveal (more effective but intrusive)')
    parser.add_argument('--reveal-time', type=int, default=10,
                        help='Time to spend revealing each hidden network')
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("  REVEAL ALL HIDDEN WIFI NETWORKS")
    print("=" * 60)
    
    check_root()
    
    # Find interface
    interface = args.interface or find_interface()
    if not interface:
        print("[!] No wireless interface found!")
        print("    Connect a WiFi adapter and try again")
        sys.exit(1)
    
    print(f"\n[*] Interface: {interface}")
    
    original_interface = interface
    mon_interface = None
    revealed_ssids = {}
    
    try:
        # Enable monitor mode
        mon_interface = enable_monitor(interface)
        if not mon_interface:
            sys.exit(1)
        
        # Scan all networks
        networks = scan_all_networks(mon_interface, args.scan_time)
        
        if not networks['all']:
            print("[!] No networks found!")
            print("    Check that your adapter is working")
            sys.exit(1)
        
        print(f"[+] Found {len(networks['all'])} networks")
        print(f"[+] Found {len(networks['hidden'])} hidden networks")
        
        # Try to reveal hidden SSIDs
        if networks['hidden']:
            print(f"\n[*] Attempting to reveal {len(networks['hidden'])} hidden SSIDs...")
            
            if args.aggressive:
                print("[!] AGGRESSIVE MODE: Will send deauth packets")
                print("[!] This may briefly disconnect nearby devices")
            else:
                print("[*] PASSIVE MODE: Waiting for client activity")
                print("[*] Use --aggressive for faster results")
            
            for i, ap in enumerate(networks['hidden']):
                bssid = ap['bssid']
                print(f"\n[{i+1}/{len(networks['hidden'])}] Trying to reveal: {bssid} (CH:{ap['channel']}, {ap['vendor']})")
                
                ssid = reveal_hidden_ssid(mon_interface, ap, aggressive=args.aggressive)
                
                if ssid:
                    revealed_ssids[bssid] = ssid
                    print(f"    \033[92m✓ REVEALED: {ssid}\033[0m")
                else:
                    revealed_ssids[bssid] = None
                    print(f"    \033[93m✗ Still hidden (no client activity)\033[0m")
        
        # Print results
        print_results(networks, revealed_ssids)
        
        # Summary of findings
        print("\n" + "=" * 75)
        print("  SUMMARY")
        print("=" * 75)
        
        revealed_count = sum(1 for v in revealed_ssids.values() if v)
        print(f"\n  Hidden networks found: {len(networks['hidden'])}")
        print(f"  SSIDs revealed: {revealed_count}")
        
        if revealed_ssids:
            print("\n  Revealed SSIDs:")
            for bssid, ssid in revealed_ssids.items():
                if ssid:
                    vendor = get_vendor(bssid)
                    print(f"    {bssid} → \033[92m{ssid}\033[0m ({vendor})")
        
        still_hidden = [b for b, s in revealed_ssids.items() if not s]
        if still_hidden:
            print("\n  Still hidden (try --aggressive or wait for client activity):")
            for bssid in still_hidden:
                vendor = get_vendor(bssid)
                print(f"    {bssid} ({vendor})")
        
        # Warnings
        suspicious_vendors = ['raspberry', 'espressif', 'vmware', 'virtualbox', 'alfa', 'bilian']
        suspicious_hidden = [ap for ap in networks['hidden'] 
                           if any(s in ap['vendor'].lower() for s in suspicious_vendors)]
        
        if suspicious_hidden:
            print("\n  \033[91m⚠ WARNING: Suspicious hidden networks!\033[0m")
            for ap in suspicious_hidden:
                print(f"    {ap['bssid']} - {ap['vendor']} (could be attack device)")
        
        print()
        
    except KeyboardInterrupt:
        print("\n\n[*] Interrupted by user")
    
    finally:
        if mon_interface:
            restore(mon_interface, original_interface)


if __name__ == "__main__":
    main()