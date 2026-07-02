#!/usr/bin/env python3
"""
================================================================================
CSI ATTACK INVESTIGATOR & DEFENDER
================================================================================

You have 99 replay detections with only 7 unique patterns.
This tool will help you:

1. INVESTIGATE - Find the source of the attack
2. DOCUMENT - Save evidence of the attack
3. DEFEND - Steps to protect yourself

================================================================================
"""

import os
import sys
import time
import json
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path
from collections import Counter
import re

def run_cmd(cmd, timeout=10):
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout + result.stderr
    except:
        return ""

def print_header(title):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()

def print_section(title):
    print()
    print(f"┌─ {title} " + "─" * (65 - len(title)) + "┐")

def print_end():
    print("└" + "─" * 68 + "┘")

def main():
    print_header("CSI ATTACK INVESTIGATOR")
    
    evidence = {
        'timestamp': datetime.now().isoformat(),
        'findings': [],
        'recommendations': []
    }
    
    # =========================================================================
    # STEP 1: IDENTIFY YOUR NETWORK
    # =========================================================================
    print_section("STEP 1: Your Network Information")
    
    # Get current connection
    iwconfig_output = run_cmd("iwconfig 2>/dev/null")
    
    current_ssid = None
    current_bssid = None
    current_freq = None
    
    if 'ESSID:"' in iwconfig_output:
        start = iwconfig_output.find('ESSID:"') + 7
        end = iwconfig_output.find('"', start)
        current_ssid = iwconfig_output[start:end]
    
    match = re.search(r'Access Point[:\s]+([0-9A-Fa-f:]{17})', iwconfig_output)
    if match:
        current_bssid = match.group(1)
    
    match = re.search(r'Frequency[:\s]+([\d.]+)', iwconfig_output)
    if match:
        current_freq = match.group(1)
    
    print(f"│  Connected SSID: {current_ssid or 'Unknown'}")
    print(f"│  Connected BSSID (MAC): {current_bssid or 'Unknown'}")
    print(f"│  Frequency: {current_freq or 'Unknown'} GHz")
    print("│")
    print("│  ⚠ WRITE DOWN YOUR ROUTER'S MAC ADDRESS")
    print("│  Check the sticker on your router - it should match BSSID above")
    print_end()
    
    evidence['your_network'] = {
        'ssid': current_ssid,
        'bssid': current_bssid,
        'frequency': current_freq
    }
    
    # =========================================================================
    # STEP 2: SCAN FOR ROGUE ACCESS POINTS
    # =========================================================================
    print_section("STEP 2: Scanning for Rogue Access Points (Evil Twin)")
    
    print("│  Scanning... (this takes a few seconds)")
    
    # Scan for all networks
    scan_output = run_cmd("sudo iwlist wlan0 scan 2>/dev/null", timeout=30)
    
    # Parse scan results
    networks = []
    current_network = {}
    
    for line in scan_output.split('\n'):
        line = line.strip()
        
        if 'Cell' in line and 'Address:' in line:
            if current_network:
                networks.append(current_network)
            current_network = {}
            match = re.search(r'Address:\s*([0-9A-Fa-f:]{17})', line)
            if match:
                current_network['bssid'] = match.group(1)
        
        if 'ESSID:"' in line:
            start = line.find('ESSID:"') + 7
            end = line.find('"', start)
            current_network['ssid'] = line[start:end]
        
        if 'Signal level' in line:
            match = re.search(r'Signal level[=:\s]+(-?\d+)', line)
            if match:
                current_network['signal'] = int(match.group(1))
        
        if 'Frequency:' in line:
            match = re.search(r'Frequency[:\s]+([\d.]+)', line)
            if match:
                current_network['frequency'] = match.group(1)
    
    if current_network:
        networks.append(current_network)
    
    # Find networks with same SSID as yours
    same_ssid = [n for n in networks if n.get('ssid') == current_ssid]
    
    if len(same_ssid) > 1:
        print("│")
        print(f"│  🚨 ALERT: Found {len(same_ssid)} networks with SSID '{current_ssid}'!")
        print("│")
        print("│  This could be an EVIL TWIN attack!")
        print("│")
        
        for i, net in enumerate(same_ssid):
            is_connected = net.get('bssid') == current_bssid
            marker = "← YOU ARE HERE" if is_connected else "← SUSPICIOUS"
            print(f"│  Network {i+1}: BSSID {net.get('bssid', 'Unknown')}")
            print(f"│            Signal: {net.get('signal', 'Unknown')} dBm  {marker}")
            print("│")
        
        evidence['findings'].append(f"EVIL TWIN: Found {len(same_ssid)} networks with same SSID")
        evidence['rogue_aps'] = same_ssid
        evidence['recommendations'].append("Verify your router's MAC address matches your connected BSSID")
    else:
        print("│  ✓ Only one network with your SSID found")
    
    print_end()
    
    # =========================================================================
    # STEP 3: CHECK FOR SUSPICIOUS DEVICES
    # =========================================================================
    print_section("STEP 3: Checking for Suspicious Devices on Network")
    
    # ARP scan
    arp_output = run_cmd("sudo arp-scan --localnet 2>/dev/null", timeout=30)
    
    if not arp_output or 'arp-scan' not in arp_output:
        # Fallback to arp -a
        arp_output = run_cmd("arp -a 2>/dev/null")
    
    print("│  Devices on your network:")
    print("│")
    
    devices = []
    suspicious_vendors = ['unknown', 'raspberry', 'espressif', 'chinese', 'shenzhen']
    
    for line in arp_output.split('\n'):
        if re.search(r'([0-9A-Fa-f:]{17})', line):
            match = re.search(r'(\d+\.\d+\.\d+\.\d+).*?([0-9A-Fa-f:]{17})', line)
            if match:
                ip = match.group(1)
                mac = match.group(2)
                vendor = ""
                
                # Check if vendor info in line
                parts = line.split()
                if len(parts) > 2:
                    vendor = ' '.join(parts[2:])[:30]
                
                is_suspicious = any(s in vendor.lower() for s in suspicious_vendors)
                marker = "⚠ CHECK THIS" if is_suspicious else ""
                
                devices.append({'ip': ip, 'mac': mac, 'vendor': vendor})
                print(f"│    {ip:<16} {mac}  {vendor}  {marker}")
    
    print("│")
    print("│  Look for devices you don't recognize!")
    print_end()
    
    evidence['network_devices'] = devices
    
    # =========================================================================
    # STEP 4: CHECK ROUTER SECURITY
    # =========================================================================
    print_section("STEP 4: Router Security Check")
    
    print("│  Manual checks needed:")
    print("│")
    print("│  □ 1. Log into router admin panel (usually 192.168.1.1)")
    print("│  □ 2. Check 'Connected Devices' list for unknowns")
    print("│  □ 3. Check if firmware is up to date")
    print("│  □ 4. Check for 'Remote Management' - should be OFF")
    print("│  □ 5. Change WiFi password if compromised")
    print("│  □ 6. Enable WPA3 if available (or WPA2-AES minimum)")
    print("│")
    
    # Get default gateway
    gateway = run_cmd("ip route | grep default | awk '{print $3}'").strip()
    if gateway:
        print(f"│  Your router admin panel is likely at: http://{gateway}")
    
    print_end()
    
    evidence['recommendations'].append("Check router admin panel for unknown devices")
    evidence['recommendations'].append("Update router firmware")
    evidence['recommendations'].append("Change WiFi password")
    
    # =========================================================================
    # STEP 5: CHECK FOR LOCAL ATTACK TOOLS
    # =========================================================================
    print_section("STEP 5: Checking for Attack Tools Running Locally")
    
    attack_tools = ['aircrack', 'airodump', 'aireplay', 'wifite', 'fluxion', 
                    'hostapd', 'dnsmasq', 'mdk3', 'mdk4', 'reaver', 'bully']
    
    found_tools = []
    
    ps_output = run_cmd("ps aux")
    
    for tool in attack_tools:
        if tool in ps_output.lower():
            found_tools.append(tool)
            print(f"│  🚨 FOUND: {tool} is running!")
    
    if found_tools:
        print("│")
        print("│  ⚠ WiFi attack tools are running on YOUR system!")
        print("│  This could mean your system is compromised.")
        evidence['findings'].append(f"Attack tools running: {found_tools}")
    else:
        print("│  ✓ No known WiFi attack tools running locally")
    
    print_end()
    
    # =========================================================================
    # STEP 6: LIVE MONITORING
    # =========================================================================
    print_section("STEP 6: Live CSI Pattern Monitoring")
    
    print("│  Monitoring WiFi patterns for 10 seconds...")
    print("│")
    
    patterns = []
    
    for i in range(20):
        # Read current WiFi state
        try:
            content = Path('/proc/net/wireless').read_text()
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    rssi = int(float(parts[3].rstrip('.')))
                    quality = float(parts[2].rstrip('.'))
                    noise = int(float(parts[4].rstrip('.'))) if len(parts) >= 5 else 0
                    
                    pattern = f"{rssi}_{noise}_{int(quality)}"
                    patterns.append(pattern)
        except:
            pass
        
        time.sleep(0.5)
    
    # Analyze patterns
    pattern_counts = Counter(patterns)
    unique_patterns = len(pattern_counts)
    total = len(patterns)
    
    print(f"│  Samples collected: {total}")
    print(f"│  Unique patterns: {unique_patterns}")
    print("│")
    print("│  Pattern distribution:")
    
    for pattern, count in pattern_counts.most_common(5):
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"│    {pattern}: {count} times ({pct:.0f}%) {bar}")
    
    print("│")
    
    if unique_patterns < 10 and total > 15:
        print("│  🚨 LOW PATTERN DIVERSITY - REPLAY ATTACK CONFIRMED")
        evidence['findings'].append(f"CSI replay confirmed: only {unique_patterns} patterns in {total} samples")
    else:
        print("│  Pattern diversity appears more normal")
    
    print_end()
    
    evidence['pattern_analysis'] = {
        'total_samples': total,
        'unique_patterns': unique_patterns,
        'pattern_counts': dict(pattern_counts)
    }
    
    # =========================================================================
    # SUMMARY & RECOMMENDATIONS
    # =========================================================================
    print_header("INVESTIGATION SUMMARY")
    
    if evidence['findings']:
        print("  🚨 FINDINGS:")
        for finding in evidence['findings']:
            print(f"     • {finding}")
        print()
    
    print("  📋 RECOMMENDED ACTIONS:")
    print()
    print("  IMMEDIATE:")
    print("     1. Disconnect from WiFi and use mobile data temporarily")
    print("     2. Physically check your router (is it yours? tampered with?)")
    print("     3. Log into router and check for unknown devices")
    print()
    print("  SHORT-TERM:")
    print("     4. Change your WiFi password to something strong")
    print("     5. Update router firmware")
    print("     6. Enable WPA3 or WPA2-AES (disable WPA/WEP)")
    print("     7. Disable WPS (WiFi Protected Setup)")
    print("     8. Disable remote management")
    print()
    print("  IF EVIL TWIN DETECTED:")
    print("     9. Your attacker is nearby (within WiFi range)")
    print("    10. The rogue AP needs power - check for new devices")
    print("    11. Consider contacting authorities if targeted attack")
    print()
    
    # Save evidence
    evidence_file = f"csi_attack_evidence_{int(time.time())}.json"
    with open(evidence_file, 'w') as f:
        json.dump(evidence, f, indent=2)
    
    print(f"  📁 Evidence saved to: {evidence_file}")
    print()
    
    # =========================================================================
    # DEFENSE MODE
    # =========================================================================
    print_header("WANT TO ENABLE DEFENSE MODE?")
    
    print("  Defense options:")
    print()
    print("  1. Switch to 5GHz band (harder to attack)")
    print("  2. MAC address filtering on router")
    print("  3. Use VPN for all traffic")
    print("  4. Set up WiFi monitoring alerts")
    print()
    
    response = input("  Run continuous monitoring? [y/N]: ").strip().lower()
    
    if response == 'y':
        print()
        print("  Starting continuous monitoring...")
        print("  Press Ctrl+C to stop")
        print()
        
        alert_count = 0
        
        try:
            while True:
                # Quick pattern check
                patterns = []
                for i in range(10):
                    try:
                        content = Path('/proc/net/wireless').read_text()
                        for line in content.split('\n')[2:]:
                            parts = line.split()
                            if len(parts) >= 4:
                                rssi = int(float(parts[3].rstrip('.')))
                                pattern = f"{rssi}"
                                patterns.append(pattern)
                    except:
                        pass
                    time.sleep(0.2)
                
                unique = len(set(patterns))
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                if unique < 3 and len(patterns) >= 8:
                    alert_count += 1
                    print(f"  [{timestamp}] 🚨 ALERT #{alert_count}: Replay pattern detected! (unique: {unique})")
                else:
                    print(f"  [{timestamp}] ✓ Normal (unique patterns: {unique})")
                
                time.sleep(2)
                
        except KeyboardInterrupt:
            print()
            print(f"  Monitoring stopped. Total alerts: {alert_count}")


if __name__ == "__main__":
    main()