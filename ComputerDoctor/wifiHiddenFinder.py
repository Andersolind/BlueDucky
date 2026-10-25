#!/usr/bin/env python3
# ================================================================================
# HIDDEN SSID REVEALER
# ================================================================================
# Reveals hidden network SSIDs using multiple methods:
# 1. Passive monitoring (wait for client activity)
# 2. Deauthentication attack (force clients to reconnect)
# 3. Probe request flood
#
# TARGET: F0:21:E0:1F:21:C7 (or specify your own)
# USAGE: 
#   sudo python3 reveal_hidden_ssid.py
#   sudo python3 reveal_hidden_ssid.py --bssid F0:21:E0:1F:21:C7
#   sudo python3 reveal_hidden_ssid.py --bssid F0:21:E0:1F:21:C7 --channel 6
# ================================================================================

import os
import sys
import time
import subprocess
import argparse
import signal
from pathlib import Path
from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeReq

def run_cmd(cmd, timeout=30):
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "Timeout", 1
    except Exception as e:
        return str(e), 1

def check_root():
    """Ensure the script runs with root privileges"""
    if os.geteuid() != 0:
        print("\033[91m[ERROR] Must run as root!\033[0m")
        print("Usage: sudo python3 reveal_hidden_ssid.py")
        sys.exit(1)

def find_interface():
    """Find wireless interface name dynamically"""
    output, _ = run_cmd("iw dev")
    for line in output.split('\n'):
        if "Interface" in line:
            return line.split()[-1]
    
    # Fallback
    for iface in Path('/sys/class/net').iterdir():
        if (iface / 'wireless').exists():
            return iface.name
    return None

def enable_monitor(interface):
    """Enable monitor mode on the wireless interface"""
    print(f"[*] Enabling monitor mode on {interface}...")
    run_cmd("airmon-ng check kill")
    time.sleep(1)
    output, code = run_cmd(f"airmon-ng start {interface}")
    
    # Identify monitor interface
    match = subprocess.run("iw dev | grep -B 1 monitor | grep Interface", shell=True, capture_output=True, text=True)
    if match.returncode == 0:
        lines = match.stdout.strip().split('\n')
        for line in lines:
            if 'Interface' in line:
                return line.split()[-1]
    return interface

def packet_handler(packet):
    """Callback function to analyze packets and extract hidden SSIDs"""
    if packet.haslayer(Dot11Beacon):
        # Hidden SSIDs show up as null/empty info in Beacon frames
        if packet.getlayer(Dot11Beacon).info == b'':
            addr2 = packet.getlayer(Dot11).addr2
            print(f"[+] Detected Hidden SSID Network! BSSID: {addr2}")
            
    elif packet.haslayer(Dot11ProbeReq):
        # Probe Requests often contain the actual SSID when a device tries to connect
        client_name = packet.getlayer(Dot11ProbeReq).info.decode('utf-8', errors='ignore')
        if client_name:
            print(f"[+] Probe Request captured - Device searching for SSID: {client_name}")

def start_sniffing(interface):
    """Start sniffing packets on the specified monitor interface"""
    print(f"[*] Listening for network activity on {interface}...")
    try:
        sniff(iface=interface, prn=packet_handler, store=0)
    except KeyboardInterrupt:
        print("\n[*] Stopping sniffer.")
        sys.exit(0)

def main():
    check_root()
    
    parser = argparse.ArgumentParser(description="Reveal hidden network SSIDs")
    parser.add_argument("--bssid", help="Target BSSID to focus on")
    parser.add_argument("--channel", type=int, help="Channel to listen on")
    args = parser.parse_args()

    interface = find_interface()
    if not interface:
        print("[-] No wireless interface found. Please specify manually.")
        sys.exit(1)

    print(f"[*] Found wireless interface: {interface}")
    monitor_iface = enable_monitor(interface)
    print(f"[*] Using monitor interface: {monitor_iface}")
    
    if args.channel:
        run_cmd(f"iwconfig {monitor_iface} channel {args.channel}")
        print(f"[*] Set to channel {args.channel}")

    start_sniffing(monitor_iface)

if __name__ == "__main__":
    main()
