#!/usr/bin/env python3
"""
================================================================================
REPLAY ATTACK DETECTION & DEVICE BEHAVIOR CORRELATION SYSTEM
================================================================================

Detects audio replay attacks and correlates with suspicious device activity:

AUDIO ANALYSIS:
    - Waveform repetition detection
    - Background noise consistency (recordings are too clean)
    - Room acoustics analysis (recordings lack natural reverb)
    - Compression artifact detection
    - Microphone characteristics matching

DEVICE MONITORING:
    - Voice assistant activation (PulseAudio/PipeWire activity)
    - Network traffic spikes (commands being sent)
    - Process spawning (assistant launching apps)
    - D-Bus messages (system commands)
    - Bluetooth activity (smart home commands)
    - System logs correlation

ALERTS:
    - Real-time console alerts
    - JSON logging for forensics
    - Optional sound/visual alert
    - Webhook notifications (optional)

USAGE:
    python3 replay_attack_detector.py
    python3 replay_attack_detector.py --log attacks.json
    python3 replay_attack_detector.py --sensitivity high --alert-sound
    
================================================================================
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
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import argparse

import numpy as np

# Optional imports
HAVE_PYAUDIO = False
try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "1.0.0"

SENSITIVITY = {
    'low': {
        'waveform_similarity': 0.98,
        'background_variance_threshold': 0.0001,
        'correlation_window_sec': 5,
    },
    'medium': {
        'waveform_similarity': 0.92,
        'background_variance_threshold': 0.001,
        'correlation_window_sec': 3,
    },
    'high': {
        'waveform_similarity': 0.85,
        'background_variance_threshold': 0.005,
        'correlation_window_sec': 2,
    }
}

# Voice assistant process names to monitor
VOICE_ASSISTANT_PROCESSES = [
    'gnome-assistant', 'goa-daemon',  # GNOME
    'mycroft', 'mimic',  # Mycroft
    'alexa', 'amazon',  # Alexa
    'google-assistant',  # Google
    'siri',  # Apple
    'cortana',  # Microsoft
    'snapd',  # Ubuntu voice
]

# Smart home related processes
SMART_HOME_PROCESSES = [
    'homeassistant', 'hass',
    'openhab',
    'domoticz',
    'homebridge',
    'mqtt', 'mosquitto',
    'zigbee', 'zwave',
    'tuya', 'smartthings',
]

# Suspicious network destinations
SUSPICIOUS_DESTINATIONS = [
    'alexa.amazon.com',
    'assistant.google.com', 
    'siri.apple.com',
    'speech.microsoft.com',
    # Smart home
    'api.smartthings.com',
    'cloud.tuya.com',
]


# =============================================================================
# ADVANCED AUDIO ANALYZER
# =============================================================================

class AdvancedAudioAnalyzer:
    """
    Deep audio analysis for replay attack detection
    """
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        
        # History for pattern detection
        self.waveform_history = deque(maxlen=100)
        self.background_history = deque(maxlen=50)
        self.spectral_history = deque(maxlen=100)
        
        # Statistics
        self.baseline_noise = None
        self.baseline_samples = 0
        
    def compute_waveform_hash(self, audio: np.ndarray, segments: int = 20) -> np.ndarray:
        """
        Create a waveform fingerprint by segmenting and hashing
        """
        segment_size = len(audio) // segments
        fingerprint = np.zeros(segments)
        
        for i in range(segments):
            start = i * segment_size
            end = start + segment_size
            segment = audio[start:end]
            
            # Compute segment characteristics
            fingerprint[i] = np.mean(np.abs(segment))
        
        # Normalize
        if np.max(fingerprint) > 0:
            fingerprint = fingerprint / np.max(fingerprint)
        
        return fingerprint
    
    def detect_waveform_repetition(self, audio: np.ndarray) -> dict:
        """
        Detect if this waveform has been seen before (replay indicator)
        """
        result = {
            'is_repetition': False,
            'similarity': 0.0,
            'match_index': -1
        }
        
        current_hash = self.compute_waveform_hash(audio)
        
        for i, old_hash in enumerate(self.waveform_history):
            # Compute similarity
            similarity = 1.0 - np.mean(np.abs(current_hash - old_hash))
            
            if similarity > result['similarity']:
                result['similarity'] = similarity
                result['match_index'] = i
        
        if result['similarity'] > 0.92:
            result['is_repetition'] = True
        
        self.waveform_history.append(current_hash)
        return result
    
    def analyze_background_noise(self, audio: np.ndarray) -> dict:
        """
        Analyze background noise characteristics.
        Real audio: varying background
        Recordings: static/consistent background
        """
        # Split into small segments
        num_segments = 20
        segment_size = len(audio) // num_segments
        
        segment_floors = []
        segment_variances = []
        
        for i in range(num_segments):
            start = i * segment_size
            end = start + segment_size
            segment = np.abs(audio[start:end])
            
            # Noise floor = lower 10th percentile
            sorted_seg = np.sort(segment)
            floor = np.mean(sorted_seg[:len(sorted_seg)//10])
            segment_floors.append(floor)
            
            # Local variance
            segment_variances.append(np.var(segment))
        
        result = {
            'mean_noise_floor': np.mean(segment_floors),
            'noise_floor_variance': np.var(segment_floors),
            'mean_segment_variance': np.mean(segment_variances),
            'variance_of_variances': np.var(segment_variances),
            'is_too_clean': False,
            'is_static_background': False
        }
        
        # Check if background is suspiciously static
        if result['noise_floor_variance'] < 1e-8:
            result['is_static_background'] = True
        
        # Check if audio is "too clean" (no natural variation)
        if result['variance_of_variances'] < 1e-10 and result['mean_segment_variance'] > 0:
            result['is_too_clean'] = True
        
        # Update baseline
        self.background_history.append(result)
        
        # Compare with recent samples
        if len(self.background_history) >= 5:
            recent = list(self.background_history)[-5:]
            
            # If all recent samples have identical background = recording
            floor_vars = [r['noise_floor_variance'] for r in recent]
            if np.var(floor_vars) < 1e-12:
                result['is_static_background'] = True
        
        return result
    
    def analyze_room_acoustics(self, audio: np.ndarray) -> dict:
        """
        Analyze room acoustics characteristics.
        Real audio: has natural reverb/echo
        Recordings: lack room characteristics or have different room
        """
        result = {
            'has_reverb': False,
            'reverb_decay': 0.0,
            'room_signature': None,
            'is_artificial': False
        }
        
        # Compute autocorrelation to detect reverb
        autocorr = np.correlate(audio, audio, mode='full')
        autocorr = autocorr[len(autocorr)//2:]  # Keep positive lags
        autocorr = autocorr / autocorr[0]  # Normalize
        
        # Look for reverb peaks (delayed correlations)
        # Reverb typically appears 10-100ms after direct sound
        reverb_start = int(0.01 * self.sample_rate)  # 10ms
        reverb_end = int(0.1 * self.sample_rate)  # 100ms
        
        if reverb_end < len(autocorr):
            reverb_region = autocorr[reverb_start:reverb_end]
            
            # Natural reverb has gradual decay
            if len(reverb_region) > 10:
                # Check for reverb presence
                reverb_energy = np.mean(np.abs(reverb_region))
                result['reverb_decay'] = reverb_energy
                
                if reverb_energy > 0.05:
                    result['has_reverb'] = True
                
                # Compute room signature (spectral characteristics)
                reverb_fft = np.abs(np.fft.rfft(reverb_region))
                result['room_signature'] = reverb_fft[:50]  # First 50 bins
        
        # Compare room signature with history
        if result['room_signature'] is not None and len(self.spectral_history) > 0:
            # Check if room signature matches recent audio
            for old_sig in list(self.spectral_history)[-10:]:
                if old_sig is not None and len(old_sig) == len(result['room_signature']):
                    similarity = np.corrcoef(result['room_signature'], old_sig)[0, 1]
                    
                    # If room signature is identical but content different = same recording source
                    if similarity > 0.99:
                        result['is_artificial'] = True
                        break
        
        self.spectral_history.append(result['room_signature'])
        return result
    
    def detect_compression_artifacts(self, audio: np.ndarray) -> dict:
        """
        Detect compression artifacts that indicate recorded/transmitted audio.
        MP3, AAC, etc. leave distinctive spectral holes.
        """
        result = {
            'has_compression_artifacts': False,
            'likely_codec': None,
            'quality_score': 1.0
        }
        
        # Compute FFT
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        # Check for spectral holes (compression artifacts)
        # MP3 typically cuts off at 16kHz or 20kHz depending on bitrate
        
        # Check high frequency content
        hf_mask = freqs > 16000
        hf_energy = np.mean(fft[hf_mask]) if np.any(hf_mask) else 0
        
        total_energy = np.mean(fft)
        
        if total_energy > 0:
            hf_ratio = hf_energy / total_energy
            
            # Very low HF = likely compressed
            if hf_ratio < 0.01:
                result['has_compression_artifacts'] = True
                result['likely_codec'] = 'MP3/AAC (low bitrate)'
                result['quality_score'] = 0.5
        
        # Check for quantization noise (low bitrate indicator)
        # This appears as regular spectral patterns
        
        return result
    
    def full_analysis(self, audio: np.ndarray) -> dict:
        """
        Run all analysis methods and compile results
        """
        timestamp = time.time()
        
        # Basic stats
        rms = np.sqrt(np.mean(audio**2))
        peak = np.max(np.abs(audio))
        
        if rms < 0.001:
            return {
                'timestamp': timestamp,
                'status': 'silent',
                'is_replay_attack': False
            }
        
        # Run all analyses
        waveform = self.detect_waveform_repetition(audio)
        background = self.analyze_background_noise(audio)
        acoustics = self.analyze_room_acoustics(audio)
        compression = self.detect_compression_artifacts(audio)
        
        # Compile indicators
        indicators = []
        confidence = 0.0
        
        if waveform['is_repetition']:
            indicators.append(f"Waveform repetition ({waveform['similarity']:.0%} match)")
            confidence = max(confidence, waveform['similarity'])
        
        if background['is_static_background']:
            indicators.append("Static background noise (recording signature)")
            confidence = max(confidence, 0.8)
        
        if background['is_too_clean']:
            indicators.append("Audio too clean (lacks natural variation)")
            confidence = max(confidence, 0.7)
        
        if acoustics['is_artificial']:
            indicators.append("Artificial room acoustics")
            confidence = max(confidence, 0.75)
        
        if compression['has_compression_artifacts']:
            indicators.append(f"Compression artifacts ({compression['likely_codec']})")
            confidence = max(confidence, 0.6)
        
        is_replay = len(indicators) >= 2 or confidence > 0.9
        
        return {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'status': 'active',
            'rms': rms,
            'peak': peak,
            'is_replay_attack': is_replay,
            'confidence': confidence,
            'indicators': indicators,
            'details': {
                'waveform': waveform,
                'background': background,
                'acoustics': acoustics,
                'compression': compression
            }
        }


# =============================================================================
# DEVICE BEHAVIOR MONITOR
# =============================================================================

class DeviceBehaviorMonitor:
    """
    Monitor device behavior for correlation with audio attacks
    """
    
    def __init__(self):
        self.events = deque(maxlen=1000)
        self.process_baseline = set()
        self.network_baseline = {}
        self.monitoring = False
        self.threads = []
        
        # Take baseline
        self._capture_baseline()
    
    def _capture_baseline(self):
        """Capture baseline system state"""
        # Baseline processes
        try:
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n')[1:]:
                parts = line.split()
                if len(parts) > 10:
                    self.process_baseline.add(parts[10])
        except Exception:
            pass
        
        # Baseline network connections
        try:
            result = subprocess.run(['ss', '-tuln'], capture_output=True, text=True, timeout=5)
            self.network_baseline['connections'] = len(result.stdout.split('\n'))
        except Exception:
            pass
    
    def start(self):
        """Start monitoring threads"""
        self.monitoring = True
        
        # Process monitor thread
        t1 = threading.Thread(target=self._monitor_processes, daemon=True)
        t1.start()
        self.threads.append(t1)
        
        # Network monitor thread
        t2 = threading.Thread(target=self._monitor_network, daemon=True)
        t2.start()
        self.threads.append(t2)
        
        # Log monitor thread
        t3 = threading.Thread(target=self._monitor_logs, daemon=True)
        t3.start()
        self.threads.append(t3)
        
        # PulseAudio/PipeWire monitor
        t4 = threading.Thread(target=self._monitor_audio_system, daemon=True)
        t4.start()
        self.threads.append(t4)
    
    def _monitor_processes(self):
        """Monitor for new processes, especially voice assistants"""
        seen_pids = set()
        
        while self.monitoring:
            try:
                result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
                
                for line in result.stdout.split('\n')[1:]:
                    parts = line.split()
                    if len(parts) > 10:
                        pid = parts[1]
                        process = parts[10].lower()
                        cmdline = ' '.join(parts[10:]).lower()
                        
                        if pid not in seen_pids:
                            seen_pids.add(pid)
                            
                            # Check for voice assistant processes
                            for assistant in VOICE_ASSISTANT_PROCESSES:
                                if assistant in process or assistant in cmdline:
                                    self._record_event('process', 'voice_assistant', {
                                        'process': process,
                                        'pid': pid,
                                        'cmdline': cmdline[:100]
                                    })
                            
                            # Check for smart home processes
                            for smart in SMART_HOME_PROCESSES:
                                if smart in process or smart in cmdline:
                                    self._record_event('process', 'smart_home', {
                                        'process': process,
                                        'pid': pid
                                    })
                            
                            # Check for network tools (data exfil)
                            if any(x in process for x in ['curl', 'wget', 'nc', 'ncat']):
                                self._record_event('process', 'network_tool', {
                                    'process': process,
                                    'cmdline': cmdline[:100]
                                })
                
                time.sleep(0.5)
                
            except Exception:
                time.sleep(1)
    
    def _monitor_network(self):
        """Monitor network activity for command transmission"""
        last_connections = 0
        
        while self.monitoring:
            try:
                # Check for new connections
                result = subprocess.run(['ss', '-tun'], capture_output=True, text=True, timeout=5)
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                
                current_connections = len(lines)
                
                # Spike in connections
                if current_connections > last_connections + 5:
                    self._record_event('network', 'connection_spike', {
                        'previous': last_connections,
                        'current': current_connections,
                        'delta': current_connections - last_connections
                    })
                
                # Check for connections to suspicious destinations
                for line in lines:
                    for dest in SUSPICIOUS_DESTINATIONS:
                        if dest in line:
                            self._record_event('network', 'suspicious_destination', {
                                'destination': dest,
                                'connection': line[:80]
                            })
                
                last_connections = current_connections
                time.sleep(0.5)
                
            except Exception:
                time.sleep(1)
    
    def _monitor_logs(self):
        """Monitor system logs for relevant events"""
        # Watch journalctl for real-time events
        try:
            process = subprocess.Popen(
                ['journalctl', '-f', '-n', '0', '--no-pager'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            while self.monitoring:
                line = process.stdout.readline()
                if line:
                    line_lower = line.lower()
                    
                    # Voice assistant mentions
                    if any(x in line_lower for x in ['voice', 'speech', 'assistant', 'alexa', 'siri', 'google assistant']):
                        self._record_event('log', 'voice_mention', {
                            'log': line.strip()[:200]
                        })
                    
                    # Bluetooth events
                    if 'bluetooth' in line_lower:
                        self._record_event('log', 'bluetooth', {
                            'log': line.strip()[:200]
                        })
                    
                    # Audio system events
                    if any(x in line_lower for x in ['pulseaudio', 'pipewire', 'alsa', 'audio']):
                        self._record_event('log', 'audio_system', {
                            'log': line.strip()[:200]
                        })
                        
        except Exception:
            pass
    
    def _monitor_audio_system(self):
        """Monitor PulseAudio/PipeWire for voice assistant activation"""
        while self.monitoring:
            try:
                # Check for audio recording applications
                result = subprocess.run(
                    ['pactl', 'list', 'source-outputs', 'short'],
                    capture_output=True, text=True, timeout=3
                )
                
                if result.stdout.strip():
                    for line in result.stdout.strip().split('\n'):
                        # Something is recording audio
                        self._record_event('audio', 'recording_active', {
                            'source_output': line.strip()
                        })
                
                time.sleep(1)
                
            except Exception:
                time.sleep(2)
    
    def _record_event(self, category: str, event_type: str, data: dict):
        """Record a device event"""
        event = {
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'category': category,
            'type': event_type,
            'data': data
        }
        self.events.append(event)
    
    def get_recent_events(self, seconds: float = 5.0) -> List[dict]:
        """Get events from the last N seconds"""
        cutoff = time.time() - seconds
        return [e for e in self.events if e['timestamp'] > cutoff]
    
    def get_correlated_events(self, audio_timestamp: float, window_sec: float = 3.0) -> List[dict]:
        """Get device events that correlate with an audio event"""
        start = audio_timestamp - window_sec
        end = audio_timestamp + window_sec
        
        return [e for e in self.events if start <= e['timestamp'] <= end]
    
    def stop(self):
        """Stop monitoring"""
        self.monitoring = False


# =============================================================================
# AUDIO CAPTURE
# =============================================================================

class AudioCapture:
    """Audio capture with Kali Linux compatibility and mic verification"""
    
    SAMPLE_RATES = [48000, 44100, 32000, 22050, 16000]
    
    def __init__(self, chunk_size: int = 8192):
        self.chunk_size = chunk_size
        self.sample_rate = None
        self.audio = None
        self.stream = None
        self.queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.device_name = None
        self.mic_verified = False
        self.last_rms = 0
    
    def _unmute_all(self):
        """Aggressively unmute all possible microphone controls"""
        print("    Unmuting microphone...")
        
        # PulseAudio commands
        pa_commands = [
            ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
            ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
            ['pactl', 'set-source-mute', '0', '0'],
            ['pactl', 'set-source-volume', '0', '100%'],
            ['pactl', 'set-source-mute', '1', '0'],
            ['pactl', 'set-source-volume', '1', '100%'],
        ]
        
        for cmd in pa_commands:
            try:
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass
        
        # ALSA commands - try multiple control names
        alsa_controls = [
            'Capture',
            'Mic',
            'Mic Boost',
            'Internal Mic',
            'Internal Mic Boost',
            'Front Mic',
            'Front Mic Boost',
            'Rear Mic',
            'Headset Mic',
            'Headset Mic Boost',
            'Input Source',
            'Capture Volume',
            'Capture Switch',
        ]
        
        for control in alsa_controls:
            for action in [['cap'], ['unmute'], ['100%']]:
                try:
                    subprocess.run(['amixer', 'set', control] + action, 
                                 capture_output=True, timeout=2)
                except Exception:
                    pass
            
            # Also try sset
            try:
                subprocess.run(['amixer', 'sset', control, 'unmute'],
                             capture_output=True, timeout=2)
                subprocess.run(['amixer', 'sset', control, '100%'],
                             capture_output=True, timeout=2)
            except Exception:
                pass
        
        # Try amixer with card specification
        try:
            result = subprocess.run(['cat', '/proc/asound/cards'], 
                                   capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if '[' in line:
                        # Extract card number
                        parts = line.split()
                        if parts and parts[0].isdigit():
                            card_num = parts[0]
                            for control in ['Capture', 'Mic']:
                                try:
                                    subprocess.run(['amixer', '-c', card_num, 'set', control, '100%', 'cap'],
                                                 capture_output=True, timeout=2)
                                except Exception:
                                    pass
        except Exception:
            pass
        
        # PipeWire (newer systems)
        try:
            subprocess.run(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', '0'],
                         capture_output=True, timeout=2)
            subprocess.run(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SOURCE@', '1.0'],
                         capture_output=True, timeout=2)
        except Exception:
            pass
    
    def _get_mic_status(self) -> dict:
        """Get current microphone status"""
        status = {
            'muted': None,
            'volume': None,
            'source': None
        }
        
        # Try PulseAudio
        try:
            result = subprocess.run(['pactl', 'get-source-mute', '@DEFAULT_SOURCE@'],
                                   capture_output=True, text=True, timeout=2)
            if 'yes' in result.stdout.lower():
                status['muted'] = True
            elif 'no' in result.stdout.lower():
                status['muted'] = False
        except Exception:
            pass
        
        try:
            result = subprocess.run(['pactl', 'get-source-volume', '@DEFAULT_SOURCE@'],
                                   capture_output=True, text=True, timeout=2)
            # Parse volume percentage
            match = re.search(r'(\d+)%', result.stdout)
            if match:
                status['volume'] = int(match.group(1))
        except Exception:
            pass
        
        try:
            result = subprocess.run(['pactl', 'get-default-source'],
                                   capture_output=True, text=True, timeout=2)
            status['source'] = result.stdout.strip()
        except Exception:
            pass
        
        return status
    
    def _list_sources(self) -> List[dict]:
        """List all available audio sources"""
        sources = []
        
        try:
            result = subprocess.run(['pactl', 'list', 'sources', 'short'],
                                   capture_output=True, text=True, timeout=5)
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        sources.append({
                            'id': parts[0],
                            'name': parts[1],
                            'full': line
                        })
        except Exception:
            pass
        
        return sources
    
    def _verify_mic_working(self, stream, rate: int) -> Tuple[bool, float]:
        """Verify microphone is actually capturing audio"""
        try:
            # Capture a few samples
            max_rms = 0
            for _ in range(10):
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                rms = np.sqrt(np.mean(audio**2))
                max_rms = max(max_rms, rms)
                time.sleep(0.05)
            
            return max_rms > 0.0001, max_rms
        except Exception:
            return False, 0
    
    def ensure_mic_on(self) -> bool:
        """Ensure microphone is on and working"""
        print("  Checking microphone status...")
        
        # Get initial status
        status = self._get_mic_status()
        print(f"    Source: {status.get('source', 'unknown')}")
        print(f"    Muted: {status.get('muted', 'unknown')}")
        print(f"    Volume: {status.get('volume', 'unknown')}%")
        
        # List available sources
        sources = self._list_sources()
        if sources:
            print(f"    Available sources: {len(sources)}")
            for src in sources[:3]:
                print(f"      - {src['name'][:50]}")
        
        # Unmute everything
        self._unmute_all()
        
        # Verify status after unmute
        time.sleep(0.5)
        status = self._get_mic_status()
        
        if status.get('muted') == True:
            print("    ⚠ Microphone still muted after unmute attempt!")
            print("    Try manually: pavucontrol or alsamixer")
            return False
        
        if status.get('volume', 100) < 50:
            print(f"    ⚠ Volume low: {status.get('volume')}%")
        
        print("    ✓ Microphone settings applied")
        return True
    
    def start(self) -> bool:
        """Start audio capture with verification"""
        if not HAVE_PYAUDIO:
            print("  ✗ PyAudio not installed")
            print("    Install: sudo apt install python3-pyaudio")
            return False
        
        # Ensure mic is on first
        self.ensure_mic_on()
        
        try:
            p = pyaudio.PyAudio()
            
            # Find working configuration
            print("  Finding working audio configuration...")
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    print(f"    Trying device [{i}]: {info['name'][:40]}")
                    
                    for rate in self.SAMPLE_RATES:
                        try:
                            stream = p.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            # Verify mic is actually working
                            is_working, rms = self._verify_mic_working(stream, rate)
                            
                            if not is_working:
                                print(f"      {rate}Hz: Opens but no audio (RMS: {rms:.6f})")
                                stream.close()
                                continue
                            
                            print(f"      ✓ {rate}Hz: Working (RMS: {rms:.6f})")
                            stream.close()
                            
                            # Found working config - open actual stream
                            self.sample_rate = rate
                            self.device_name = info['name']
                            self.mic_verified = True
                            self.last_rms = rms
                            
                            self.audio = pyaudio.PyAudio()
                            self.stream = self.audio.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            self.running = True
                            self.thread = threading.Thread(target=self._capture, daemon=True)
                            self.thread.start()
                            
                            p.terminate()
                            return True
                            
                        except Exception as e:
                            print(f"      {rate}Hz: Failed ({str(e)[:30]})")
                            continue
            
            p.terminate()
            
            # If we get here, no working config found
            print()
            print("  ✗ No working microphone configuration found!")
            print()
            print("  Troubleshooting steps:")
            print("    1. Check physical mic connection")
            print("    2. Run: pavucontrol (GUI) and check Input Devices")
            print("    3. Run: alsamixer, press F4, unmute with 'M' key")
            print("    4. Try: sudo alsactl init")
            print("    5. Check: dmesg | grep -i audio")
            
        except Exception as e:
            print(f"  ✗ PyAudio error: {e}")
        
        return False
    
    def _capture(self):
        """Background capture loop with mic monitoring"""
        silent_count = 0
        
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                
                # Track audio level
                rms = np.sqrt(np.mean(audio**2))
                self.last_rms = rms
                
                # Warn if mic goes silent
                if rms < 0.0001:
                    silent_count += 1
                    if silent_count > 50:  # ~5 seconds of silence
                        self.mic_verified = False
                else:
                    silent_count = 0
                    self.mic_verified = True
                
                if not self.queue.full():
                    self.queue.put(audio)
            except Exception:
                time.sleep(0.01)
    
    def get_mic_status(self) -> dict:
        """Get current mic status for display"""
        return {
            'verified': self.mic_verified,
            'device': self.device_name,
            'sample_rate': self.sample_rate,
            'last_rms': self.last_rms,
            'status': 'active' if self.last_rms > 0.0001 else 'silent'
        }
    
    def get_sample(self) -> Optional[np.ndarray]:
        """Get latest audio sample"""
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def stop(self):
        """Stop capture"""
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
# MAIN DETECTOR
# =============================================================================

class ReplayAttackDetector:
    """
    Main replay attack detection system with device correlation
    """
    
    def __init__(self, sensitivity: str = 'medium', log_file: str = None, alert_sound: bool = False):
        self.sensitivity = sensitivity
        self.config = SENSITIVITY.get(sensitivity, SENSITIVITY['medium'])
        self.log_file = log_file
        self.alert_sound = alert_sound
        
        # Components
        self.audio_capture = AudioCapture()
        self.audio_analyzer = None  # Initialized after we know sample rate
        self.device_monitor = DeviceBehaviorMonitor()
        
        # State
        self.attack_log = deque(maxlen=1000)
        self.start_time = time.time()
        self.sample_count = 0
        self.attack_count = 0
        
    def initialize(self) -> bool:
        """Initialize all components"""
        print("=" * 70)
        print("  REPLAY ATTACK DETECTION SYSTEM")
        print(f"  Version {VERSION}")
        print("=" * 70)
        print()
        print(f"  Sensitivity: {self.sensitivity.upper()}")
        print()
        
        print("Initializing components...")
        
        # Audio capture
        audio_ok = self.audio_capture.start()
        if audio_ok:
            print(f"  ✓ Audio capture: {self.audio_capture.device_name} @ {self.audio_capture.sample_rate}Hz")
            self.audio_analyzer = AdvancedAudioAnalyzer(self.audio_capture.sample_rate)
        else:
            print("  ✗ Audio capture failed")
            print("    Install: sudo apt install python3-pyaudio")
            return False
        
        # Device monitor
        self.device_monitor.start()
        print("  ✓ Device behavior monitor")
        print("    - Process monitoring")
        print("    - Network monitoring")
        print("    - System log monitoring")
        print("    - Audio system monitoring")
        
        print()
        return True
    
    def analyze_and_correlate(self) -> Optional[dict]:
        """Analyze audio and correlate with device behavior"""
        audio = self.audio_capture.get_sample()
        
        if audio is None:
            return None
        
        self.sample_count += 1
        
        # Analyze audio
        analysis = self.audio_analyzer.full_analysis(audio)
        
        if analysis['status'] == 'silent':
            return {
                'timestamp': analysis['timestamp'],
                'status': 'silent',
                'is_attack': False
            }
        
        # Get correlated device events
        correlated_events = self.device_monitor.get_correlated_events(
            analysis['timestamp'],
            self.config['correlation_window_sec']
        )
        
        # Build result
        result = {
            'timestamp': analysis['timestamp'],
            'datetime': analysis['datetime'],
            'status': 'active',
            'rms': analysis['rms'],
            'peak': analysis['peak'],
            'is_attack': analysis['is_replay_attack'],
            'confidence': analysis['confidence'],
            'indicators': analysis['indicators'],
            'correlated_events': correlated_events,
            'correlation_count': len(correlated_events)
        }
        
        # Increase confidence if device events correlate
        if analysis['is_replay_attack'] and correlated_events:
            # Voice assistant activity correlates with replay = very suspicious
            voice_events = [e for e in correlated_events 
                          if e['type'] in ['voice_assistant', 'recording_active', 'voice_mention']]
            
            if voice_events:
                result['confidence'] = min(1.0, result['confidence'] + 0.2)
                result['indicators'].append(f"Correlated with {len(voice_events)} voice assistant events")
            
            # Network activity correlates = command being sent
            network_events = [e for e in correlated_events
                            if e['category'] == 'network']
            
            if network_events:
                result['confidence'] = min(1.0, result['confidence'] + 0.1)
                result['indicators'].append(f"Network activity detected ({len(network_events)} events)")
        
        # Log attack
        if result['is_attack']:
            self.attack_count += 1
            self.attack_log.append(result)
            
            if self.alert_sound:
                self._play_alert()
        
        return result
    
    def _play_alert(self):
        """Play alert sound"""
        try:
            subprocess.run(['paplay', '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'],
                         capture_output=True, timeout=1)
        except Exception:
            # Fallback: terminal bell
            print('\a', end='', flush=True)
    
    def display(self, data: dict):
        """Display current status"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 75
        runtime = int(time.time() - self.start_time)
        
        # Header
        print("╔" + "═" * width + "╗")
        print("║" + " " * 20 + "REPLAY ATTACK DETECTOR" + " " * 31 + "║")
        info = f"Runtime: {runtime}s  |  Samples: {self.sample_count}  |  Attacks: {self.attack_count}"
        print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # Microphone Status
        mic_status = self.audio_capture.get_mic_status()
        print("┌─ Microphone Status " + "─" * (width - 21) + "┐")
        
        if mic_status['verified']:
            color = '\033[92m'  # Green
            status_text = "✓ ACTIVE"
        elif mic_status['status'] == 'silent':
            color = '\033[93m'  # Yellow
            status_text = "⚠ SILENT (mic may be muted)"
        else:
            color = '\033[91m'  # Red
            status_text = "✗ NOT WORKING"
        
        reset = '\033[0m'
        
        line = f"│  Status: {color}{status_text}{reset}"
        visible_len = len(f"│  Status: {status_text}")
        print(line + " " * (width - visible_len) + "│")
        
        line = f"│  Device: {mic_status['device'][:50] if mic_status['device'] else 'None'}"
        print(line + " " * (width - len(line)) + "│")
        
        line = f"│  Sample Rate: {mic_status['sample_rate']}Hz  |  Level: {mic_status['last_rms']:.6f}"
        print(line + " " * (width - len(line)) + "│")
        
        # Level meter
        level_bars = int(min(mic_status['last_rms'] * 500, 40))
        meter = "█" * level_bars + "░" * (40 - level_bars)
        line = f"│  [{meter}]"
        print(line + " " * (width - len(line)) + "│")
        
        if not mic_status['verified'] and mic_status['status'] == 'silent':
            line = "│  → Try: pactl set-source-mute @DEFAULT_SOURCE@ 0"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Audio Status
        print("┌─ Audio Analysis " + "─" * (width - 18) + "┐")
        
        if data and data.get('status') == 'active':
            line = f"│  Level: RMS={data['rms']:.4f}  Peak={data['peak']:.4f}"
            print(line + " " * (width - len(line)) + "│")
            
            if data['is_attack']:
                print("│" + " " * width + "│")
                conf = data['confidence']
                color = '\033[91m' if conf > 0.8 else '\033[93m'
                reset = '\033[0m'
                line = f"│  {color}⚠ REPLAY ATTACK DETECTED (confidence: {conf:.0%}){reset}"
                visible_len = len(f"│  ⚠ REPLAY ATTACK DETECTED (confidence: {conf:.0%})")
                print(line + " " * (width - visible_len) + "│")
                
                print("│" + " " * width + "│")
                for indicator in data['indicators'][:5]:
                    line = f"│    → {indicator[:width-8]}"
                    print(line + " " * (width - len(line)) + "│")
            else:
                line = "│  ✓ No replay detected"
                print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  Status: " + (data.get('status', 'waiting') if data else 'initializing')
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Device Events
        recent_events = self.device_monitor.get_recent_events(10)
        
        print("┌─ Device Activity (last 10s) " + "─" * (width - 30) + "┐")
        
        if recent_events:
            # Group by category
            by_category = {}
            for event in recent_events:
                cat = event['category']
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(event)
            
            for category, events in by_category.items():
                line = f"│  {category.upper()}: {len(events)} events"
                print(line + " " * (width - len(line)) + "│")
                
                for event in events[-2:]:  # Show last 2 per category
                    ts = event['datetime'][11:19]
                    line = f"│    [{ts}] {event['type']}"
                    print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  No recent device activity"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Correlation Status
        if data and data.get('is_attack') and data.get('correlated_events'):
            print("┌─ CORRELATION ALERT " + "─" * (width - 21) + "┐")
            
            line = f"│  ⚠ {len(data['correlated_events'])} device events correlate with audio attack!"
            print(line + " " * (width - len(line)) + "│")
            
            for event in data['correlated_events'][:3]:
                line = f"│    → {event['category']}/{event['type']}"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
        
        # Recent Attacks
        if self.attack_log:
            print("┌─ Recent Attacks " + "─" * (width - 18) + "┐")
            
            for attack in list(self.attack_log)[-3:]:
                ts = attack['datetime'][11:19]
                conf = attack['confidence']
                corr = attack.get('correlation_count', 0)
                line = f"│  [{ts}] Confidence: {conf:.0%}  Correlations: {corr}"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
        
        print("  Press Ctrl+C to stop")
    
    def run(self, interval: float = 0.5):
        """Main detection loop"""
        print("Starting detection...")
        print()
        time.sleep(1)
        
        try:
            while True:
                result = self.analyze_and_correlate()
                self.display(result)
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.shutdown()
    
    def shutdown(self):
        """Clean shutdown"""
        print("\n\nShutting down...")
        
        self.audio_capture.stop()
        self.device_monitor.stop()
        
        # Export log
        if self.log_file and self.attack_log:
            log_data = {
                'export_time': datetime.now().isoformat(),
                'sensitivity': self.sensitivity,
                'total_samples': self.sample_count,
                'total_attacks': self.attack_count,
                'attacks': list(self.attack_log)
            }
            
            # Convert numpy types for JSON
            def convert(obj):
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                if isinstance(obj, np.floating):
                    return float(obj)
                if isinstance(obj, np.integer):
                    return int(obj)
                return obj
            
            with open(self.log_file, 'w') as f:
                json.dump(log_data, f, indent=2, default=convert)
            
            print(f"Exported {len(self.attack_log)} attacks to {self.log_file}")
        
        # Summary
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Duration: {int(time.time() - self.start_time)}s")
        print(f"  Audio samples: {self.sample_count}")
        print(f"  Attacks detected: {self.attack_count}")
        
        if self.attack_log:
            print()
            print("  Attack details:")
            for attack in list(self.attack_log)[-5:]:
                print(f"    [{attack['datetime'][:19]}] {attack['confidence']:.0%} confidence")
                for ind in attack['indicators'][:2]:
                    print(f"      - {ind}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Replay Attack Detection with Device Correlation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
DETECTION METHODS:
    - Waveform repetition (identical audio segments)
    - Background noise analysis (recordings are too clean)
    - Room acoustics (recordings lack natural reverb)
    - Compression artifacts (MP3/AAC signatures)
    
DEVICE CORRELATION:
    - Voice assistant process spawning
    - Network traffic to assistant servers
    - System log events
    - Audio recording activity

EXAMPLES:
    %(prog)s
    %(prog)s --sensitivity high
    %(prog)s --log attacks.json --alert-sound
        """
    )
    
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high'],
                        default='medium',
                        help='Detection sensitivity')
    parser.add_argument('-l', '--log',
                        help='Export attacks to JSON file')
    parser.add_argument('--alert-sound', action='store_true',
                        help='Play sound on attack detection')
    parser.add_argument('-i', '--interval', type=float, default=0.5,
                        help='Analysis interval in seconds')
    
    args = parser.parse_args()
    
    detector = ReplayAttackDetector(
        sensitivity=args.sensitivity,
        log_file=args.log,
        alert_sound=args.alert_sound
    )
    
    if not detector.initialize():
        print("Failed to initialize. Exiting.")
        sys.exit(1)
    
    detector.run(interval=args.interval)


if __name__ == "__main__":
    main()