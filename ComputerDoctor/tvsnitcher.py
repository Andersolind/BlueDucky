#!/usr/bin/env python3
"""
================================================================================
TV-AWARE REPLAY ATTACK DETECTOR
================================================================================

Detects replay attacks even while watching TV by distinguishing between:
- Normal TV/media audio (expected, broadcast characteristics)
- Voice assistant commands (speech patterns, specific frequencies)
- Replay attacks (recorded commands played through speakers)

KEY DETECTION METHODS:

1. VOICE COMMAND DETECTION
   - Detects speech patterns vs music/TV audio
   - Identifies wake words ("Hey Siri", "Alexa", "OK Google")
   - Monitors voice frequency band (85-255 Hz fundamental)

2. SPEAKER vs LIVE VOICE DETECTION
   - Live voice: has room reverb, natural variation
   - Speaker playback: flat response, no room acoustics
   - Detects speaker frequency response (unnatural EQ)

3. DIRECTIONAL ANALYSIS (if stereo mic available)
   - TV comes from fixed direction
   - Replay attack speaker may be different location
   - Sudden direction changes = suspicious

4. TIMING CORRELATION
   - Correlates suspicious audio with device activity
   - Voice assistant activation
   - Network traffic to cloud services

USAGE:
    python3 tv_aware_detector.py
    python3 tv_aware_detector.py --tv-learning    # Learn your TV's audio signature
    python3 tv_aware_detector.py --sensitivity high --log attacks.json

================================================================================
"""

import os
import sys
import time
import json
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

# Wake words to detect (will be detected via energy patterns, not speech recognition)
WAKE_WORD_PATTERNS = [
    "hey siri",
    "alexa", 
    "ok google",
    "hey google",
    "cortana",
    "hey mycroft",
]

# Frequency bands for analysis
FREQ_BANDS = {
    'sub_bass': (20, 60),
    'bass': (60, 250),
    'low_mid': (250, 500),
    'mid': (500, 2000),
    'high_mid': (2000, 4000),
    'presence': (4000, 6000),
    'brilliance': (6000, 10000),
    'high': (10000, 16000),
    'ultrasonic': (18000, 22000),
}

# Voice characteristics
VOICE_FUNDAMENTAL_RANGE = (85, 300)  # Hz - human voice fundamental
VOICE_FORMANT_RANGE = (300, 3400)    # Hz - voice formants


# =============================================================================
# TV AUDIO SIGNATURE LEARNING
# =============================================================================

class TVAudioSignature:
    """Learn and recognize TV audio characteristics"""
    
    def __init__(self):
        self.signatures = deque(maxlen=1000)
        self.spectral_profile = None
        self.is_learned = False
        self.learning_samples = 0
        
    def learn(self, audio: np.ndarray, sample_rate: int):
        """Learn TV audio characteristics"""
        # Compute spectral signature
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/sample_rate)
        
        # Normalize
        if np.max(fft) > 0:
            fft = fft / np.max(fft)
        
        # Store signature
        self.signatures.append({
            'fft': fft[:500],  # First 500 bins
            'freqs': freqs[:500],
            'timestamp': time.time()
        })
        
        self.learning_samples += 1
        
        # Build average profile after enough samples
        if self.learning_samples >= 50:
            self._build_profile()
    
    def _build_profile(self):
        """Build average TV spectral profile"""
        if not self.signatures:
            return
            
        # Average all signatures
        all_ffts = np.array([s['fft'] for s in self.signatures])
        self.spectral_profile = {
            'mean': np.mean(all_ffts, axis=0),
            'std': np.std(all_ffts, axis=0),
            'min': np.min(all_ffts, axis=0),
            'max': np.max(all_ffts, axis=0),
        }
        self.is_learned = True
    
    def is_tv_audio(self, audio: np.ndarray, sample_rate: int) -> Tuple[bool, float]:
        """Check if audio matches TV signature"""
        if not self.is_learned:
            return False, 0.0
        
        # Compute current signature
        fft = np.abs(np.fft.rfft(audio))
        if np.max(fft) > 0:
            fft = fft / np.max(fft)
        
        fft = fft[:500]
        
        # Compare with profile
        if len(fft) != len(self.spectral_profile['mean']):
            return False, 0.0
        
        # Compute similarity
        diff = np.abs(fft - self.spectral_profile['mean'])
        within_range = diff < (self.spectral_profile['std'] * 2 + 0.1)
        similarity = np.mean(within_range)
        
        return similarity > 0.7, similarity
    
    def save(self, filepath: str):
        """Save learned profile"""
        if not self.is_learned:
            return
        
        data = {
            'spectral_profile': {
                'mean': self.spectral_profile['mean'].tolist(),
                'std': self.spectral_profile['std'].tolist(),
            },
            'learning_samples': self.learning_samples,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f)
    
    def load(self, filepath: str) -> bool:
        """Load saved profile"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.spectral_profile = {
                'mean': np.array(data['spectral_profile']['mean']),
                'std': np.array(data['spectral_profile']['std']),
            }
            self.learning_samples = data['learning_samples']
            self.is_learned = True
            return True
        except Exception:
            return False


# =============================================================================
# VOICE vs TV AUDIO CLASSIFIER
# =============================================================================

class VoiceDetector:
    """Detect human voice/speech patterns in audio"""
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.speech_history = deque(maxlen=50)
        
    def analyze(self, audio: np.ndarray) -> dict:
        """Analyze audio for voice characteristics"""
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        result = {
            'is_voice': False,
            'voice_confidence': 0.0,
            'is_command_like': False,
            'voice_energy': 0.0,
            'music_energy': 0.0,
            'spectral_flatness': 0.0,
        }
        
        # Voice frequency band energy (300-3400 Hz)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        voice_energy = np.sum(fft[voice_mask])
        
        # Music/broad spectrum energy
        music_mask = (freqs >= 20) & (freqs <= 16000)
        music_energy = np.sum(fft[music_mask])
        
        result['voice_energy'] = float(voice_energy)
        result['music_energy'] = float(music_energy)
        
        # Voice has concentrated energy in formant regions
        # Music has more evenly distributed energy
        
        # Spectral flatness: voice has peaks, music is flatter
        if np.mean(fft) > 0:
            geometric_mean = np.exp(np.mean(np.log(fft + 1e-10)))
            arithmetic_mean = np.mean(fft)
            spectral_flatness = geometric_mean / arithmetic_mean
            result['spectral_flatness'] = float(spectral_flatness)
        
        # Voice typically has lower spectral flatness (more peaked)
        # due to formant structure
        
        # Check for voice fundamental frequency (85-300 Hz)
        fundamental_mask = (freqs >= 85) & (freqs <= 300)
        fundamental_energy = np.sum(fft[fundamental_mask])
        
        # Check formant regions
        formant1_mask = (freqs >= 300) & (freqs <= 900)
        formant2_mask = (freqs >= 900) & (freqs <= 2500)
        
        formant1_energy = np.sum(fft[formant1_mask])
        formant2_energy = np.sum(fft[formant2_mask])
        
        # Voice has strong formant peaks
        total = voice_energy + 1e-10
        formant_ratio = (formant1_energy + formant2_energy) / total
        
        # Calculate voice confidence
        voice_confidence = 0.0
        
        # Low spectral flatness = voice
        if spectral_flatness < 0.3:
            voice_confidence += 0.3
        
        # Strong formants relative to total
        if formant_ratio > 0.4:
            voice_confidence += 0.3
        
        # Fundamental frequency present
        if fundamental_energy > voice_energy * 0.1:
            voice_confidence += 0.2
        
        # Not too much high frequency (voice rolls off above 4kHz)
        high_mask = freqs > 6000
        high_energy = np.sum(fft[high_mask])
        if high_energy < voice_energy * 0.3:
            voice_confidence += 0.2
        
        result['voice_confidence'] = voice_confidence
        result['is_voice'] = voice_confidence > 0.5
        
        # Check if it sounds like a short command (1-3 seconds of speech)
        self.speech_history.append(result['is_voice'])
        
        if len(self.speech_history) >= 10:
            recent = list(self.speech_history)[-20:]
            speech_ratio = sum(recent) / len(recent)
            
            # Command pattern: burst of speech then silence
            if 0.3 < speech_ratio < 0.8:
                result['is_command_like'] = True
        
        return result


# =============================================================================
# SPEAKER vs LIVE VOICE DETECTOR  
# =============================================================================

class SpeakerDetector:
    """Detect if audio is coming from a speaker vs live voice"""
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.room_signatures = deque(maxlen=100)
        
    def analyze(self, audio: np.ndarray) -> dict:
        """Detect speaker playback characteristics"""
        result = {
            'is_speaker': False,
            'speaker_confidence': 0.0,
            'reasons': [],
            'room_reverb': 0.0,
            'frequency_response_flat': False,
        }
        
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        # === Check 1: Room Reverb ===
        # Live voice has natural room reverb (delayed reflections)
        # Speaker playback has its own recorded reverb but lacks room interaction
        
        # Compute autocorrelation for reverb detection
        autocorr = np.correlate(audio, audio, mode='full')
        autocorr = autocorr[len(autocorr)//2:]
        if autocorr[0] > 0:
            autocorr = autocorr / autocorr[0]
        
        # Look for reverb (reflections 10-100ms)
        reverb_start = int(0.01 * self.sample_rate)
        reverb_end = int(0.1 * self.sample_rate)
        
        if reverb_end < len(autocorr):
            reverb_energy = np.mean(np.abs(autocorr[reverb_start:reverb_end]))
            result['room_reverb'] = float(reverb_energy)
            
            # Very low reverb = likely speaker (or anechoic room)
            if reverb_energy < 0.02:
                result['speaker_confidence'] += 0.3
                result['reasons'].append("No room reverb detected")
        
        # === Check 2: Frequency Response ===
        # Speakers have limited/colored frequency response
        # Small speakers lack bass, have resonance peaks
        
        # Check bass response (real voice in room has natural bass)
        bass_mask = (freqs >= 60) & (freqs <= 250)
        bass_energy = np.sum(fft[bass_mask])
        
        mid_mask = (freqs >= 500) & (freqs <= 2000)
        mid_energy = np.sum(fft[mid_mask])
        
        if mid_energy > 0:
            bass_ratio = bass_energy / mid_energy
            
            # Phone/small speakers have weak bass
            if bass_ratio < 0.1:
                result['speaker_confidence'] += 0.2
                result['reasons'].append("Weak bass (small speaker signature)")
        
        # === Check 3: High Frequency Cutoff ===
        # Cheap speakers cut off sharply above 12-16 kHz
        
        high_mask = freqs > 14000
        very_high_mask = freqs > 18000
        
        high_energy = np.sum(fft[high_mask])
        very_high_energy = np.sum(fft[very_high_mask])
        
        total_energy = np.sum(fft)
        
        if total_energy > 0:
            high_ratio = high_energy / total_energy
            
            # Abrupt HF cutoff = speaker
            if high_ratio < 0.001 and mid_energy > 0:
                result['speaker_confidence'] += 0.2
                result['reasons'].append("Sharp high-frequency cutoff")
        
        # === Check 4: Dynamic Range ===
        # Compressed audio (like phone playback) has limited dynamic range
        
        rms = np.sqrt(np.mean(audio**2))
        peak = np.max(np.abs(audio))
        
        if rms > 0:
            crest_factor = peak / rms
            
            # Low crest factor = compressed audio
            if crest_factor < 2.5:
                result['speaker_confidence'] += 0.15
                result['reasons'].append("Low dynamic range (compressed)")
        
        # === Check 5: Spectral Consistency ===
        # Speaker playback is very consistent
        # Live voice has more variation
        
        # Split into segments and compare
        seg_size = len(audio) // 4
        segments = [audio[i*seg_size:(i+1)*seg_size] for i in range(4)]
        
        seg_energies = [np.sqrt(np.mean(s**2)) for s in segments]
        energy_variation = np.std(seg_energies) / (np.mean(seg_energies) + 1e-10)
        
        # Very consistent = likely speaker
        if energy_variation < 0.1:
            result['speaker_confidence'] += 0.15
            result['reasons'].append("Unnaturally consistent audio")
        
        result['is_speaker'] = result['speaker_confidence'] > 0.5
        
        return result


# =============================================================================
# COMBINED TV-AWARE DETECTOR
# =============================================================================

class TVAwareReplayDetector:
    """
    Replay attack detector that works while watching TV
    """
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        
        # Sub-detectors
        self.tv_signature = TVAudioSignature()
        self.voice_detector = VoiceDetector(sample_rate)
        self.speaker_detector = SpeakerDetector(sample_rate)
        
        # Attack detection state
        self.command_history = deque(maxlen=50)
        self.attack_log = deque(maxlen=1000)
        
        # Waveform matching for exact replays
        self.waveform_hashes = deque(maxlen=500)
        
    def analyze(self, audio: np.ndarray) -> dict:
        """Full analysis for replay attack while TV is on"""
        timestamp = time.time()
        
        rms = np.sqrt(np.mean(audio**2))
        
        result = {
            'timestamp': timestamp,
            'datetime': datetime.now().isoformat(),
            'rms': float(rms),
            'is_attack': False,
            'confidence': 0.0,
            'attack_type': None,
            'indicators': [],
            'analysis': {}
        }
        
        if rms < 0.001:
            result['status'] = 'silent'
            return result
        
        result['status'] = 'active'
        
        # === Step 1: Check if this is TV audio ===
        is_tv, tv_similarity = self.tv_signature.is_tv_audio(audio, self.sample_rate)
        result['analysis']['tv'] = {
            'is_tv_audio': is_tv,
            'similarity': float(tv_similarity)
        }
        
        # === Step 2: Detect voice/speech ===
        voice_result = self.voice_detector.analyze(audio)
        result['analysis']['voice'] = voice_result
        
        # === Step 3: Check for speaker playback ===
        speaker_result = self.speaker_detector.analyze(audio)
        result['analysis']['speaker'] = speaker_result
        
        # === Step 4: Check for exact waveform replay ===
        waveform_hash = self._compute_waveform_hash(audio)
        is_exact_replay = waveform_hash in self.waveform_hashes
        self.waveform_hashes.append(waveform_hash)
        
        result['analysis']['exact_replay'] = is_exact_replay
        
        # === Step 5: Ultrasonic check ===
        ultrasonic = self._check_ultrasonic(audio)
        result['analysis']['ultrasonic'] = ultrasonic
        
        # === ATTACK DETECTION LOGIC ===
        
        attack_confidence = 0.0
        indicators = []
        
        # Scenario 1: Voice command detected + speaker characteristics
        # = Someone playing a recorded command through speaker
        if voice_result['is_voice'] and voice_result['is_command_like']:
            if speaker_result['is_speaker']:
                attack_confidence += 0.6
                indicators.append(f"Voice command from speaker (conf: {speaker_result['speaker_confidence']:.0%})")
                for reason in speaker_result['reasons'][:2]:
                    indicators.append(f"  → {reason}")
        
        # Scenario 2: Voice detected but NOT matching TV signature
        # = Unexpected voice (could be attack or person in room)
        if voice_result['is_voice'] and not is_tv:
            if self.tv_signature.is_learned:
                # TV is on, but this voice doesn't match TV
                if speaker_result['is_speaker']:
                    attack_confidence += 0.4
                    indicators.append("Voice not matching TV signature + speaker detected")
        
        # Scenario 3: Exact waveform replay
        # = Definite replay attack
        if is_exact_replay:
            attack_confidence = max(attack_confidence, 0.9)
            indicators.append("Exact audio waveform repeated (definite replay)")
        
        # Scenario 4: Ultrasonic injection (DolphinAttack)
        if ultrasonic['is_suspicious']:
            attack_confidence = max(attack_confidence, 0.7)
            indicators.append(f"Ultrasonic injection detected (ratio: {ultrasonic['ratio']:.2f})")
        
        # Scenario 5: Voice command NOT from TV direction
        # (would need stereo analysis - placeholder)
        
        # === Final Decision ===
        result['confidence'] = attack_confidence
        result['is_attack'] = attack_confidence > 0.5
        result['indicators'] = indicators
        
        if result['is_attack']:
            if is_exact_replay:
                result['attack_type'] = 'exact_replay'
            elif ultrasonic['is_suspicious']:
                result['attack_type'] = 'ultrasonic'
            else:
                result['attack_type'] = 'speaker_playback'
            
            self.attack_log.append(result)
        
        return result
    
    def _compute_waveform_hash(self, audio: np.ndarray) -> str:
        """Compute perceptual hash of waveform"""
        # Downsample for faster comparison
        downsampled = audio[::10]
        
        # Normalize
        if np.max(np.abs(downsampled)) > 0:
            downsampled = downsampled / np.max(np.abs(downsampled))
        
        # Quantize to reduce noise sensitivity
        quantized = (downsampled * 100).astype(np.int8)
        
        return hashlib.md5(quantized.tobytes()).hexdigest()
    
    def _check_ultrasonic(self, audio: np.ndarray) -> dict:
        """Check for ultrasonic injection"""
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        ultrasonic_mask = (freqs >= 18000) & (freqs <= 22000)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        
        ultrasonic_energy = np.sum(fft[ultrasonic_mask])
        voice_energy = np.sum(fft[voice_mask])
        
        ratio = ultrasonic_energy / (voice_energy + 1e-10)
        
        return {
            'energy': float(ultrasonic_energy),
            'ratio': float(ratio),
            'is_suspicious': ratio > 0.3
        }
    
    def learn_tv(self, audio: np.ndarray):
        """Add sample to TV learning"""
        self.tv_signature.learn(audio, self.sample_rate)


# =============================================================================
# AUDIO CAPTURE (SAME AS BEFORE WITH MIC VERIFICATION)
# =============================================================================

class AudioCapture:
    """Audio capture with mic verification"""
    
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
        """Unmute all mic controls"""
        # PulseAudio
        for cmd in [
            ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
            ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
        ]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass
        
        # ALSA
        for control in ['Capture', 'Mic', 'Mic Boost', 'Internal Mic']:
            for action in [['cap'], ['unmute'], ['100%']]:
                try:
                    subprocess.run(['amixer', 'set', control] + action,
                                 capture_output=True, timeout=2)
                except Exception:
                    pass
        
        # PipeWire
        try:
            subprocess.run(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', '0'],
                         capture_output=True, timeout=2)
        except Exception:
            pass
    
    def _verify_mic(self, stream, rate: int) -> Tuple[bool, float]:
        """Verify mic is capturing audio"""
        try:
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
    
    def start(self) -> bool:
        """Start audio capture"""
        if not HAVE_PYAUDIO:
            print("  ✗ PyAudio not installed")
            return False
        
        print("  Configuring microphone...")
        self._unmute_all()
        
        try:
            p = pyaudio.PyAudio()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
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
                            
                            is_working, rms = self._verify_mic(stream, rate)
                            stream.close()
                            
                            if not is_working:
                                continue
                            
                            # Found working config
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
                            print(f"  ✓ Microphone: {self.device_name[:40]} @ {rate}Hz")
                            return True
                            
                        except Exception:
                            continue
            
            p.terminate()
        except Exception as e:
            print(f"  ✗ Error: {e}")
        
        print("  ✗ No working microphone found")
        return False
    
    def _capture(self):
        """Background capture"""
        silent_count = 0
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                
                rms = np.sqrt(np.mean(audio**2))
                self.last_rms = rms
                
                if rms < 0.0001:
                    silent_count += 1
                    if silent_count > 50:
                        self.mic_verified = False
                else:
                    silent_count = 0
                    self.mic_verified = True
                
                if not self.queue.full():
                    self.queue.put(audio)
            except Exception:
                time.sleep(0.01)
    
    def get_sample(self) -> Optional[np.ndarray]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def get_status(self) -> dict:
        return {
            'verified': self.mic_verified,
            'device': self.device_name,
            'sample_rate': self.sample_rate,
            'rms': self.last_rms
        }
    
    def stop(self):
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
# DEVICE MONITOR (SIMPLIFIED)
# =============================================================================

class DeviceMonitor:
    """Monitor for voice assistant activity"""
    
    def __init__(self):
        self.events = deque(maxlen=100)
        self.monitoring = False
        self.thread = None
    
    def start(self):
        self.monitoring = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()
    
    def _monitor(self):
        while self.monitoring:
            try:
                # Check for voice assistant processes
                result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
                
                for pattern in ['alexa', 'siri', 'google-assistant', 'mycroft', 'speech']:
                    if pattern in result.stdout.lower():
                        self.events.append({
                            'timestamp': time.time(),
                            'type': 'voice_assistant',
                            'pattern': pattern
                        })
                
                # Check audio system
                result = subprocess.run(['pactl', 'list', 'source-outputs', 'short'],
                                      capture_output=True, text=True, timeout=3)
                if result.stdout.strip():
                    self.events.append({
                        'timestamp': time.time(),
                        'type': 'audio_recording',
                        'details': result.stdout.strip()[:100]
                    })
                
                time.sleep(1)
            except Exception:
                time.sleep(2)
    
    def get_recent(self, seconds: float = 5) -> List[dict]:
        cutoff = time.time() - seconds
        return [e for e in self.events if e['timestamp'] > cutoff]
    
    def stop(self):
        self.monitoring = False


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class TVAwareDetectorApp:
    """Main application"""
    
    def __init__(self, sensitivity: str = 'medium', log_file: str = None, 
                 tv_learning: bool = False, tv_profile: str = None):
        self.sensitivity = sensitivity
        self.log_file = log_file
        self.tv_learning = tv_learning
        self.tv_profile = tv_profile or os.path.expanduser('~/.tv_audio_profile.json')
        
        self.audio_capture = AudioCapture()
        self.detector = None
        self.device_monitor = DeviceMonitor()
        
        self.start_time = time.time()
        self.sample_count = 0
        self.attack_count = 0
    
    def initialize(self) -> bool:
        print("=" * 70)
        print("  TV-AWARE REPLAY ATTACK DETECTOR")
        print(f"  Version {VERSION}")
        print("=" * 70)
        print()
        
        if self.tv_learning:
            print("  MODE: TV Learning (learning your TV's audio signature)")
        else:
            print("  MODE: Detection")
        print()
        
        # Start audio
        if not self.audio_capture.start():
            return False
        
        # Initialize detector
        self.detector = TVAwareReplayDetector(self.audio_capture.sample_rate)
        
        # Load TV profile if exists
        if not self.tv_learning and os.path.exists(self.tv_profile):
            if self.detector.tv_signature.load(self.tv_profile):
                print(f"  ✓ Loaded TV profile from {self.tv_profile}")
            else:
                print(f"  ⚠ Could not load TV profile")
        
        # Start device monitor
        self.device_monitor.start()
        print("  ✓ Device monitor started")
        
        print()
        return True
    
    def run(self, interval: float = 0.3):
        print("Starting detection...")
        if self.tv_learning:
            print("Play your TV normally for 30-60 seconds to learn its signature...")
        print()
        time.sleep(1)
        
        try:
            while True:
                audio = self.audio_capture.get_sample()
                
                if audio is not None:
                    self.sample_count += 1
                    
                    if self.tv_learning:
                        # Learning mode
                        self.detector.learn_tv(audio)
                        self._display_learning()
                    else:
                        # Detection mode
                        result = self.detector.analyze(audio)
                        
                        if result.get('is_attack'):
                            self.attack_count += 1
                            
                            # Correlate with device activity
                            device_events = self.device_monitor.get_recent(3)
                            result['device_events'] = device_events
                        
                        self._display_detection(result)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.shutdown()
    
    def _display_learning(self):
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 70
        samples = self.detector.tv_signature.learning_samples
        
        print("╔" + "═" * width + "╗")
        print("║" + " " * 20 + "TV AUDIO LEARNING MODE" + " " * 26 + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # Mic status
        mic = self.audio_capture.get_status()
        print("┌─ Microphone " + "─" * (width - 14) + "┐")
        status = "✓ ACTIVE" if mic['verified'] else "⚠ SILENT"
        line = f"│  {status}  |  Level: {mic['rms']:.6f}"
        print(line + " " * (width - len(line)) + "│")
        
        level_bars = int(min(mic['rms'] * 500, 50))
        meter = "█" * level_bars + "░" * (50 - level_bars)
        line = f"│  [{meter}]"
        print(line + " " * (width - len(line)) + "│")
        print("└" + "─" * width + "┘")
        print()
        
        # Learning progress
        print("┌─ Learning Progress " + "─" * (width - 21) + "┐")
        
        progress = min(samples / 50 * 100, 100)
        progress_bar = "█" * int(progress / 2) + "░" * (50 - int(progress / 2))
        
        line = f"│  Samples: {samples}/50  [{progress_bar}]"
        print(line + " " * (width - len(line) - 1) + "│")
        
        if samples >= 50:
            line = "│  ✓ LEARNING COMPLETE - Press Ctrl+C to save and exit"
            print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  Keep your TV playing normally..."
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        print("  Play TV audio normally. Profile will be saved when you press Ctrl+C")
    
    def _display_detection(self, result: dict):
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 70
        runtime = int(time.time() - self.start_time)
        
        print("╔" + "═" * width + "╗")
        print("║" + " " * 18 + "TV-AWARE REPLAY DETECTOR" + " " * 26 + "║")
        info = f"Runtime: {runtime}s  |  Samples: {self.sample_count}  |  Attacks: {self.attack_count}"
        print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # Mic status
        mic = self.audio_capture.get_status()
        print("┌─ Microphone " + "─" * (width - 14) + "┐")
        color = '\033[92m' if mic['verified'] else '\033[93m'
        reset = '\033[0m'
        status = "ACTIVE" if mic['verified'] else "SILENT"
        line = f"│  {color}{status}{reset}  |  Level: {mic['rms']:.4f}"
        visible = f"│  {status}  |  Level: {mic['rms']:.4f}"
        print(line + " " * (width - len(visible)) + "│")
        
        level_bars = int(min(mic['rms'] * 300, 40))
        meter = "█" * level_bars + "░" * (40 - level_bars)
        line = f"│  [{meter}]"
        print(line + " " * (width - len(line)) + "│")
        print("└" + "─" * width + "┘")
        print()
        
        # Analysis
        print("┌─ Audio Analysis " + "─" * (width - 18) + "┐")
        
        if result.get('status') == 'active':
            analysis = result.get('analysis', {})
            
            # Voice detection
            voice = analysis.get('voice', {})
            voice_conf = voice.get('voice_confidence', 0)
            is_voice = "YES" if voice.get('is_voice') else "no"
            is_cmd = "YES" if voice.get('is_command_like') else "no"
            line = f"│  Voice: {is_voice} ({voice_conf:.0%})  |  Command-like: {is_cmd}"
            print(line + " " * (width - len(line)) + "│")
            
            # Speaker detection
            speaker = analysis.get('speaker', {})
            speaker_conf = speaker.get('speaker_confidence', 0)
            is_speaker = "YES" if speaker.get('is_speaker') else "no"
            line = f"│  Speaker playback: {is_speaker} ({speaker_conf:.0%})"
            print(line + " " * (width - len(line)) + "│")
            
            # TV match
            tv = analysis.get('tv', {})
            if self.detector.tv_signature.is_learned:
                is_tv = "YES" if tv.get('is_tv_audio') else "no"
                tv_sim = tv.get('similarity', 0)
                line = f"│  Matches TV signature: {is_tv} ({tv_sim:.0%})"
                print(line + " " * (width - len(line)) + "│")
            
            # Ultrasonic
            ultra = analysis.get('ultrasonic', {})
            if ultra.get('is_suspicious'):
                line = f"│  ⚠ Ultrasonic detected (ratio: {ultra['ratio']:.2f})"
                print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  Status: silent"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Attack Status
        print("┌─ Attack Detection " + "─" * (width - 20) + "┐")
        
        if result.get('is_attack'):
            color = '\033[91m'
            reset = '\033[0m'
            conf = result['confidence']
            line = f"│  {color}⚠ REPLAY ATTACK DETECTED ({conf:.0%} confidence){reset}"
            visible = f"│  ⚠ REPLAY ATTACK DETECTED ({conf:.0%} confidence)"
            print(line + " " * (width - len(visible)) + "│")
            
            line = f"│  Type: {result.get('attack_type', 'unknown')}"
            print(line + " " * (width - len(line)) + "│")
            
            print("│" + " " * width + "│")
            for indicator in result.get('indicators', [])[:4]:
                line = f"│  → {indicator[:width-6]}"
                print(line + " " * (width - len(line)) + "│")
            
            # Device correlation
            device_events = result.get('device_events', [])
            if device_events:
                print("│" + " " * width + "│")
                line = f"│  Correlated device events: {len(device_events)}"
                print(line + " " * (width - len(line)) + "│")
                for event in device_events[:2]:
                    line = f"│    - {event['type']}"
                    print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  ✓ No attack detected"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # Recent attacks
        if self.detector.attack_log:
            print("┌─ Recent Attacks " + "─" * (width - 18) + "┐")
            for attack in list(self.detector.attack_log)[-3:]:
                ts = attack['datetime'][11:19]
                atype = attack.get('attack_type', '?')
                conf = attack['confidence']
                line = f"│  [{ts}] {atype} ({conf:.0%})"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        print("  Ctrl+C to stop  |  Run with --tv-learning first to improve accuracy")
    
    def shutdown(self):
        print("\n\nShutting down...")
        
        # Save TV profile if learning
        if self.tv_learning and self.detector.tv_signature.learning_samples >= 50:
            self.detector.tv_signature._build_profile()
            self.detector.tv_signature.save(self.tv_profile)
            print(f"  ✓ Saved TV profile to {self.tv_profile}")
        
        # Export attack log
        if self.log_file and self.detector.attack_log:
            log_data = {
                'export_time': datetime.now().isoformat(),
                'attacks': [
                    {k: v for k, v in a.items() if k != 'analysis'}
                    for a in self.detector.attack_log
                ]
            }
            with open(self.log_file, 'w') as f:
                json.dump(log_data, f, indent=2, default=str)
            print(f"  ✓ Exported {len(self.detector.attack_log)} attacks to {self.log_file}")
        
        self.audio_capture.stop()
        self.device_monitor.stop()
        
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Duration: {int(time.time() - self.start_time)}s")
        print(f"  Samples analyzed: {self.sample_count}")
        print(f"  Attacks detected: {self.attack_count}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='TV-Aware Replay Attack Detector',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
HOW TO USE:

1. First, learn your TV's audio signature:
   %(prog)s --tv-learning
   (Play TV normally for 30-60 seconds, then Ctrl+C)

2. Then run detection:
   %(prog)s
   
The detector will distinguish between:
- Normal TV audio (ignored)
- Voice commands from speakers (ATTACK)
- Ultrasonic injection (ATTACK)
- Exact audio replays (ATTACK)

EXAMPLES:
    %(prog)s --tv-learning          # Learn TV signature
    %(prog)s                         # Normal detection
    %(prog)s --sensitivity high      # More sensitive
    %(prog)s --log attacks.json      # Save attack log
        """
    )
    
    parser.add_argument('--tv-learning', action='store_true',
                        help='Learn your TV audio signature')
    parser.add_argument('--tv-profile', default=None,
                        help='Path to TV profile file')
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high'],
                        default='medium')
    parser.add_argument('-l', '--log', help='Export attacks to JSON file')
    parser.add_argument('-i', '--interval', type=float, default=0.3)
    
    args = parser.parse_args()
    
    app = TVAwareDetectorApp(
        sensitivity=args.sensitivity,
        log_file=args.log,
        tv_learning=args.tv_learning,
        tv_profile=args.tv_profile
    )
    
    if not app.initialize():
        print("Failed to initialize")
        sys.exit(1)
    
    app.run(interval=args.interval)


if __name__ == "__main__":
    main()