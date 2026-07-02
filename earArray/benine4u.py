#!/usr/bin/env python3
"""
DolphinAttack Replay Attack Detector
=====================================

Detects whether ultrasonic signals are likely from:
  A) Environmental sources (TV, electronics, interference)
  B) Active replay attack (speaker playing ultrasonic commands)

Replay attack indicators:
  - Modulated carrier waves (AM/FM patterns)
  - Speech-like temporal patterns in ultrasonic band
  - Compression artifacts from recorded audio
  - Unnatural spectral patterns (too clean/synthetic)
  - Speaker frequency response characteristics
  - Repeated identical patterns (recorded loops)

Usage:
    python replay_detector.py                    # Real-time monitoring
    python replay_detector.py --analyze FILE    # Analyze saved .wav file
"""

import numpy as np
import threading
import queue
import time
import argparse
import os
import sys
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict
from collections import deque
import json
import warnings
warnings.filterwarnings('ignore')

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    from scipy import signal as scipy_signal
    from scipy.io import wavfile
    from scipy.stats import entropy, kurtosis, skew
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("WARNING: scipy required. Run: pip install scipy")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    sample_rate: int = 44100
    channels: int = 2
    chunk_size: int = 8820  # 200ms for better analysis
    device_index: Optional[int] = None
    
    # Analysis windows
    fft_size: int = 4096
    
    # Thresholds
    replay_confidence_threshold: float = 0.6
    

# =============================================================================
# REPLAY ATTACK ANALYZER
# =============================================================================

class ReplayAttackAnalyzer:
    """
    Analyzes audio to determine if ultrasonic signals are from 
    active replay attacks vs passive environmental sources.
    """
    
    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self.nyquist = sample_rate / 2
        
        # History for pattern matching
        self.spectral_history = deque(maxlen=50)
        self.detection_history = deque(maxlen=100)
        
    def analyze(self, audio: np.ndarray) -> Dict:
        """
        Comprehensive replay attack analysis.
        Returns dict with threat assessment and evidence.
        """
        if audio.ndim > 1:
            mono = np.mean(audio, axis=0)
        else:
            mono = audio
            
        results = {
            'timestamp': datetime.now().isoformat(),
            'is_replay_attack': False,
            'confidence': 0.0,
            'threat_level': 'UNKNOWN',
            'indicators': [],
            'evidence': {}
        }
        
        # Run all detection methods
        indicators = []
        scores = []
        
        # 1. Check for modulated carrier (key sign of DolphinAttack)
        mod_result = self._detect_modulated_carrier(mono)
        results['evidence']['modulation'] = mod_result
        if mod_result['detected']:
            indicators.append(f"⚠️  MODULATED CARRIER at {mod_result['carrier_freq']:.0f} Hz")
            scores.append(mod_result['confidence'] * 0.35)
            
        # 2. Check for speech-like patterns in ultrasonic band
        speech_result = self._detect_ultrasonic_speech(mono)
        results['evidence']['speech_patterns'] = speech_result
        if speech_result['detected']:
            indicators.append(f"⚠️  SPEECH PATTERNS in ultrasonic band")
            scores.append(speech_result['confidence'] * 0.25)
            
        # 3. Check for synthetic/artificial signal characteristics
        synth_result = self._detect_synthetic_signal(mono)
        results['evidence']['synthetic'] = synth_result
        if synth_result['detected']:
            indicators.append(f"⚠️  SYNTHETIC signal characteristics")
            scores.append(synth_result['confidence'] * 0.15)
            
        # 4. Check for speaker playback artifacts
        speaker_result = self._detect_speaker_artifacts(mono)
        results['evidence']['speaker'] = speaker_result
        if speaker_result['detected']:
            indicators.append(f"⚠️  SPEAKER PLAYBACK artifacts detected")
            scores.append(speaker_result['confidence'] * 0.15)
            
        # 5. Check for repeated patterns (looped attack)
        repeat_result = self._detect_repeated_patterns(mono)
        results['evidence']['repetition'] = repeat_result
        if repeat_result['detected']:
            indicators.append(f"⚠️  REPEATED PATTERN (possible loop)")
            scores.append(repeat_result['confidence'] * 0.10)
            
        # 6. Check temporal envelope (attacks have speech-like envelope)
        envelope_result = self._analyze_temporal_envelope(mono)
        results['evidence']['envelope'] = envelope_result
        if envelope_result['is_speech_like']:
            indicators.append(f"⚠️  SPEECH-LIKE temporal envelope")
            scores.append(envelope_result['confidence'] * 0.15)
            
        # 7. Check for compression artifacts
        compress_result = self._detect_compression_artifacts(mono)
        results['evidence']['compression'] = compress_result
        if compress_result['detected']:
            indicators.append(f"⚠️  COMPRESSION ARTIFACTS (recorded audio)")
            scores.append(compress_result['confidence'] * 0.10)
        
        # Calculate overall confidence
        total_confidence = min(sum(scores), 1.0)
        results['confidence'] = total_confidence
        results['indicators'] = indicators
        
        # Determine threat level
        if total_confidence > 0.75:
            results['is_replay_attack'] = True
            results['threat_level'] = 'HIGH - LIKELY ACTIVE ATTACK'
        elif total_confidence > 0.5:
            results['is_replay_attack'] = True
            results['threat_level'] = 'MEDIUM - POSSIBLE ATTACK'
        elif total_confidence > 0.3:
            results['threat_level'] = 'LOW - SUSPICIOUS'
        else:
            results['threat_level'] = 'MINIMAL - LIKELY ENVIRONMENTAL'
            
        # Add to history
        self.detection_history.append({
            'time': time.time(),
            'confidence': total_confidence,
            'is_attack': results['is_replay_attack']
        })
        
        return results
        
    def _detect_modulated_carrier(self, signal: np.ndarray) -> Dict:
        """
        Detect amplitude-modulated carrier wave.
        DolphinAttacks modulate voice commands onto ultrasonic carrier.
        """
        result = {
            'detected': False,
            'carrier_freq': 0,
            'modulation_freq': 0,
            'modulation_depth': 0,
            'confidence': 0
        }
        
        if not HAS_SCIPY:
            return result
            
        # Bandpass filter to ultrasonic range
        try:
            sos = scipy_signal.butter(4, [15000, self.nyquist * 0.95], 
                                      btype='band', fs=self.sample_rate, output='sos')
            ultrasonic = scipy_signal.sosfilt(sos, signal)
        except Exception:
            return result
            
        # Find carrier frequency
        spectrum = np.abs(np.fft.rfft(ultrasonic))
        freqs = np.fft.rfftfreq(len(ultrasonic), 1/self.sample_rate)
        
        # Look in ultrasonic range
        ultra_mask = freqs > 15000
        if not np.any(ultra_mask):
            return result
            
        ultra_spectrum = spectrum[ultra_mask]
        ultra_freqs = freqs[ultra_mask]
        
        if len(ultra_spectrum) == 0:
            return result
            
        carrier_idx = np.argmax(ultra_spectrum)
        carrier_freq = ultra_freqs[carrier_idx]
        carrier_power = ultra_spectrum[carrier_idx]
        
        # Demodulate (envelope detection)
        analytic = scipy_signal.hilbert(ultrasonic)
        envelope = np.abs(analytic)
        
        # Check envelope for voice-frequency content (100-4000 Hz)
        env_spectrum = np.abs(np.fft.rfft(envelope))
        env_freqs = np.fft.rfftfreq(len(envelope), 1/self.sample_rate)
        
        voice_mask = (env_freqs > 100) & (env_freqs < 4000)
        if np.any(voice_mask):
            voice_power = np.mean(env_spectrum[voice_mask])
            dc_power = env_spectrum[0] + 1e-10
            
            # Modulation index
            modulation_depth = voice_power / dc_power
            
            if modulation_depth > 0.1:  # Significant modulation
                result['detected'] = True
                result['carrier_freq'] = float(carrier_freq)
                result['modulation_depth'] = float(modulation_depth)
                result['confidence'] = min(modulation_depth * 2, 1.0)
                
                # Find dominant modulation frequency
                voice_spectrum = env_spectrum[voice_mask]
                voice_freq_range = env_freqs[voice_mask]
                mod_idx = np.argmax(voice_spectrum)
                result['modulation_freq'] = float(voice_freq_range[mod_idx])
                
        return result
        
    def _detect_ultrasonic_speech(self, signal: np.ndarray) -> Dict:
        """
        Detect speech-like patterns in ultrasonic band.
        Real attacks carry voice commands.
        """
        result = {
            'detected': False,
            'formant_like_peaks': 0,
            'temporal_variation': 0,
            'confidence': 0
        }
        
        if not HAS_SCIPY:
            return result
            
        try:
            # Extract ultrasonic band
            sos = scipy_signal.butter(4, [15000, self.nyquist * 0.95],
                                      btype='band', fs=self.sample_rate, output='sos')
            ultrasonic = scipy_signal.sosfilt(sos, signal)
        except Exception:
            return result
            
        # Compute spectrogram
        f, t, Sxx = scipy_signal.spectrogram(ultrasonic, self.sample_rate,
                                              nperseg=512, noverlap=256)
        
        if Sxx.size == 0:
            return result
            
        # Check for formant-like spectral peaks (speech has 3-5 formants)
        mean_spectrum = np.mean(Sxx, axis=1)
        if len(mean_spectrum) < 10:
            return result
            
        # Count peaks
        peaks, _ = scipy_signal.find_peaks(mean_spectrum, prominence=np.std(mean_spectrum))
        result['formant_like_peaks'] = len(peaks)
        
        # Check temporal variation (speech varies, noise doesn't)
        temporal_std = np.std(Sxx, axis=1)
        temporal_mean = np.mean(Sxx, axis=1) + 1e-10
        variation_ratio = np.mean(temporal_std / temporal_mean)
        result['temporal_variation'] = float(variation_ratio)
        
        # Speech typically has 3-5 formants and high temporal variation
        if len(peaks) >= 2 and variation_ratio > 0.3:
            result['detected'] = True
            result['confidence'] = min(0.3 + variation_ratio + len(peaks) * 0.1, 1.0)
            
        return result
        
    def _detect_synthetic_signal(self, signal: np.ndarray) -> Dict:
        """
        Detect artificially generated signals.
        Synthetic signals have unnaturally low noise and high spectral purity.
        """
        result = {
            'detected': False,
            'spectral_flatness': 0,
            'kurtosis': 0,
            'crest_factor': 0,
            'confidence': 0
        }
        
        if not HAS_SCIPY:
            return result
            
        try:
            sos = scipy_signal.butter(4, 15000, btype='high', 
                                      fs=self.sample_rate, output='sos')
            ultrasonic = scipy_signal.sosfilt(sos, signal)
        except Exception:
            return result
            
        if np.std(ultrasonic) < 1e-10:
            return result
            
        # Spectral flatness (synthetic = low, noise = high)
        spectrum = np.abs(np.fft.rfft(ultrasonic)) + 1e-10
        geometric_mean = np.exp(np.mean(np.log(spectrum)))
        arithmetic_mean = np.mean(spectrum)
        flatness = geometric_mean / arithmetic_mean
        result['spectral_flatness'] = float(flatness)
        
        # Kurtosis (synthetic often has high kurtosis)
        kurt = kurtosis(ultrasonic)
        result['kurtosis'] = float(kurt)
        
        # Crest factor
        rms = np.sqrt(np.mean(ultrasonic**2))
        peak = np.max(np.abs(ultrasonic))
        crest = peak / (rms + 1e-10)
        result['crest_factor'] = float(crest)
        
        # Synthetic signals: low flatness, high kurtosis, specific crest
        synthetic_score = 0
        if flatness < 0.1:  # Very tonal
            synthetic_score += 0.4
        if kurt > 5:  # Spiky
            synthetic_score += 0.3
        if 3 < crest < 10:  # Typical for synthesized tones
            synthetic_score += 0.2
            
        if synthetic_score > 0.5:
            result['detected'] = True
            result['confidence'] = synthetic_score
            
        return result
        
    def _detect_speaker_artifacts(self, signal: np.ndarray) -> Dict:
        """
        Detect artifacts from speaker playback.
        Speakers have frequency response limitations and introduce distortion.
        """
        result = {
            'detected': False,
            'harmonic_distortion': 0,
            'frequency_rolloff': 0,
            'confidence': 0
        }
        
        if not HAS_SCIPY:
            return result
            
        # Get spectrum
        spectrum = np.abs(np.fft.rfft(signal))
        freqs = np.fft.rfftfreq(len(signal), 1/self.sample_rate)
        
        # Check for speaker frequency response (rolloff above 18-20kHz)
        if len(freqs) < 100:
            return result
            
        # Most speakers can't reproduce above 20kHz well
        mask_18k = (freqs > 17000) & (freqs < 19000)
        mask_20k = (freqs > 20000) & (freqs < 22000)
        
        if np.any(mask_18k) and np.any(mask_20k):
            power_18k = np.mean(spectrum[mask_18k])
            power_20k = np.mean(spectrum[mask_20k]) + 1e-10
            
            rolloff_ratio = power_18k / power_20k
            result['frequency_rolloff'] = float(rolloff_ratio)
            
            # Speakers typically show 6-12dB rolloff above 18kHz
            if rolloff_ratio > 2:  # More than 6dB difference
                result['detected'] = True
                result['confidence'] = min(rolloff_ratio / 10, 0.8)
                
        # Check for harmonic distortion (speakers introduce harmonics)
        try:
            sos = scipy_signal.butter(4, [15000, self.nyquist * 0.95],
                                      btype='band', fs=self.sample_rate, output='sos')
            ultrasonic = scipy_signal.sosfilt(sos, signal)
            
            # Find fundamental
            ultra_spectrum = np.abs(np.fft.rfft(ultrasonic))
            ultra_freqs = np.fft.rfftfreq(len(ultrasonic), 1/self.sample_rate)
            
            if len(ultra_spectrum) > 0:
                fund_idx = np.argmax(ultra_spectrum)
                fund_freq = ultra_freqs[fund_idx]
                fund_power = ultra_spectrum[fund_idx]
                
                # Check for 2nd and 3rd harmonics
                harmonic_power = 0
                for h in [2, 3]:
                    h_freq = fund_freq * h
                    if h_freq < self.nyquist:
                        h_idx = np.searchsorted(ultra_freqs, h_freq)
                        if h_idx < len(ultra_spectrum):
                            harmonic_power += ultra_spectrum[h_idx]
                            
                if fund_power > 0:
                    thd = harmonic_power / fund_power
                    result['harmonic_distortion'] = float(thd)
                    
                    if thd > 0.05:  # More than 5% THD suggests speaker
                        result['detected'] = True
                        result['confidence'] = max(result['confidence'], min(thd * 5, 0.7))
        except Exception:
            pass
                        
        return result
        
    def _detect_repeated_patterns(self, signal: np.ndarray) -> Dict:
        """
        Detect repeated patterns that suggest a looped recording.
        """
        result = {
            'detected': False,
            'autocorr_peak': 0,
            'repeat_interval_ms': 0,
            'confidence': 0
        }
        
        if not HAS_SCIPY:
            return result
            
        try:
            sos = scipy_signal.butter(4, 15000, btype='high',
                                      fs=self.sample_rate, output='sos')
            ultrasonic = scipy_signal.sosfilt(sos, signal)
        except Exception:
            return result
            
        # Autocorrelation
        if len(ultrasonic) < 1000:
            return result
            
        autocorr = np.correlate(ultrasonic, ultrasonic, mode='full')
        autocorr = autocorr[len(autocorr)//2:]  # Keep positive lags
        autocorr = autocorr / (autocorr[0] + 1e-10)  # Normalize
        
        # Find peaks (excluding zero-lag)
        min_lag = int(0.05 * self.sample_rate)  # Minimum 50ms
        max_lag = min(len(autocorr) - 1, int(0.5 * self.sample_rate))  # Maximum 500ms
        
        if max_lag <= min_lag:
            return result
            
        search_region = autocorr[min_lag:max_lag]
        if len(search_region) == 0:
            return result
            
        peak_idx = np.argmax(search_region) + min_lag
        peak_value = autocorr[peak_idx]
        
        result['autocorr_peak'] = float(peak_value)
        result['repeat_interval_ms'] = float(peak_idx / self.sample_rate * 1000)
        
        # Strong autocorrelation suggests repetition
        if peak_value > 0.5:
            result['detected'] = True
            result['confidence'] = float(peak_value)
            
        return result
        
    def _analyze_temporal_envelope(self, signal: np.ndarray) -> Dict:
        """
        Analyze temporal envelope for speech-like characteristics.
        Speech has specific attack/decay patterns.
        """
        result = {
            'is_speech_like': False,
            'envelope_variance': 0,
            'zero_crossing_rate': 0,
            'syllable_rate': 0,
            'confidence': 0
        }
        
        if not HAS_SCIPY:
            return result
            
        try:
            sos = scipy_signal.butter(4, 15000, btype='high',
                                      fs=self.sample_rate, output='sos')
            ultrasonic = scipy_signal.sosfilt(sos, signal)
        except Exception:
            return result
            
        # Get envelope
        analytic = scipy_signal.hilbert(ultrasonic)
        envelope = np.abs(analytic)
        
        # Smooth envelope
        window = int(0.01 * self.sample_rate)  # 10ms window
        if window > 0 and len(envelope) > window:
            envelope_smooth = np.convolve(envelope, np.ones(window)/window, mode='valid')
        else:
            envelope_smooth = envelope
            
        if len(envelope_smooth) < 10:
            return result
            
        # Envelope variance (speech has high variance)
        env_var = np.var(envelope_smooth) / (np.mean(envelope_smooth)**2 + 1e-10)
        result['envelope_variance'] = float(env_var)
        
        # Zero crossing rate of envelope (syllable boundaries)
        env_centered = envelope_smooth - np.mean(envelope_smooth)
        zcr = np.sum(np.abs(np.diff(np.sign(env_centered)))) / (2 * len(env_centered))
        result['zero_crossing_rate'] = float(zcr)
        
        # Estimate syllable rate (speech: 3-7 syllables/sec)
        # Low-pass filter envelope and count peaks
        try:
            sos_lp = scipy_signal.butter(2, 10, btype='low', 
                                         fs=self.sample_rate, output='sos')
            env_lp = scipy_signal.sosfilt(sos_lp, envelope_smooth)
            peaks, _ = scipy_signal.find_peaks(env_lp, distance=int(0.1*self.sample_rate))
            duration = len(signal) / self.sample_rate
            syllable_rate = len(peaks) / duration if duration > 0 else 0
            result['syllable_rate'] = float(syllable_rate)
        except Exception:
            syllable_rate = 0
            
        # Speech-like: high envelope variance, moderate ZCR, 3-7 syllables/sec
        speech_score = 0
        if env_var > 0.5:
            speech_score += 0.3
        if 0.01 < zcr < 0.1:
            speech_score += 0.3
        if 2 < syllable_rate < 10:
            speech_score += 0.4
            
        if speech_score > 0.5:
            result['is_speech_like'] = True
            result['confidence'] = speech_score
            
        return result
        
    def _detect_compression_artifacts(self, signal: np.ndarray) -> Dict:
        """
        Detect MP3/AAC compression artifacts.
        Recorded/transmitted audio often has compression.
        """
        result = {
            'detected': False,
            'spectral_holes': 0,
            'quantization_noise': 0,
            'confidence': 0
        }
        
        # Get high-resolution spectrum
        spectrum = np.abs(np.fft.rfft(signal, n=8192))
        freqs = np.fft.rfftfreq(8192, 1/self.sample_rate)
        
        # MP3 has characteristic cutoff and spectral holes
        # Check for hard cutoff (MP3 typically cuts at 16-20kHz depending on bitrate)
        high_freq_mask = freqs > 18000
        low_freq_mask = (freqs > 10000) & (freqs < 15000)
        
        if np.any(high_freq_mask) and np.any(low_freq_mask):
            high_power = np.mean(spectrum[high_freq_mask])
            low_power = np.mean(spectrum[low_freq_mask]) + 1e-10
            
            # Sharp cutoff suggests MP3
            if high_power / low_power < 0.01:
                result['detected'] = True
                result['spectral_holes'] = 1
                result['confidence'] = 0.5
                
        # Check for quantization noise patterns
        # (Not fully implemented - would need more sophisticated analysis)
        
        return result
        
    def get_historical_analysis(self) -> Dict:
        """
        Analyze detection history for patterns.
        """
        if len(self.detection_history) < 5:
            return {'status': 'insufficient_data'}
            
        confidences = [d['confidence'] for d in self.detection_history]
        attacks = [d['is_attack'] for d in self.detection_history]
        
        return {
            'total_samples': len(self.detection_history),
            'attack_percentage': sum(attacks) / len(attacks) * 100,
            'mean_confidence': np.mean(confidences),
            'max_confidence': max(confidences),
            'trend': 'INCREASING' if len(confidences) > 10 and 
                     np.mean(confidences[-5:]) > np.mean(confidences[:5]) else 'STABLE'
        }


# =============================================================================
# REAL-TIME MONITOR
# =============================================================================

class ReplayMonitor:
    """Real-time monitoring for replay attacks."""
    
    def __init__(self, config: Config):
        self.config = config
        self.analyzer = ReplayAttackAnalyzer(config.sample_rate)
        self.is_running = False
        self.audio_queue = queue.Queue(maxsize=50)
        self.stream = None
        
        # Stats
        self.total_windows = 0
        self.attack_detections = 0
        
    def start(self):
        if not HAS_SOUNDDEVICE:
            raise RuntimeError("sounddevice required: pip install sounddevice")
            
        def callback(indata, frames, time_info, status):
            audio = indata.T.copy()
            try:
                self.audio_queue.put_nowait(audio)
            except queue.Full:
                pass
                
        self.stream = sd.InputStream(
            device=self.config.device_index,
            channels=self.config.channels,
            samplerate=self.config.sample_rate,
            blocksize=self.config.chunk_size,
            callback=callback
        )
        
        self.stream.start()
        self.is_running = True
        
    def stop(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            
    def run(self, duration: Optional[float] = None):
        """Run real-time monitoring."""
        self.start()
        
        print(f"\n{'='*70}")
        print("  REPLAY ATTACK DETECTOR")
        print(f"{'='*70}")
        print("\n  Analyzing audio for signs of active replay attacks...")
        print("  (Looking for: modulated carriers, speech patterns, speaker artifacts)")
        print(f"\n  Press Ctrl+C to stop\n")
        print(f"{'='*70}\n")
        
        start_time = time.time()
        last_status = time.time()
        
        try:
            while self.is_running:
                if duration and (time.time() - start_time) > duration:
                    break
                    
                try:
                    audio = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                    
                self.total_windows += 1
                
                # Analyze
                result = self.analyzer.analyze(audio)
                
                # Print alerts
                if result['is_replay_attack']:
                    self.attack_detections += 1
                    self._print_alert(result)
                elif result['confidence'] > 0.3:
                    self._print_warning(result)
                    
                # Periodic status
                if time.time() - last_status > 10:
                    self._print_status()
                    last_status = time.time()
                    
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            self.stop()
            self._print_summary()
            
    def _print_alert(self, result: Dict):
        """Print high-confidence alert."""
        print(f"\n{'!'*70}")
        print(f"  🚨 POSSIBLE REPLAY ATTACK DETECTED 🚨")
        print(f"{'!'*70}")
        print(f"  Time: {result['timestamp']}")
        print(f"  Threat Level: {result['threat_level']}")
        print(f"  Confidence: {result['confidence']:.1%}")
        print(f"\n  Indicators:")
        for indicator in result['indicators']:
            print(f"    {indicator}")
            
        # Print key evidence
        evidence = result['evidence']
        if evidence.get('modulation', {}).get('detected'):
            mod = evidence['modulation']
            print(f"\n  Modulation Analysis:")
            print(f"    Carrier: {mod['carrier_freq']:.0f} Hz")
            print(f"    Modulation depth: {mod['modulation_depth']:.2f}")
            
        print(f"{'!'*70}\n")
        print('\a', end='', flush=True)  # Beep
        
    def _print_warning(self, result: Dict):
        """Print low-confidence warning."""
        indicators = ', '.join([i.replace('⚠️  ', '') for i in result['indicators'][:2]])
        print(f"  ⚠️  Suspicious ({result['confidence']:.0%}): {indicators}")
        
    def _print_status(self):
        """Print periodic status."""
        hist = self.analyzer.get_historical_analysis()
        if hist.get('status') == 'insufficient_data':
            print(f"  [STATUS] Windows: {self.total_windows}, Attacks: {self.attack_detections}")
        else:
            print(f"  [STATUS] Windows: {self.total_windows}, "
                  f"Attack signals: {hist['attack_percentage']:.1f}%, "
                  f"Trend: {hist['trend']}")
            
    def _print_summary(self):
        """Print final summary."""
        print(f"\n{'='*70}")
        print("  ANALYSIS SUMMARY")
        print(f"{'='*70}")
        print(f"  Total windows analyzed: {self.total_windows}")
        print(f"  Attack detections: {self.attack_detections}")
        
        hist = self.analyzer.get_historical_analysis()
        if hist.get('status') != 'insufficient_data':
            print(f"  Attack signal percentage: {hist['attack_percentage']:.1f}%")
            print(f"  Peak confidence: {hist['max_confidence']:.1%}")
            
        if self.attack_detections > 0:
            print(f"\n  ⚠️  REPLAY ATTACK INDICATORS FOUND")
            print(f"  Recommendations:")
            print(f"    1. Check for unknown devices nearby")
            print(f"    2. Look for directional speakers/ultrasonic emitters")
            print(f"    3. Disable voice assistants temporarily")
            print(f"    4. Check phone apps for suspicious background audio")
        else:
            print(f"\n  ✓ No strong replay attack indicators detected")
            print(f"  Signals appear to be environmental/electronic interference")
            
        print(f"{'='*70}\n")


# =============================================================================
# FILE ANALYZER
# =============================================================================

def analyze_file(filepath: str):
    """Analyze a saved WAV file for replay attack indicators."""
    if not HAS_SCIPY:
        print("scipy required: pip install scipy")
        return
        
    print(f"\nAnalyzing: {filepath}")
    
    try:
        sample_rate, audio = wavfile.read(filepath)
    except Exception as e:
        print(f"Error reading file: {e}")
        return
        
    # Convert to float
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483648.0
        
    # Use mono
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
        
    analyzer = ReplayAttackAnalyzer(sample_rate)
    result = analyzer.analyze(audio)
    
    print(f"\n{'='*70}")
    print("  FILE ANALYSIS RESULT")
    print(f"{'='*70}")
    print(f"  File: {os.path.basename(filepath)}")
    print(f"  Duration: {len(audio)/sample_rate:.2f} seconds")
    print(f"  Sample rate: {sample_rate} Hz")
    print(f"\n  Threat Level: {result['threat_level']}")
    print(f"  Confidence: {result['confidence']:.1%}")
    
    if result['indicators']:
        print(f"\n  Indicators found:")
        for indicator in result['indicators']:
            print(f"    {indicator}")
    else:
        print(f"\n  No replay attack indicators found")
        
    # Detailed evidence
    print(f"\n  Detailed Analysis:")
    for key, value in result['evidence'].items():
        if isinstance(value, dict) and value.get('detected'):
            print(f"    {key}: DETECTED (conf: {value.get('confidence', 0):.1%})")
        elif isinstance(value, dict):
            print(f"    {key}: not detected")
            
    print(f"{'='*70}\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Replay Attack Detector')
    parser.add_argument('--device', type=int, help='Audio device index')
    parser.add_argument('--duration', type=float, help='Monitoring duration (seconds)')
    parser.add_argument('--analyze', type=str, help='Analyze a WAV file')
    parser.add_argument('--list-devices', action='store_true')
    
    args = parser.parse_args()
    
    if args.list_devices:
        if HAS_SOUNDDEVICE:
            print(sd.query_devices())
        return
        
    if args.analyze:
        analyze_file(args.analyze)
        return
        
    config = Config(device_index=args.device)
    monitor = ReplayMonitor(config)
    monitor.run(duration=args.duration)


if __name__ == '__main__':
    main()