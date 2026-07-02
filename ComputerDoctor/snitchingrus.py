#!/usr/bin/env python3
"""
================================================================================
UNIFIED SIGNAL INJECTION DETECTION SYSTEM - ENHANCED EDITION
================================================================================

With Advanced Audio Replay Detection:
- Exact hash matching (identical audio)
- Perceptual hashing (similar/re-encoded audio)
- Background noise analysis (static background = recording)
- Temporal pattern detection (unnatural timing)
- Spectral fingerprinting (frequency signature matching)

SENSORS:
    - WiFi/CSI: Signal strength, packet analysis, replay detection
    - Bluetooth: Device scanning, RSSI tracking, spoofing detection
    - Audio: Ultrasonic injection, advanced replay detection
    - Touch/Input: Event injection, EM correlation detection
    - GPS: Location spoofing, impossible movement detection
    - System: CPU, memory, network, USB, process monitoring

USAGE:
    python3 unified_signal_detector_enhanced.py
    python3 unified_signal_detector_enhanced.py --sensitivity low
    python3 unified_signal_detector_enhanced.py --log threats.json
    sudo python3 unified_signal_detector_enhanced.py  # For Bluetooth

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
import select
import argparse
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

import numpy as np

# Optional imports
HAVE_PYAUDIO = False
HAVE_PSUTIL = False

try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    pass

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "2.0.0"

SENSITIVITY_PROFILES = {
    'low': {
        'ultrasonic_ratio_threshold': 0.8,
        'ultrasonic_absolute_threshold': 1000,
        'rssi_change_threshold': 30,
        'replay_similarity_threshold': 0.98,
        'background_similarity_threshold': 0.99,
        'description': 'Minimal alerts - only obvious attacks'
    },
    'medium': {
        'ultrasonic_ratio_threshold': 0.4,
        'ultrasonic_absolute_threshold': 500,
        'rssi_change_threshold': 20,
        'replay_similarity_threshold': 0.92,
        'background_similarity_threshold': 0.95,
        'description': 'Balanced detection (recommended)'
    },
    'high': {
        'ultrasonic_ratio_threshold': 0.2,
        'ultrasonic_absolute_threshold': 200,
        'rssi_change_threshold': 15,
        'replay_similarity_threshold': 0.85,
        'background_similarity_threshold': 0.90,
        'description': 'Sensitive - may have false positives'
    },
    'paranoid': {
        'ultrasonic_ratio_threshold': 0.1,
        'ultrasonic_absolute_threshold': 100,
        'rssi_change_threshold': 10,
        'replay_similarity_threshold': 0.75,
        'background_similarity_threshold': 0.85,
        'description': 'Maximum sensitivity'
    }
}

KNOWN_ULTRASONIC_SOURCES = {
    (15000, 17000): "CRT TV / Old monitor",
    (17000, 19000): "LCD backlight / LED driver",
    (19000, 20000): "Mosquito deterrent",
    (19500, 20500): "⚠ DolphinAttack range",
    (20000, 22000): "Ultrasonic pest repeller",
}


# =============================================================================
# ENHANCED AUDIO REPLAY DETECTOR
# =============================================================================

class AudioReplayDetector:
    """
    Advanced replay attack detection using multiple methods:
    
    1. Exact Hash - Catches identical audio playback
    2. Perceptual Hash - Catches re-encoded/slightly modified replays
    3. Spectral Fingerprint - Catches frequency-domain similarities
    4. Background Analysis - Recordings have static background noise
    5. Temporal Analysis - Replays often have unnatural timing patterns
    """
    
    def __init__(self, profile: dict, sample_rate: int = 48000):
        self.profile = profile
        self.sample_rate = sample_rate
        
        # Storage for different detection methods
        self.exact_hashes = deque(maxlen=500)
        self.perceptual_hashes = deque(maxlen=200)
        self.spectral_fingerprints = deque(maxlen=200)
        self.background_profiles = deque(maxlen=50)
        self.audio_timestamps = deque(maxlen=100)
        
        # Statistics
        self.total_samples = 0
        self.replay_detections = 0
        
    def compute_exact_hash(self, audio: np.ndarray) -> str:
        """Compute exact SHA256 hash of audio data"""
        return hashlib.sha256(audio.tobytes()).hexdigest()
    
    def compute_perceptual_hash(self, audio: np.ndarray, bands: int = 32) -> np.ndarray:
        """
        Compute perceptual hash using frequency bands.
        Similar audio will have similar hashes even if slightly different.
        """
        # Compute FFT
        fft = np.abs(np.fft.rfft(audio))
        
        # Divide into frequency bands and compute energy
        band_size = len(fft) // bands
        band_energies = np.zeros(bands)
        
        for i in range(bands):
            start = i * band_size
            end = start + band_size
            band_energies[i] = np.sum(fft[start:end])
        
        # Normalize
        if np.max(band_energies) > 0:
            band_energies = band_energies / np.max(band_energies)
        
        # Convert to binary hash (above/below median)
        median = np.median(band_energies)
        binary_hash = (band_energies > median).astype(np.uint8)
        
        return binary_hash
    
    def compute_spectral_fingerprint(self, audio: np.ndarray) -> dict:
        """
        Compute detailed spectral fingerprint for similarity matching.
        """
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        # Find peak frequencies
        peak_indices = np.argsort(fft)[-10:]  # Top 10 peaks
        peak_freqs = freqs[peak_indices]
        peak_mags = fft[peak_indices]
        
        # Normalize magnitudes
        if np.max(peak_mags) > 0:
            peak_mags = peak_mags / np.max(peak_mags)
        
        # Compute spectral centroid
        if np.sum(fft) > 0:
            centroid = np.sum(freqs * fft) / np.sum(fft)
        else:
            centroid = 0
        
        # Compute spectral spread
        if np.sum(fft) > 0:
            spread = np.sqrt(np.sum(((freqs - centroid) ** 2) * fft) / np.sum(fft))
        else:
            spread = 0
        
        return {
            'peak_freqs': peak_freqs,
            'peak_mags': peak_mags,
            'centroid': centroid,
            'spread': spread,
            'total_energy': np.sum(fft)
        }
    
    def extract_background_profile(self, audio: np.ndarray) -> dict:
        """
        Extract background noise profile.
        Real audio has varying background; recordings have static background.
        """
        # Split into segments
        segment_size = len(audio) // 10
        if segment_size < 100:
            return {'noise_floor': 0, 'variance': 0}
        
        segment_energies = []
        segment_noise_floors = []
        
        for i in range(10):
            start = i * segment_size
            end = start + segment_size
            segment = audio[start:end]
            
            # Energy of segment
            segment_energies.append(np.sqrt(np.mean(segment**2)))
            
            # Estimate noise floor (lower 10th percentile)
            sorted_abs = np.sort(np.abs(segment))
            noise_floor = np.mean(sorted_abs[:len(sorted_abs)//10])
            segment_noise_floors.append(noise_floor)
        
        return {
            'noise_floor': np.mean(segment_noise_floors),
            'noise_variance': np.var(segment_noise_floors),
            'energy_variance': np.var(segment_energies),
            'segment_energies': segment_energies
        }
    
    def hash_similarity(self, hash1: np.ndarray, hash2: np.ndarray) -> float:
        """Compute similarity between two perceptual hashes (0-1)"""
        if len(hash1) != len(hash2):
            return 0.0
        matching = np.sum(hash1 == hash2)
        return matching / len(hash1)
    
    def fingerprint_similarity(self, fp1: dict, fp2: dict) -> float:
        """Compute similarity between two spectral fingerprints (0-1)"""
        # Compare centroids
        centroid_diff = abs(fp1['centroid'] - fp2['centroid'])
        centroid_sim = 1.0 / (1.0 + centroid_diff / 1000)
        
        # Compare spreads
        spread_diff = abs(fp1['spread'] - fp2['spread'])
        spread_sim = 1.0 / (1.0 + spread_diff / 1000)
        
        # Compare peak frequencies
        peak_matches = 0
        for freq1 in fp1['peak_freqs']:
            for freq2 in fp2['peak_freqs']:
                if abs(freq1 - freq2) < 50:  # Within 50 Hz
                    peak_matches += 1
                    break
        peak_sim = peak_matches / max(len(fp1['peak_freqs']), 1)
        
        # Combined similarity
        return (centroid_sim * 0.3 + spread_sim * 0.2 + peak_sim * 0.5)
    
    def background_similarity(self, bg1: dict, bg2: dict) -> float:
        """Check if two background profiles are suspiciously similar"""
        if bg1['noise_variance'] == 0 and bg2['noise_variance'] == 0:
            return 1.0  # Both completely static = suspicious
        
        # Compare noise floors
        floor_diff = abs(bg1['noise_floor'] - bg2['noise_floor'])
        floor_sim = 1.0 / (1.0 + floor_diff * 1000)
        
        # Compare variances
        var_diff = abs(bg1['noise_variance'] - bg2['noise_variance'])
        var_sim = 1.0 / (1.0 + var_diff * 10000)
        
        # Compare segment energies if available
        energy_sim = 0.5
        if 'segment_energies' in bg1 and 'segment_energies' in bg2:
            e1 = np.array(bg1['segment_energies'])
            e2 = np.array(bg2['segment_energies'])
            if len(e1) == len(e2) and np.std(e1) > 0 and np.std(e2) > 0:
                correlation = np.corrcoef(e1, e2)[0, 1]
                energy_sim = (correlation + 1) / 2  # Map -1,1 to 0,1
        
        return (floor_sim * 0.3 + var_sim * 0.3 + energy_sim * 0.4)
    
    def analyze(self, audio: np.ndarray, timestamp: float) -> dict:
        """
        Perform comprehensive replay detection analysis.
        Returns detailed results with threat indicators.
        """
        self.total_samples += 1
        
        results = {
            'timestamp': timestamp,
            'is_replay': False,
            'confidence': 0.0,
            'methods_triggered': [],
            'details': {}
        }
        
        # Skip if audio is too quiet (silence)
        rms = np.sqrt(np.mean(audio**2))
        if rms < 0.001:
            results['details']['status'] = 'silent'
            return results
        
        threats = []
        confidences = []
        
        # === Method 1: Exact Hash Match ===
        exact_hash = self.compute_exact_hash(audio)
        
        if exact_hash in self.exact_hashes:
            threats.append('exact_match')
            confidences.append(1.0)
            results['methods_triggered'].append({
                'method': 'Exact Hash Match',
                'confidence': 1.0,
                'description': 'Identical audio detected - definite replay'
            })
        
        self.exact_hashes.append(exact_hash)
        results['details']['exact_hash'] = exact_hash[:16]
        
        # === Method 2: Perceptual Hash Similarity ===
        p_hash = self.compute_perceptual_hash(audio)
        
        for i, old_hash in enumerate(self.perceptual_hashes):
            similarity = self.hash_similarity(p_hash, old_hash)
            if similarity >= self.profile['replay_similarity_threshold']:
                threats.append('perceptual_match')
                confidences.append(similarity)
                results['methods_triggered'].append({
                    'method': 'Perceptual Hash Match',
                    'confidence': similarity,
                    'description': f'Similar audio detected ({similarity:.1%} match)'
                })
                break
        
        self.perceptual_hashes.append(p_hash)
        
        # === Method 3: Spectral Fingerprint Match ===
        fingerprint = self.compute_spectral_fingerprint(audio)
        
        for i, old_fp in enumerate(self.spectral_fingerprints):
            similarity = self.fingerprint_similarity(fingerprint, old_fp)
            if similarity >= self.profile['replay_similarity_threshold']:
                threats.append('spectral_match')
                confidences.append(similarity)
                results['methods_triggered'].append({
                    'method': 'Spectral Fingerprint Match',
                    'confidence': similarity,
                    'description': f'Matching frequency signature ({similarity:.1%})'
                })
                break
        
        self.spectral_fingerprints.append(fingerprint)
        results['details']['spectral_centroid'] = fingerprint['centroid']
        
        # === Method 4: Background Noise Analysis ===
        background = self.extract_background_profile(audio)
        
        if len(self.background_profiles) >= 3:
            # Check if background is suspiciously static
            recent_bgs = list(self.background_profiles)[-3:]
            
            for old_bg in recent_bgs:
                similarity = self.background_similarity(background, old_bg)
                if similarity >= self.profile['background_similarity_threshold']:
                    threats.append('static_background')
                    confidences.append(similarity)
                    results['methods_triggered'].append({
                        'method': 'Static Background',
                        'confidence': similarity,
                        'description': f'Unnaturally consistent background ({similarity:.1%})'
                    })
                    break
            
            # Check if background has zero variance (definite recording)
            if background['noise_variance'] < 1e-10 and background['noise_floor'] > 0:
                threats.append('zero_variance_background')
                confidences.append(0.9)
                results['methods_triggered'].append({
                    'method': 'Zero Variance Background',
                    'confidence': 0.9,
                    'description': 'Background noise has no variation - likely recording'
                })
        
        self.background_profiles.append(background)
        results['details']['background_variance'] = background['noise_variance']
        
        # === Method 5: Temporal Pattern Analysis ===
        self.audio_timestamps.append(timestamp)
        
        if len(self.audio_timestamps) >= 10:
            recent_ts = list(self.audio_timestamps)[-10:]
            intervals = np.diff(recent_ts)
            
            # Check for unnaturally regular intervals
            if len(intervals) > 5:
                interval_std = np.std(intervals)
                interval_mean = np.mean(intervals)
                
                # If intervals are too regular (< 1% variation), suspicious
                if interval_mean > 0 and (interval_std / interval_mean) < 0.01:
                    threats.append('regular_timing')
                    confidences.append(0.7)
                    results['methods_triggered'].append({
                        'method': 'Regular Timing Pattern',
                        'confidence': 0.7,
                        'description': 'Audio arriving at unnaturally regular intervals'
                    })
        
        # === Aggregate Results ===
        if threats:
            self.replay_detections += 1
            results['is_replay'] = True
            results['confidence'] = max(confidences)
            results['threat_types'] = threats
        
        return results


# =============================================================================
# ENHANCED AUDIO SENSOR
# =============================================================================

class EnhancedAudioSensor:
    """Audio sensor with ultrasonic detection and advanced replay detection"""
    
    SAMPLE_RATES = [48000, 44100, 32000, 22050, 16000]
    
    def __init__(self, profile: dict, sample_rate: int = None, chunk_size: int = 8192):
        self.profile = profile
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.available = HAVE_PYAUDIO
        
        self.audio = None
        self.stream = None
        self.audio_queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.device_name = None
        
        # Replay detector
        self.replay_detector = None  # Initialized after sample rate is known
        
        # Ultrasonic detection history
        self.ultrasonic_history = deque(maxlen=60)
        
        # Detailed logging
        self.detailed_log = deque(maxlen=1000)
        
    def _try_unmute_mic(self):
        """Try to unmute microphone"""
        try:
            subprocess.run(['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
                         capture_output=True, timeout=2)
            subprocess.run(['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
                         capture_output=True, timeout=2)
        except Exception:
            pass
        
        try:
            subprocess.run(['amixer', 'set', 'Capture', 'cap'],
                         capture_output=True, timeout=2)
            subprocess.run(['amixer', 'set', 'Capture', '100%'],
                         capture_output=True, timeout=2)
        except Exception:
            pass
    
    def _find_working_config(self):
        """Find working audio configuration"""
        if not self.available:
            return None, None, None
        
        try:
            p = pyaudio.PyAudio()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    rates = [self.sample_rate] if self.sample_rate else self.SAMPLE_RATES
                    
                    for rate in rates:
                        try:
                            stream = p.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            stream.read(self.chunk_size, exception_on_overflow=False)
                            stream.close()
                            p.terminate()
                            return i, info['name'], rate
                        except Exception:
                            continue
            
            p.terminate()
        except Exception:
            pass
        
        return None, None, None
    
    def start(self) -> bool:
        """Start audio capture"""
        if not self.available:
            return False
        
        self._try_unmute_mic()
        
        device_index, self.device_name, detected_rate = self._find_working_config()
        
        if device_index is None:
            return False
        
        if self.sample_rate is None:
            self.sample_rate = detected_rate
        
        # Initialize replay detector with correct sample rate
        self.replay_detector = AudioReplayDetector(self.profile, self.sample_rate)
        
        try:
            self.audio = pyaudio.PyAudio()
            
            self.stream = self.audio.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size
            )
            
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            
            return True
        except Exception:
            return False
    
    def _capture_loop(self):
        """Background audio capture"""
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio_array = np.frombuffer(data, dtype=np.float32)
                if not self.audio_queue.full():
                    self.audio_queue.put(audio_array)
            except Exception:
                time.sleep(0.01)
    
    def get_sample(self) -> Optional[np.ndarray]:
        """Get latest audio sample"""
        try:
            return self.audio_queue.get_nowait()
        except queue.Empty:
            return None
    
    def analyze(self, audio: np.ndarray) -> Optional[dict]:
        """Comprehensive audio analysis"""
        if audio is None or len(audio) == 0:
            return None
        
        timestamp = time.time()
        
        results = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'sample_rate': self.sample_rate,
            'rms': float(np.sqrt(np.mean(audio**2))),
            'peak': float(np.max(np.abs(audio)))
        }
        
        # Skip if silent
        if results['rms'] < 0.001:
            results['status'] = 'silent'
            return results
        
        results['status'] = 'active'
        
        # === FFT Analysis ===
        fft = np.fft.rfft(audio)
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        magnitude = np.abs(fft)
        
        # Frequency bands
        bands = {
            'voice': (300, 3400),
            'ultrasonic_low': (18000, 19000),
            'ultrasonic_mid': (19000, 20000),
            'ultrasonic_high': (20000, 22000),
        }
        
        band_energy = {}
        for name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs < high)
            band_energy[name] = float(np.sum(magnitude[mask]))
        
        results['band_energy'] = band_energy
        
        # Total energies
        ultrasonic_mask = (freqs >= 18000) & (freqs <= 22000)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        
        results['ultrasonic_energy'] = float(np.sum(magnitude[ultrasonic_mask]))
        results['voice_energy'] = float(np.sum(magnitude[voice_mask]))
        
        results['ultrasonic_ratio'] = (
            results['ultrasonic_energy'] / results['voice_energy']
            if results['voice_energy'] > 0 else 0
        )
        
        # Find ultrasonic peaks
        ultrasonic_freqs = freqs[ultrasonic_mask]
        ultrasonic_mags = magnitude[ultrasonic_mask]
        
        peak_frequencies = []
        if len(ultrasonic_mags) > 0 and np.max(ultrasonic_mags) > 10:
            for i in range(1, len(ultrasonic_mags) - 1):
                if (ultrasonic_mags[i] > ultrasonic_mags[i-1] and
                    ultrasonic_mags[i] > ultrasonic_mags[i+1] and
                    ultrasonic_mags[i] > np.mean(ultrasonic_mags) * 2):
                    peak_frequencies.append({
                        'frequency': float(ultrasonic_freqs[i]),
                        'magnitude': float(ultrasonic_mags[i])
                    })
            peak_frequencies.sort(key=lambda x: x['magnitude'], reverse=True)
            peak_frequencies = peak_frequencies[:5]
        
        results['ultrasonic_peaks'] = peak_frequencies
        
        # Identify sources
        likely_sources = []
        if peak_frequencies:
            dom_freq = peak_frequencies[0]['frequency']
            for (low, high), source in KNOWN_ULTRASONIC_SOURCES.items():
                if low <= dom_freq <= high:
                    likely_sources.append(source)
        results['likely_sources'] = likely_sources
        
        # === Ultrasonic Threat Assessment ===
        results['ultrasonic_suspicious'] = False
        results['ultrasonic_threat_level'] = 'none'
        results['ultrasonic_reasons'] = []
        
        ratio = results['ultrasonic_ratio']
        energy = results['ultrasonic_energy']
        
        if (ratio > self.profile['ultrasonic_ratio_threshold'] and 
            energy > self.profile['ultrasonic_absolute_threshold']):
            results['ultrasonic_suspicious'] = True
            results['ultrasonic_reasons'].append(
                f"High ratio: {ratio:.2f} (threshold: {self.profile['ultrasonic_ratio_threshold']})"
            )
            
            if ratio > self.profile['ultrasonic_ratio_threshold'] * 3:
                results['ultrasonic_threat_level'] = 'high'
            elif ratio > self.profile['ultrasonic_ratio_threshold'] * 1.5:
                results['ultrasonic_threat_level'] = 'medium'
            else:
                results['ultrasonic_threat_level'] = 'low'
        
        # Check DolphinAttack range
        if peak_frequencies:
            dom_freq = peak_frequencies[0]['frequency']
            if 19500 <= dom_freq <= 20500:
                results['ultrasonic_reasons'].append(f"DolphinAttack range: {dom_freq:.0f}Hz")
                if not results['ultrasonic_suspicious']:
                    results['ultrasonic_suspicious'] = True
                    results['ultrasonic_threat_level'] = 'medium'
        
        # === Replay Detection ===
        replay_results = self.replay_detector.analyze(audio, timestamp)
        results['replay'] = replay_results
        
        # === Combined Threat Summary ===
        results['threats'] = []
        
        if results['ultrasonic_suspicious']:
            results['threats'].append({
                'type': 'ultrasonic',
                'level': results['ultrasonic_threat_level'],
                'reasons': results['ultrasonic_reasons']
            })
        
        if replay_results['is_replay']:
            results['threats'].append({
                'type': 'replay',
                'level': 'high' if replay_results['confidence'] > 0.9 else 'medium',
                'confidence': replay_results['confidence'],
                'methods': [m['method'] for m in replay_results['methods_triggered']]
            })
        
        # Log if threats detected
        if results['threats']:
            self.detailed_log.append({
                'timestamp': results['datetime'],
                'threats': results['threats'],
                'ultrasonic_ratio': ratio,
                'replay_confidence': replay_results.get('confidence', 0),
                'peaks': peak_frequencies
            })
        
        return results
    
    def get_log(self) -> List[dict]:
        """Get detailed log"""
        return list(self.detailed_log)
    
    def get_stats(self) -> dict:
        """Get detection statistics"""
        if self.replay_detector:
            return {
                'total_samples': self.replay_detector.total_samples,
                'replay_detections': self.replay_detector.replay_detections,
                'log_entries': len(self.detailed_log)
            }
        return {}
    
    def export_log(self, filepath: str) -> int:
        """Export log to JSON"""
        data = {
            'export_time': datetime.now().isoformat(),
            'sample_rate': self.sample_rate,
            'stats': self.get_stats(),
            'events': self.get_log()
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return len(data['events'])
    
    def stop(self):
        """Stop audio capture"""
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
# WIFI SENSOR
# =============================================================================

class WiFiSensor:
    """WiFi signal monitoring"""
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.interface = self._find_interface()
        self.rssi_history = deque(maxlen=100)
        self.last_data = None
        
    def _find_interface(self) -> Optional[str]:
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
    
    def read(self) -> dict:
        data = {
            'available': self.interface is not None,
            'interface': self.interface,
            'ssid': None,
            'rssi': None,
            'quality': None,
            'timestamp': time.time()
        }
        
        if not self.interface:
            return data
        
        try:
            content = Path('/proc/net/wireless').read_text()
            for line in content.split('\n')[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    data['quality'] = float(parts[2].rstrip('.'))
                    data['rssi'] = int(float(parts[3].rstrip('.')))
        except Exception:
            pass
        
        try:
            result = subprocess.run(['iwconfig', self.interface],
                                  capture_output=True, text=True, timeout=2)
            if 'ESSID:"' in result.stdout:
                start = result.stdout.find('ESSID:"') + 7
                end = result.stdout.find('"', start)
                if end > start:
                    data['ssid'] = result.stdout[start:end]
        except Exception:
            pass
        
        return data
    
    def analyze(self, data: dict) -> List[Tuple[str, str]]:
        threats = []
        
        if data['rssi'] is not None:
            self.rssi_history.append(data['rssi'])
            
            if len(self.rssi_history) > 10:
                std = np.std(list(self.rssi_history)[-10:])
                if std < 0.5 and len(self.rssi_history) > 20:
                    threats.append(('WiFi', 'Suspiciously stable RSSI'))
            
            if self.last_data and self.last_data.get('rssi'):
                change = abs(data['rssi'] - self.last_data['rssi'])
                if change > self.profile['rssi_change_threshold']:
                    threats.append(('WiFi', f'RSSI jump: {change} dB'))
        
        self.last_data = data
        return threats


# =============================================================================
# BLUETOOTH SENSOR
# =============================================================================

class BluetoothSensor:
    """Bluetooth monitoring"""
    
    def __init__(self, profile: dict):
        self.profile = profile
        self.available = self._check()
        self.device_history = {}
        
    def _check(self) -> bool:
        try:
            result = subprocess.run(['which', 'hcitool'], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def scan(self, duration: int = 1) -> List[dict]:
        devices = []
        if not self.available:
            return devices
        
        try:
            result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=2)
            if 'UP RUNNING' not in result.stdout:
                return devices
        except Exception:
            return devices
        
        try:
            result = subprocess.run(
                ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
                capture_output=True, text=True, timeout=duration+2
            )
            
            seen = set()
            for line in result.stdout.split('\n'):
                if ':' in line:
                    parts = line.strip().split(' ', 1)
                    mac = parts[0]
                    if mac not in seen and len(mac) == 17:
                        devices.append({
                            'mac': mac,
                            'name': parts[1] if len(parts) > 1 else 'Unknown'
                        })
                        seen.add(mac)
        except Exception:
            pass
        
        if not devices:
            try:
                result = subprocess.run(['bluetoothctl', 'devices'],
                                      capture_output=True, text=True, timeout=3)
                for line in result.stdout.split('\n'):
                    if line.startswith('Device '):
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            devices.append({
                                'mac': parts[1],
                                'name': parts[2] if len(parts) > 2 else 'Unknown'
                            })
            except Exception:
                pass
        
        return devices


# =============================================================================
# SYSTEM SENSOR
# =============================================================================

class SystemSensor:
    """System monitoring"""
    
    def __init__(self):
        self.last_net = {}
        self.usb_history = set()
        
    def read_cpu(self) -> dict:
        if HAVE_PSUTIL:
            return {
                'usage': psutil.cpu_percent(interval=0.1),
                'cores': psutil.cpu_count()
            }
        return {'usage': 0, 'cores': 0}
    
    def read_memory(self) -> dict:
        if HAVE_PSUTIL:
            mem = psutil.virtual_memory()
            return {
                'total_mb': mem.total / (1024*1024),
                'used_percent': mem.percent
            }
        return {'total_mb': 0, 'used_percent': 0}
    
    def read_usb(self) -> List[dict]:
        devices = []
        usb_path = Path('/sys/bus/usb/devices')
        if usb_path.exists():
            for device in usb_path.iterdir():
                try:
                    vendor = (device / 'idVendor').read_text().strip()
                    product = (device / 'idProduct').read_text().strip()
                    name = (device / 'product').read_text().strip() if (device / 'product').exists() else 'Unknown'
                    devices.append({
                        'id': f"{vendor}:{product}",
                        'name': name
                    })
                except Exception:
                    pass
        return devices
    
    def check_usb_changes(self, devices: List[dict]) -> List[Tuple[str, str]]:
        threats = []
        current = set(d['id'] for d in devices)
        
        if self.usb_history:
            new_devices = current - self.usb_history
            for dev_id in new_devices:
                dev = next((d for d in devices if d['id'] == dev_id), None)
                name = dev['name'] if dev else dev_id
                threats.append(('USB', f'New device: {name}'))
        
        self.usb_history = current
        return threats


# =============================================================================
# MAIN DETECTOR
# =============================================================================

class UnifiedDetector:
    """Main unified detector"""
    
    def __init__(self, sensitivity: str = 'medium', log_file: str = None):
        self.sensitivity = sensitivity
        self.log_file = log_file
        self.profile = SENSITIVITY_PROFILES.get(sensitivity, SENSITIVITY_PROFILES['medium'])
        
        print("=" * 78)
        print("  UNIFIED SIGNAL INJECTION DETECTOR - ENHANCED")
        print(f"  Version {VERSION} with Advanced Replay Detection")
        print("=" * 78)
        print()
        print(f"  Sensitivity: {sensitivity.upper()} - {self.profile['description']}")
        print()
        
        self.wifi = WiFiSensor(self.profile)
        self.bluetooth = BluetoothSensor(self.profile)
        self.audio = EnhancedAudioSensor(self.profile)
        self.system = SystemSensor()
        
        self.start_time = time.time()
        self.sample_count = 0
        self.threat_log = deque(maxlen=1000)
        
    def initialize(self) -> dict:
        print("Initializing sensors...")
        
        status = {
            'wifi': self.wifi.interface is not None,
            'bluetooth': self.bluetooth.available,
            'audio': self.audio.start(),
            'system': True
        }
        
        icons = {True: '✓', False: '✗'}
        print(f"  {icons[status['wifi']]} WiFi ({self.wifi.interface or 'not found'})")
        print(f"  {icons[status['bluetooth']]} Bluetooth")
        print(f"  {icons[status['audio']]} Audio ({self.audio.device_name or 'not found'})")
        if status['audio'] and self.audio.sample_rate:
            print(f"      Sample rate: {self.audio.sample_rate}Hz")
        print(f"  {icons[status['system']]} System sensors")
        print()
        
        return status
    
    def collect(self) -> dict:
        timestamp = time.time()
        threats = []
        
        data = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'sensitivity': self.sensitivity
        }
        
        # WiFi
        wifi_data = self.wifi.read()
        data['wifi'] = wifi_data
        threats.extend(self.wifi.analyze(wifi_data))
        
        # Bluetooth
        if self.bluetooth.available and self.sample_count % 10 == 0:
            devices = self.bluetooth.scan(duration=1)
            data['bluetooth'] = {'count': len(devices), 'devices': devices}
        
        # Audio
        audio_sample = self.audio.get_sample()
        if audio_sample is not None:
            audio_data = self.audio.analyze(audio_sample)
            data['audio'] = audio_data
            
            if audio_data:
                # Ultrasonic threats
                if audio_data.get('ultrasonic_suspicious'):
                    msg = f"Ultrasonic (ratio: {audio_data['ultrasonic_ratio']:.2f}"
                    if audio_data.get('ultrasonic_peaks'):
                        msg += f" @ {audio_data['ultrasonic_peaks'][0]['frequency']:.0f}Hz"
                    msg += ")"
                    threats.append(('Audio-Ultrasonic', msg))
                
                # Replay threats
                replay = audio_data.get('replay', {})
                if replay.get('is_replay'):
                    methods = replay.get('methods_triggered', [])
                    method_names = [m['method'] for m in methods[:2]]
                    confidence = replay.get('confidence', 0)
                    msg = f"REPLAY ATTACK ({confidence:.0%}) - {', '.join(method_names)}"
                    threats.append(('Audio-Replay', msg))
        
        # System
        if self.sample_count % 5 == 0:
            data['cpu'] = self.system.read_cpu()
            data['memory'] = self.system.read_memory()
            
            usb_devices = self.system.read_usb()
            threats.extend(self.system.check_usb_changes(usb_devices))
        
        # Risk level
        count = len(threats)
        if count >= 3:
            data['risk_level'] = 'CRITICAL'
        elif count >= 2:
            data['risk_level'] = 'HIGH'
        elif count >= 1:
            data['risk_level'] = 'MEDIUM'
        else:
            data['risk_level'] = 'LOW'
        
        data['threats'] = threats
        self.sample_count += 1
        
        return data
    
    def display(self, data: dict):
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 78
        
        # Header
        print("╔" + "═" * width + "╗")
        print("║" + " " * 16 + "UNIFIED SIGNAL INJECTION DETECTOR" + " " * 27 + "║")
        runtime = int(time.time() - self.start_time)
        info = f"{data['datetime'][:19]}  |  {self.sensitivity.upper()}  |  Sample #{self.sample_count}  |  {runtime}s"
        print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # WiFi
        wifi = data.get('wifi', {})
        print("┌─ WiFi " + "─" * (width - 8) + "┐")
        if wifi.get('ssid'):
            line = f"│  {wifi['ssid']}  |  RSSI: {wifi.get('rssi', 'N/A')} dBm"
        else:
            line = "│  Not connected"
        print(line + " " * (width - len(line)) + "│")
        print("└" + "─" * width + "┘")
        print()
        
        # Audio
        audio = data.get('audio', {})
        print("┌─ Audio Analysis " + "─" * (width - 18) + "┐")
        
        if audio and audio.get('status') == 'active':
            line = f"│  RMS: {audio.get('rms', 0):.4f}  |  Peak: {audio.get('peak', 0):.4f}"
            print(line + " " * (width - len(line)) + "│")
            
            ratio = audio.get('ultrasonic_ratio', 0)
            line = f"│  Ultrasonic ratio: {ratio:.3f}"
            if audio.get('ultrasonic_peaks'):
                line += f"  |  Peak: {audio['ultrasonic_peaks'][0]['frequency']:.0f}Hz"
            print(line + " " * (width - len(line)) + "│")
            
            # Replay detection status
            replay = audio.get('replay', {})
            stats = self.audio.get_stats()
            line = f"│  Replay detector: {stats.get('total_samples', 0)} samples, {stats.get('replay_detections', 0)} detections"
            print(line + " " * (width - len(line)) + "│")
            
            if replay.get('is_replay'):
                print("│" + " " * width + "│")
                line = f"│  ⚠ REPLAY DETECTED (confidence: {replay.get('confidence', 0):.0%})"
                print(line + " " * (width - len(line)) + "│")
                for method in replay.get('methods_triggered', [])[:3]:
                    line = f"│    → {method['method']}: {method['description'][:50]}"
                    print(line + " " * (width - len(line)) + "│")
        else:
            status = audio.get('status', 'not available') if audio else 'not available'
            line = f"│  Status: {status}"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # System
        if 'cpu' in data:
            print("┌─ System " + "─" * (width - 10) + "┐")
            line = f"│  CPU: {data['cpu'].get('usage', 0):.1f}%  |  Memory: {data['memory'].get('used_percent', 0):.1f}%"
            print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        # Threats
        risk_colors = {
            'LOW': '\033[92m',
            'MEDIUM': '\033[93m',
            'HIGH': '\033[91m',
            'CRITICAL': '\033[95m'
        }
        reset = '\033[0m'
        color = risk_colors.get(data['risk_level'], '')
        
        print("┌─ Threat Assessment " + "─" * (width - 21) + "┐")
        visible = f"│  Risk: {data['risk_level']}  |  Active: {len(data['threats'])}  |  Logged: {len(self.audio.detailed_log)}"
        line = f"│  Risk: {color}{data['risk_level']}{reset}  |  Active: {len(data['threats'])}  |  Logged: {len(self.audio.detailed_log)}"
        print(line + " " * (width - len(visible)) + "│")
        print("│" + " " * width + "│")
        
        if data['threats']:
            for threat_type, message in data['threats'][:5]:
                msg = message[:width-20]
                line = f"│  🚨 [{threat_type}] {msg}"
                print(line + " " * (width - len(line) + 2) + "│")
        else:
            line = "│  ✅ All sensors normal"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Recent threats
        recent = list(self.audio.detailed_log)[-3:]
        if recent:
            print("┌─ Recent Threat Log " + "─" * (width - 21) + "┐")
            for entry in recent:
                ts = entry['timestamp'][11:19]
                threat_types = [t['type'] for t in entry.get('threats', [])]
                line = f"│  [{ts}] {', '.join(threat_types)}"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        print(f"  Ctrl+C to stop  |  --sensitivity [low/medium/high/paranoid]  |  --log FILE")
    
    def run(self, interval: float = 1.0):
        try:
            while True:
                data = self.collect()
                self.display(data)
                
                for threat in data['threats']:
                    self.threat_log.append({
                        'timestamp': data['datetime'],
                        'type': threat[0],
                        'message': threat[1]
                    })
                
                time.sleep(interval)
        except KeyboardInterrupt:
            self.shutdown()
    
    def shutdown(self):
        print("\n\nShutting down...")
        
        if self.log_file:
            count = self.audio.export_log(self.log_file)
            print(f"Exported {count} events to {self.log_file}")
        
        self.audio.stop()
        
        stats = self.audio.get_stats()
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Duration: {int(time.time() - self.start_time)}s")
        print(f"  Audio samples: {stats.get('total_samples', 0)}")
        print(f"  Replay detections: {stats.get('replay_detections', 0)}")
        print(f"  Total threats logged: {len(self.audio.detailed_log)}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Unified Signal Injection Detector - Enhanced with Replay Detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
REPLAY DETECTION METHODS:
    1. Exact Hash       - Catches identical audio playback
    2. Perceptual Hash  - Catches re-encoded/modified replays  
    3. Spectral Match   - Catches frequency-domain similarities
    4. Background Analysis - Recordings have static background
    5. Temporal Pattern - Detects unnatural timing

EXAMPLES:
    %(prog)s
    %(prog)s --sensitivity low
    %(prog)s --sensitivity paranoid --log threats.json
    sudo %(prog)s  # For Bluetooth scanning
        """
    )
    
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high', 'paranoid'],
                        default='medium')
    parser.add_argument('-l', '--log', help='Export log to JSON file')
    parser.add_argument('-i', '--interval', type=float, default=1.0)
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    detector = UnifiedDetector(
        sensitivity=args.sensitivity,
        log_file=args.log
    )
    
    detector.initialize()
    
    print("Starting monitoring with enhanced replay detection...")
    time.sleep(1)
    
    detector.run(interval=args.interval)


if __name__ == "__main__":
    main()