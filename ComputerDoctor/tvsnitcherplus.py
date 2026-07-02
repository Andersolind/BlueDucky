#!/usr/bin/env python3
"""
================================================================================
CSI/WiFi DEEP ANALYSIS TOOL
================================================================================

Investigates CSI injection/replay attacks by analyzing:
- WiFi signal patterns
- RSSI changes over time
- Packet timing analysis
- CSI pattern repetition
- Physics plausibility

Run this when you see high CSI/WiFi alerts to understand what's happening.

USAGE:
    python3 csi_deep_analysis.py
    python3 csi_deep_analysis.py --duration 60
    python3 csi_deep_analysis.py --log csi_analysis.json

================================================================================
"""

import os
import sys
import time
import json
import subprocess
import hashlib
import re
from collections import deque, Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import argparse

import numpy as np


# =============================================================================
# CSI DATA COLLECTOR
# =============================================================================

class CSIDataCollector:
    """Collects and analyzes WiFi/CSI data"""
    
    def __init__(self):
        self.interface = self._find_interface()
        self.history = deque(maxlen=1000)
        self.rssi_history = deque(maxlen=500)
        self.packet_history = deque(maxlen=500)
        self.pattern_hashes = deque(maxlen=1000)
        
        # Baselines
        self.rssi_baseline = None
        self.packet_rate_baseline = None
        
        # Detection counters
        self.replay_count = 0
        self.anomaly_count = 0
        
    def _find_interface(self) -> Optional[str]:
        """Find wireless interface"""
        try:
            content = Path('/proc/net/wireless').read_text()
            for line in content.split('\n')[2:]:
                if line.strip():
                    return line.split()[0].rstrip(':')
        except Exception:
            pass
        
        try:
            for iface in Path('/sys/class/net').iterdir():
                if (iface / 'wireless').exists():
                    return iface.name
        except Exception:
            pass
        
        return None
    
    def collect(self) -> dict:
        """Collect current WiFi/CSI data"""
        data = {
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'interface': self.interface,
            'rssi': None,
            'noise': None,
            'link_quality': None,
            'rx_packets': None,
            'tx_packets': None,
            'rx_bytes': None,
            'tx_bytes': None,
            'ssid': None,
            'bssid': None,
            'frequency': None,
            'channel': None,
            'bitrate': None,
            'signal_pattern': None,
        }
        
        # Read from /proc/net/wireless
        try:
            content = Path('/proc/net/wireless').read_text()
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    data['link_quality'] = float(parts[2].rstrip('.'))
                    data['rssi'] = int(float(parts[3].rstrip('.')))
                    if len(parts) >= 5:
                        data['noise'] = int(float(parts[4].rstrip('.')))
        except Exception:
            pass
        
        # Read packet counts
        try:
            content = Path('/proc/net/dev').read_text()
            for line in content.split('\n'):
                if self.interface and self.interface in line:
                    parts = line.split()
                    if len(parts) >= 10:
                        data['rx_bytes'] = int(parts[1])
                        data['rx_packets'] = int(parts[2])
                        data['tx_bytes'] = int(parts[9])
                        data['tx_packets'] = int(parts[10])
        except Exception:
            pass
        
        # Get detailed info from iwconfig
        try:
            result = subprocess.run(['iwconfig', self.interface or ''],
                                  capture_output=True, text=True, timeout=2)
            output = result.stdout
            
            # SSID
            if 'ESSID:"' in output:
                start = output.find('ESSID:"') + 7
                end = output.find('"', start)
                if end > start:
                    data['ssid'] = output[start:end]
            
            # Frequency
            match = re.search(r'Frequency[:\s]+([\d.]+)\s*GHz', output)
            if match:
                data['frequency'] = float(match.group(1))
                # Calculate channel
                freq_mhz = data['frequency'] * 1000
                if freq_mhz > 5000:
                    data['channel'] = int((freq_mhz - 5000) / 5)
                else:
                    data['channel'] = int((freq_mhz - 2407) / 5)
            
            # Bit Rate
            match = re.search(r'Bit Rate[=:\s]+([\d.]+)\s*Mb/s', output)
            if match:
                data['bitrate'] = float(match.group(1))
            
            # Access Point (BSSID)
            match = re.search(r'Access Point[:\s]+([0-9A-Fa-f:]{17})', output)
            if match:
                data['bssid'] = match.group(1)
                
        except Exception:
            pass
        
        # Create signal pattern hash
        if data['rssi'] is not None:
            pattern = f"{data['rssi']}_{data.get('noise', 0)}_{data.get('link_quality', 0)}"
            data['signal_pattern'] = hashlib.md5(pattern.encode()).hexdigest()[:8]
        
        return data
    
    def analyze(self, data: dict) -> dict:
        """Analyze collected data for anomalies"""
        analysis = {
            'timestamp': data['timestamp'],
            'is_anomaly': False,
            'is_replay': False,
            'confidence': 0.0,
            'issues': [],
            'metrics': {}
        }
        
        if data['rssi'] is None:
            analysis['issues'].append("No WiFi signal detected")
            return analysis
        
        # Store history
        self.history.append(data)
        self.rssi_history.append({
            'rssi': data['rssi'],
            'timestamp': data['timestamp']
        })
        
        if data['rx_packets']:
            self.packet_history.append({
                'packets': data['rx_packets'],
                'timestamp': data['timestamp']
            })
        
        # === Analysis 1: RSSI Pattern Replay ===
        if data['signal_pattern']:
            pattern = data['signal_pattern']
            
            # Count how many times we've seen this exact pattern
            pattern_count = sum(1 for h in self.history if h.get('signal_pattern') == pattern)
            
            if pattern_count > 5:
                analysis['issues'].append(f"Signal pattern repeated {pattern_count} times")
                analysis['confidence'] = max(analysis['confidence'], min(pattern_count / 10, 0.9))
                
                if pattern_count > 10:
                    analysis['is_replay'] = True
                    self.replay_count += 1
        
        # === Analysis 2: RSSI Stability (Too Stable = Suspicious) ===
        if len(self.rssi_history) >= 20:
            recent_rssi = [r['rssi'] for r in list(self.rssi_history)[-20:]]
            rssi_std = np.std(recent_rssi)
            rssi_mean = np.mean(recent_rssi)
            
            analysis['metrics']['rssi_std'] = float(rssi_std)
            analysis['metrics']['rssi_mean'] = float(rssi_mean)
            
            # Natural WiFi has some variation (0.5-5 dB typically)
            if rssi_std < 0.1:
                analysis['issues'].append(f"RSSI suspiciously stable (std={rssi_std:.3f})")
                analysis['confidence'] = max(analysis['confidence'], 0.7)
                analysis['is_anomaly'] = True
            elif rssi_std < 0.5:
                analysis['issues'].append(f"RSSI very stable (std={rssi_std:.2f})")
                analysis['confidence'] = max(analysis['confidence'], 0.5)
        
        # === Analysis 3: RSSI Sudden Changes ===
        if len(self.rssi_history) >= 2:
            prev = self.rssi_history[-2]
            curr = self.rssi_history[-1]
            
            rssi_change = abs(curr['rssi'] - prev['rssi'])
            time_delta = curr['timestamp'] - prev['timestamp']
            
            if time_delta > 0:
                change_rate = rssi_change / time_delta
                analysis['metrics']['rssi_change_rate'] = float(change_rate)
                
                # >20 dB/sec is physically impossible without teleportation
                if change_rate > 20:
                    analysis['issues'].append(f"Impossible RSSI change: {rssi_change}dB in {time_delta:.2f}s")
                    analysis['confidence'] = max(analysis['confidence'], 0.95)
                    analysis['is_anomaly'] = True
                    self.anomaly_count += 1
                elif change_rate > 10:
                    analysis['issues'].append(f"Suspicious RSSI change: {rssi_change}dB in {time_delta:.2f}s")
                    analysis['confidence'] = max(analysis['confidence'], 0.6)
        
        # === Analysis 4: Packet Rate Analysis ===
        if len(self.packet_history) >= 2:
            prev = self.packet_history[-2]
            curr = self.packet_history[-1]
            
            packet_delta = curr['packets'] - prev['packets']
            time_delta = curr['timestamp'] - prev['timestamp']
            
            if time_delta > 0:
                packet_rate = packet_delta / time_delta
                analysis['metrics']['packet_rate'] = float(packet_rate)
                
                # Establish baseline
                if self.packet_rate_baseline is None and len(self.packet_history) > 10:
                    rates = []
                    ph = list(self.packet_history)
                    for i in range(1, len(ph)):
                        dt = ph[i]['timestamp'] - ph[i-1]['timestamp']
                        if dt > 0:
                            rates.append((ph[i]['packets'] - ph[i-1]['packets']) / dt)
                    if rates:
                        self.packet_rate_baseline = np.mean(rates)
                
                # Check for anomalies
                if self.packet_rate_baseline and self.packet_rate_baseline > 0:
                    ratio = packet_rate / self.packet_rate_baseline
                    
                    if ratio > 10:
                        analysis['issues'].append(f"Packet rate spike: {ratio:.1f}x baseline")
                        analysis['confidence'] = max(analysis['confidence'], 0.6)
                    elif ratio < 0.1 and packet_rate > 0:
                        analysis['issues'].append(f"Packet rate drop: {ratio:.2f}x baseline")
                        analysis['confidence'] = max(analysis['confidence'], 0.4)
        
        # === Analysis 5: Timing Regularity ===
        if len(self.history) >= 20:
            recent = list(self.history)[-20:]
            intervals = []
            for i in range(1, len(recent)):
                intervals.append(recent[i]['timestamp'] - recent[i-1]['timestamp'])
            
            if intervals:
                interval_std = np.std(intervals)
                interval_mean = np.mean(intervals)
                
                analysis['metrics']['timing_std'] = float(interval_std)
                
                # Check for machine-like regularity in the WiFi data itself
                # (not our sampling, but the underlying data changes)
                rssi_changes = []
                for i in range(1, len(recent)):
                    if recent[i]['rssi'] and recent[i-1]['rssi']:
                        rssi_changes.append(abs(recent[i]['rssi'] - recent[i-1]['rssi']))
                
                if rssi_changes:
                    change_std = np.std(rssi_changes)
                    if change_std < 0.01 and np.mean(rssi_changes) > 0:
                        analysis['issues'].append("RSSI changes are unnaturally regular")
                        analysis['confidence'] = max(analysis['confidence'], 0.7)
                        analysis['is_anomaly'] = True
        
        # Final decision
        if analysis['confidence'] > 0.7:
            analysis['is_anomaly'] = True
        
        return analysis
    
    def get_summary(self) -> dict:
        """Get analysis summary"""
        if not self.history:
            return {'error': 'No data collected'}
        
        rssi_values = [h['rssi'] for h in self.history if h['rssi'] is not None]
        
        return {
            'samples': len(self.history),
            'duration_sec': self.history[-1]['timestamp'] - self.history[0]['timestamp'] if len(self.history) > 1 else 0,
            'interface': self.interface,
            'ssid': self.history[-1].get('ssid'),
            'bssid': self.history[-1].get('bssid'),
            'channel': self.history[-1].get('channel'),
            'rssi_stats': {
                'min': min(rssi_values) if rssi_values else None,
                'max': max(rssi_values) if rssi_values else None,
                'mean': float(np.mean(rssi_values)) if rssi_values else None,
                'std': float(np.std(rssi_values)) if rssi_values else None,
            },
            'replay_detections': self.replay_count,
            'anomaly_detections': self.anomaly_count,
            'unique_patterns': len(set(h.get('signal_pattern') for h in self.history if h.get('signal_pattern'))),
        }


# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='CSI/WiFi Deep Analysis Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
WHAT THIS TOOL DETECTS:

  1. RSSI Pattern Replay
     Same signal pattern repeating = recorded data being replayed

  2. Suspiciously Stable RSSI  
     Natural WiFi varies 0.5-5dB. Zero variation = fake/replayed

  3. Impossible RSSI Changes
     >20dB/second change is physically impossible = injection

  4. Packet Rate Anomalies
     Sudden spikes or drops in packet rate

  5. Timing Regularity
     Machine-like regular changes = synthetic data

EXAMPLES:
    %(prog)s                    # Quick 30-second analysis
    %(prog)s --duration 120     # 2-minute deep analysis
    %(prog)s --log results.json # Save results
        """
    )
    
    parser.add_argument('-d', '--duration', type=int, default=30,
                        help='Analysis duration in seconds (default: 30)')
    parser.add_argument('-i', '--interval', type=float, default=0.2,
                        help='Sampling interval in seconds')
    parser.add_argument('-l', '--log', help='Save results to JSON file')
    parser.add_argument('--continuous', action='store_true',
                        help='Run continuously until Ctrl+C')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("  CSI/WiFi DEEP ANALYSIS TOOL")
    print("=" * 70)
    print()
    
    collector = CSIDataCollector()
    
    if not collector.interface:
        print("  ✗ No wireless interface found!")
        sys.exit(1)
    
    print(f"  Interface: {collector.interface}")
    
    # Initial data
    initial = collector.collect()
    print(f"  SSID: {initial.get('ssid', 'N/A')}")
    print(f"  BSSID: {initial.get('bssid', 'N/A')}")
    print(f"  Channel: {initial.get('channel', 'N/A')}")
    print(f"  Initial RSSI: {initial.get('rssi', 'N/A')} dBm")
    print()
    
    if args.continuous:
        print("  Running continuously. Press Ctrl+C to stop.")
    else:
        print(f"  Analyzing for {args.duration} seconds...")
    print()
    
    start_time = time.time()
    sample_count = 0
    anomaly_log = []
    
    try:
        while True:
            # Check duration
            elapsed = time.time() - start_time
            if not args.continuous and elapsed >= args.duration:
                break
            
            # Collect and analyze
            data = collector.collect()
            analysis = collector.analyze(data)
            sample_count += 1
            
            # Display
            os.system('clear' if os.name != 'nt' else 'cls')
            
            width = 70
            
            print("╔" + "═" * width + "╗")
            print("║" + " " * 20 + "CSI/WiFi DEEP ANALYSIS" + " " * 26 + "║")
            info = f"Elapsed: {elapsed:.0f}s  |  Samples: {sample_count}"
            print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
            print("╚" + "═" * width + "╝")
            print()
            
            # Current readings
            print("┌─ Current Readings " + "─" * (width - 20) + "┐")
            line = f"│  RSSI: {data.get('rssi', 'N/A')} dBm  |  Noise: {data.get('noise', 'N/A')} dBm"
            print(line + " " * (width - len(line)) + "│")
            line = f"│  Link Quality: {data.get('link_quality', 'N/A')}  |  Bitrate: {data.get('bitrate', 'N/A')} Mb/s"
            print(line + " " * (width - len(line)) + "│")
            line = f"│  RX Packets: {data.get('rx_packets', 'N/A')}  |  TX Packets: {data.get('tx_packets', 'N/A')}"
            print(line + " " * (width - len(line)) + "│")
            line = f"│  Pattern Hash: {data.get('signal_pattern', 'N/A')}"
            print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
            
            # Analysis metrics
            print("┌─ Analysis Metrics " + "─" * (width - 20) + "┐")
            metrics = analysis.get('metrics', {})
            
            if 'rssi_std' in metrics:
                std = metrics['rssi_std']
                status = "⚠ SUSPICIOUS" if std < 0.5 else "✓ Normal"
                line = f"│  RSSI Stability: std={std:.3f} ({status})"
                print(line + " " * (width - len(line)) + "│")
            
            if 'rssi_change_rate' in metrics:
                rate = metrics['rssi_change_rate']
                status = "⚠ SUSPICIOUS" if rate > 10 else "✓ Normal"
                line = f"│  RSSI Change Rate: {rate:.1f} dB/s ({status})"
                print(line + " " * (width - len(line)) + "│")
            
            if 'packet_rate' in metrics:
                rate = metrics['packet_rate']
                line = f"│  Packet Rate: {rate:.1f} pkt/s"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
            
            # Detection status
            print("┌─ Detection Status " + "─" * (width - 20) + "┐")
            
            if analysis['is_anomaly'] or analysis['is_replay']:
                color = '\033[91m'
                reset = '\033[0m'
                
                if analysis['is_replay']:
                    line = f"│  {color}⚠ CSI REPLAY DETECTED{reset} (confidence: {analysis['confidence']:.0%})"
                    visible = f"│  ⚠ CSI REPLAY DETECTED (confidence: {analysis['confidence']:.0%})"
                else:
                    line = f"│  {color}⚠ ANOMALY DETECTED{reset} (confidence: {analysis['confidence']:.0%})"
                    visible = f"│  ⚠ ANOMALY DETECTED (confidence: {analysis['confidence']:.0%})"
                
                print(line + " " * (width - len(visible)) + "│")
                
                print("│" + " " * width + "│")
                for issue in analysis['issues'][:5]:
                    line = f"│  → {issue[:width-6]}"
                    print(line + " " * (width - len(line)) + "│")
                
                # Log anomaly
                anomaly_log.append({
                    'timestamp': analysis['timestamp'],
                    'confidence': analysis['confidence'],
                    'issues': analysis['issues'],
                    'is_replay': analysis['is_replay']
                })
            else:
                line = "│  ✓ No anomalies detected"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
            
            # Statistics
            summary = collector.get_summary()
            print("┌─ Session Statistics " + "─" * (width - 22) + "┐")
            line = f"│  Replay Detections: {summary['replay_detections']}  |  Anomaly Detections: {summary['anomaly_detections']}"
            print(line + " " * (width - len(line)) + "│")
            line = f"│  Unique Patterns: {summary['unique_patterns']}  |  Total Samples: {summary['samples']}"
            print(line + " " * (width - len(line)) + "│")
            
            if summary['rssi_stats']['std'] is not None:
                line = f"│  RSSI Range: {summary['rssi_stats']['min']} to {summary['rssi_stats']['max']} dBm (std: {summary['rssi_stats']['std']:.2f})"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
            
            # Interpretation
            print("┌─ What This Means " + "─" * (width - 19) + "┐")
            
            if summary['replay_detections'] > 0:
                line = "│  ⚠ REPLAY: Same signal patterns repeating - possible recorded data"
                print(line + " " * (width - len(line)) + "│")
            
            if summary['rssi_stats']['std'] is not None:
                std = summary['rssi_stats']['std']
                if std < 0.1:
                    line = "│  ⚠ STABLE: RSSI too stable - natural WiFi varies more"
                    print(line + " " * (width - len(line)) + "│")
                elif std < 0.5:
                    line = "│  ⚠ SUSPICIOUS: RSSI variation lower than normal"
                    print(line + " " * (width - len(line)) + "│")
                else:
                    line = "│  ✓ RSSI variation appears natural"
                    print(line + " " * (width - len(line)) + "│")
            
            if summary['anomaly_detections'] == 0 and summary['replay_detections'] == 0:
                line = "│  ✓ No signs of CSI injection or replay detected"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
            
            if not args.continuous:
                remaining = args.duration - elapsed
                print(f"  {remaining:.0f}s remaining... (Ctrl+C to stop early)")
            else:
                print("  Running continuously... (Ctrl+C to stop)")
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        pass
    
    # Final summary
    print("\n")
    print("=" * 70)
    print("  FINAL ANALYSIS SUMMARY")
    print("=" * 70)
    print()
    
    summary = collector.get_summary()
    
    print(f"  Duration: {summary['duration_sec']:.1f} seconds")
    print(f"  Samples: {summary['samples']}")
    print(f"  Interface: {summary['interface']}")
    print(f"  SSID: {summary['ssid']}")
    print()
    
    print("  RSSI Statistics:")
    print(f"    Min: {summary['rssi_stats']['min']} dBm")
    print(f"    Max: {summary['rssi_stats']['max']} dBm")
    print(f"    Mean: {summary['rssi_stats']['mean']:.1f} dBm")
    print(f"    Std Dev: {summary['rssi_stats']['std']:.3f} dBm")
    print()
    
    print("  Detection Results:")
    print(f"    Replay Detections: {summary['replay_detections']}")
    print(f"    Anomaly Detections: {summary['anomaly_detections']}")
    print(f"    Unique Signal Patterns: {summary['unique_patterns']}")
    print()
    
    # Verdict
    print("  VERDICT:")
    if summary['replay_detections'] > 5:
        print("    ⚠ HIGH CONFIDENCE: CSI replay attack likely occurring")
        print("    → Signal patterns are repeating abnormally")
    elif summary['anomaly_detections'] > 5:
        print("    ⚠ SUSPICIOUS: Multiple anomalies detected")
        print("    → Investigate WiFi environment")
    elif summary['rssi_stats']['std'] is not None and summary['rssi_stats']['std'] < 0.1:
        print("    ⚠ SUSPICIOUS: RSSI is unnaturally stable")
        print("    → Natural WiFi varies more - possible injection")
    else:
        print("    ✓ No clear signs of CSI injection or replay")
    
    print()
    
    # Save log
    if args.log:
        log_data = {
            'analysis_time': datetime.now().isoformat(),
            'duration_sec': summary['duration_sec'],
            'summary': summary,
            'anomalies': anomaly_log,
            'verdict': {
                'replay_detected': summary['replay_detections'] > 5,
                'anomalies_detected': summary['anomaly_detections'] > 5,
                'suspicious_stability': summary['rssi_stats']['std'] < 0.1 if summary['rssi_stats']['std'] else False
            }
        }
        
        with open(args.log, 'w') as f:
            json.dump(log_data, f, indent=2)
        
        print(f"  Results saved to: {args.log}")
        print()


if __name__ == "__main__":
    main()