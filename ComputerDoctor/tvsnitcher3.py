#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audio Injection Source Analyzer
================================
Characterizes the source of detected audio injection attacks by analyzing:
- Waveform signatures (recording vs live)
- Frequency response (speaker/transducer fingerprinting)
- Background noise patterns (environment identification)
- Ultrasonic carriers (covert channel detection)
- Temporal patterns (automated vs manual injection)
- RF correlation (satellite source identification)

Hardware: Dodotronic Ultramic 384K, Rode Mic, HackRF, RTL-SDR
"""

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.fft import fft, fftfreq
from scipy.stats import kurtosis, skew
from scipy.ndimage import uniform_filter1d
import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# Optional imports
try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    print("sounddevice not available - live capture disabled")

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("matplotlib not available - plotting disabled")


@dataclass
class InjectionCharacteristics:
    """Comprehensive characterization of an injection source"""
    timestamp: str
    
    # Source type classification
    source_type: str  # 'speaker', 'ultrasonic_transducer', 'bone_conduction', 'rf_demod', 'unknown'
    source_confidence: float
    
    # Recording signatures
    is_recording: bool
    recording_confidence: float
    recording_indicators: List[str]
    
    # Frequency analysis
    frequency_range_hz: Tuple[float, float]
    dominant_frequencies_hz: List[float]
    bandwidth_hz: float
    spectral_centroid_hz: float
    
    # Speaker/transducer fingerprint
    speaker_resonances_hz: List[float]
    estimated_speaker_size: str  # 'small', 'medium', 'large'
    frequency_response_quality: str  # 'phone', 'laptop', 'hifi', 'pa_system'
    
    # Background noise analysis
    noise_floor_db: float
    noise_type: str  # 'static', 'environmental', 'digital', 'rf_interference'
    snr_db: float
    
    # Ultrasonic analysis
    has_ultrasonic_carrier: bool
    ultrasonic_freq_hz: Optional[float]
    ultrasonic_modulation: Optional[str]  # 'AM', 'FM', 'none'
    
    # Temporal patterns
    injection_duration_sec: float
    repeat_interval_sec: Optional[float]
    is_automated: bool
    
    # Spatial estimation (if multi-mic)
    estimated_direction_deg: Optional[float]
    estimated_distance_m: Optional[float]
    
    # RF correlation
    rf_correlation: bool
    rf_frequency_mhz: Optional[float]
    rf_satellite_band: Optional[str]
    rf_time_delta_ms: Optional[float]


class InjectionSourceAnalyzer:
    """
    Analyzes audio to characterize injection attack sources
    """
    
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.results = []
        
        # Known speaker frequency response signatures
        self.speaker_signatures = {
            'phone': {'low_cutoff': 200, 'high_cutoff': 8000, 'resonances': [800, 2500]},
            'laptop': {'low_cutoff': 150, 'high_cutoff': 12000, 'resonances': [500, 3000]},
            'bluetooth': {'low_cutoff': 100, 'high_cutoff': 15000, 'resonances': [400, 2000, 8000]},
            'hifi': {'low_cutoff': 40, 'high_cutoff': 20000, 'resonances': []},
            'pa_system': {'low_cutoff': 60, 'high_cutoff': 18000, 'resonances': [120, 250]},
            'ultrasonic_transducer': {'low_cutoff': 18000, 'high_cutoff': 100000, 'resonances': [25000, 40000]},
        }
        
    def analyze_audio(self, audio_data: np.ndarray, 
                      sample_rate: int = None,
                      rf_events: List[Dict] = None) -> InjectionCharacteristics:
        """
        Comprehensive analysis of audio segment
        """
        if sample_rate:
            self.sample_rate = sample_rate
            
        # Normalize audio
        audio = audio_data.astype(np.float32)
        if audio.ndim > 1:
            audio = audio[:, 0]
        audio = audio / (np.max(np.abs(audio)) + 1e-10)
        
        print("\n" + "=" * 60)
        print("INJECTION SOURCE ANALYSIS")
        print("=" * 60)
        
        # 1. Recording detection
        print("\n[1/8] Analyzing recording signatures...")
        is_recording, rec_confidence, rec_indicators = self._detect_recording(audio)
        
        # 2. Frequency analysis
        print("[2/8] Analyzing frequency content...")
        freq_analysis = self._analyze_frequency_content(audio)
        
        # 3. Speaker fingerprinting
        print("[3/8] Fingerprinting speaker/transducer...")
        speaker_info = self._fingerprint_speaker(audio, freq_analysis)
        
        # 4. Background noise analysis
        print("[4/8] Analyzing background noise...")
        noise_analysis = self._analyze_noise(audio)
        
        # 5. Ultrasonic analysis
        print("[5/8] Scanning for ultrasonic carriers...")
        ultrasonic = self._analyze_ultrasonic(audio)
        
        # 6. Temporal pattern analysis
        print("[6/8] Analyzing temporal patterns...")
        temporal = self._analyze_temporal_patterns(audio)
        
        # 7. Source type classification
        print("[7/8] Classifying source type...")
        source_type, source_conf = self._classify_source(
            freq_analysis, speaker_info, ultrasonic, noise_analysis
        )
        
        # 8. RF correlation
        print("[8/8] Correlating with RF events...")
        rf_corr = self._correlate_rf(rf_events) if rf_events else {
            'correlation': False, 'frequency': None, 'band': None, 'delta': None
        }
        
        # Build result
        result = InjectionCharacteristics(
            timestamp=datetime.now().isoformat(),
            source_type=source_type,
            source_confidence=source_conf,
            is_recording=is_recording,
            recording_confidence=rec_confidence,
            recording_indicators=rec_indicators,
            frequency_range_hz=freq_analysis['range'],
            dominant_frequencies_hz=freq_analysis['dominant'],
            bandwidth_hz=freq_analysis['bandwidth'],
            spectral_centroid_hz=freq_analysis['centroid'],
            speaker_resonances_hz=speaker_info['resonances'],
            estimated_speaker_size=speaker_info['size'],
            frequency_response_quality=speaker_info['quality'],
            noise_floor_db=noise_analysis['floor_db'],
            noise_type=noise_analysis['type'],
            snr_db=noise_analysis['snr_db'],
            has_ultrasonic_carrier=ultrasonic['has_carrier'],
            ultrasonic_freq_hz=ultrasonic['freq'],
            ultrasonic_modulation=ultrasonic['modulation'],
            injection_duration_sec=len(audio) / self.sample_rate,
            repeat_interval_sec=temporal['repeat_interval'],
            is_automated=temporal['is_automated'],
            estimated_direction_deg=None,  # Requires multi-mic
            estimated_distance_m=None,  # Requires calibration
            rf_correlation=rf_corr['correlation'],
            rf_frequency_mhz=rf_corr['frequency'],
            rf_satellite_band=rf_corr['band'],
            rf_time_delta_ms=rf_corr['delta']
        )
        
        self.results.append(result)
        self._print_analysis(result)
        
        return result
    
    def _detect_recording(self, audio: np.ndarray) -> Tuple[bool, float, List[str]]:
        """
        Detect if audio is from a recording vs live source
        """
        indicators = []
        scores = []
        
        # 1. Waveform consistency (recordings have unnaturally consistent envelopes)
        envelope = np.abs(signal.hilbert(audio))
        window_size = int(0.1 * self.sample_rate)  # 100ms windows
        
        # Calculate variance of variance (should be high for live audio)
        variances = []
        for i in range(0, len(envelope) - window_size, window_size // 2):
            variances.append(np.var(envelope[i:i+window_size]))
        
        var_of_var = np.std(variances) / (np.mean(variances) + 1e-10)
        
        if var_of_var < 0.3:  # Too consistent
            indicators.append("Waveform too consistent (envelope variance ratio: {:.2f})".format(var_of_var))
            scores.append(0.9)
        elif var_of_var < 0.5:
            indicators.append("Waveform somewhat consistent")
            scores.append(0.6)
        
        # 2. Background noise stationarity
        # Split into segments and compare noise floors
        n_segments = 10
        seg_len = len(audio) // n_segments
        noise_floors = []
        
        for i in range(n_segments):
            seg = audio[i*seg_len:(i+1)*seg_len]
            # Estimate noise floor from quietest portions
            sorted_amp = np.sort(np.abs(seg))
            noise_floors.append(np.mean(sorted_amp[:len(sorted_amp)//10]))
        
        noise_variation = np.std(noise_floors) / (np.mean(noise_floors) + 1e-10)
        
        if noise_variation < 0.1:  # Very static noise floor
            indicators.append("Static background noise (variation: {:.1%})".format(noise_variation))
            scores.append(0.85)
        elif noise_variation < 0.2:
            indicators.append("Relatively static background")
            scores.append(0.5)
        
        # 3. Spectral flatness consistency
        f, t, Sxx = signal.spectrogram(audio, fs=self.sample_rate, nperseg=1024)
        
        spectral_flatness = []
        for i in range(Sxx.shape[1]):
            col = Sxx[:, i] + 1e-10
            geo_mean = np.exp(np.mean(np.log(col)))
            arith_mean = np.mean(col)
            spectral_flatness.append(geo_mean / arith_mean)
        
        flatness_var = np.std(spectral_flatness) / (np.mean(spectral_flatness) + 1e-10)
        
        if flatness_var < 0.15:
            indicators.append("Spectral flatness too consistent")
            scores.append(0.7)
        
        # 4. Phase coherence (recordings often have perfect phase relationships)
        analytic = signal.hilbert(audio)
        inst_phase = np.unwrap(np.angle(analytic))
        phase_diff = np.diff(inst_phase)
        phase_consistency = 1 - (np.std(phase_diff) / (np.mean(np.abs(phase_diff)) + 1e-10))
        
        if phase_consistency > 0.8:
            indicators.append("Unnaturally coherent phase")
            scores.append(0.6)
        
        # 5. Clipping/compression artifacts (common in recordings)
        peak_ratio = np.sum(np.abs(audio) > 0.95) / len(audio)
        if peak_ratio > 0.001 and peak_ratio < 0.05:  # Some clipping but not natural
            indicators.append("Compression/limiting artifacts detected")
            scores.append(0.5)
        
        # 6. Lack of room acoustics variation
        # Natural audio has varying reverb characteristics
        # This is a simplified check
        autocorr = np.correlate(audio[:min(len(audio), self.sample_rate)], 
                               audio[:min(len(audio), self.sample_rate)], mode='full')
        autocorr = autocorr[len(autocorr)//2:]
        
        # Look for echo patterns (reverb)
        peaks, _ = signal.find_peaks(autocorr[int(0.01*self.sample_rate):], 
                                     height=np.max(autocorr) * 0.1)
        
        if len(peaks) < 3:  # Very few reflections = likely close-mic'd recording
            indicators.append("Minimal room acoustics (close-mic'd or processed)")
            scores.append(0.4)
        
        # Calculate overall confidence
        is_recording = len(scores) >= 2 and np.mean(scores) > 0.5
        confidence = np.mean(scores) if scores else 0.0
        
        return is_recording, confidence, indicators
    
    def _analyze_frequency_content(self, audio: np.ndarray) -> Dict:
        """
        Detailed frequency analysis
        """
        # Compute spectrum
        n = len(audio)
        spectrum = np.abs(fft(audio))[:n//2]
        freqs = fftfreq(n, 1/self.sample_rate)[:n//2]
        
        # Power spectrum in dB
        power_db = 20 * np.log10(spectrum + 1e-10)
        
        # Find frequency range (where energy is present)
        threshold = np.max(power_db) - 40  # 40dB below peak
        active = power_db > threshold
        
        if np.any(active):
            active_freqs = freqs[active]
            freq_range = (float(np.min(active_freqs)), float(np.max(active_freqs)))
        else:
            freq_range = (0.0, 0.0)
        
        # Dominant frequencies (peaks)
        peaks, properties = signal.find_peaks(power_db, height=threshold, distance=50)
        dominant = sorted(freqs[peaks], key=lambda f: power_db[np.argmin(np.abs(freqs - f))], reverse=True)[:5]
        
        # Bandwidth
        bandwidth = freq_range[1] - freq_range[0]
        
        # Spectral centroid
        centroid = np.sum(freqs * spectrum) / (np.sum(spectrum) + 1e-10)
        
        # Spectral rolloff (frequency below which 85% of energy is contained)
        cumsum = np.cumsum(spectrum)
        rolloff_idx = np.where(cumsum >= 0.85 * cumsum[-1])[0]
        rolloff = freqs[rolloff_idx[0]] if len(rolloff_idx) > 0 else freqs[-1]
        
        return {
            'range': freq_range,
            'dominant': [float(f) for f in dominant],
            'bandwidth': float(bandwidth),
            'centroid': float(centroid),
            'rolloff': float(rolloff),
            'spectrum': spectrum,
            'freqs': freqs,
            'power_db': power_db
        }
    
    def _fingerprint_speaker(self, audio: np.ndarray, freq_analysis: Dict) -> Dict:
        """
        Identify speaker/transducer characteristics
        """
        freqs = freq_analysis['freqs']
        power_db = freq_analysis['power_db']
        
        # Find resonance peaks (speaker cabinet/driver resonances)
        # These appear as peaks in the frequency response
        smoothed = uniform_filter1d(power_db, size=20)
        peaks, properties = signal.find_peaks(smoothed, prominence=5, distance=100)
        resonances = [float(freqs[p]) for p in peaks if 50 < freqs[p] < 15000][:5]
        
        # Estimate speaker size based on low frequency response
        low_freq_energy = np.mean(power_db[(freqs > 20) & (freqs < 200)])
        mid_freq_energy = np.mean(power_db[(freqs > 200) & (freqs < 2000)])
        
        if low_freq_energy > mid_freq_energy - 10:
            size = 'large'  # Good bass response
        elif low_freq_energy > mid_freq_energy - 20:
            size = 'medium'
        else:
            size = 'small'  # Poor bass = small speaker
        
        # Match against known signatures
        freq_range = freq_analysis['range']
        best_match = 'unknown'
        best_score = 0
        
        for speaker_type, sig in self.speaker_signatures.items():
            score = 0
            
            # Check frequency range match
            if freq_range[0] >= sig['low_cutoff'] * 0.8:
                score += 0.3
            if freq_range[1] <= sig['high_cutoff'] * 1.2:
                score += 0.3
            
            # Check resonance match
            for res in resonances:
                for sig_res in sig['resonances']:
                    if abs(res - sig_res) < sig_res * 0.2:  # Within 20%
                        score += 0.2
                        break
            
            if score > best_score:
                best_score = score
                best_match = speaker_type
        
        return {
            'resonances': resonances,
            'size': size,
            'quality': best_match,
            'match_confidence': best_score
        }
    
    def _analyze_noise(self, audio: np.ndarray) -> Dict:
        """
        Analyze background noise characteristics
        """
        # Estimate noise floor from quiet segments
        frame_size = int(0.05 * self.sample_rate)  # 50ms frames
        frame_energies = []
        
        for i in range(0, len(audio) - frame_size, frame_size):
            frame = audio[i:i+frame_size]
            frame_energies.append(np.sqrt(np.mean(frame**2)))
        
        # Noise floor is the lower percentile of frame energies
        noise_floor = np.percentile(frame_energies, 10)
        noise_floor_db = 20 * np.log10(noise_floor + 1e-10)
        
        # Signal level is the upper percentile
        signal_level = np.percentile(frame_energies, 90)
        signal_level_db = 20 * np.log10(signal_level + 1e-10)
        
        snr_db = signal_level_db - noise_floor_db
        
        # Classify noise type
        # Extract quiet portions for analysis
        quiet_mask = np.array(frame_energies) < np.percentile(frame_energies, 20)
        quiet_indices = np.where(quiet_mask)[0]
        
        if len(quiet_indices) > 0:
            quiet_samples = []
            for idx in quiet_indices[:10]:  # Take first 10 quiet frames
                start = idx * frame_size
                quiet_samples.extend(audio[start:start+frame_size])
            quiet_samples = np.array(quiet_samples)
            
            # Analyze noise spectrum
            if len(quiet_samples) > 1024:
                noise_spectrum = np.abs(fft(quiet_samples[:1024]))[:512]
                noise_freqs = fftfreq(1024, 1/self.sample_rate)[:512]
                
                # Check for specific noise patterns
                # Pink noise: -3dB/octave slope
                # White noise: flat
                # Digital noise: peaks at specific frequencies
                
                low_energy = np.mean(noise_spectrum[(noise_freqs > 100) & (noise_freqs < 500)])
                high_energy = np.mean(noise_spectrum[(noise_freqs > 2000) & (noise_freqs < 8000)])
                
                ratio = high_energy / (low_energy + 1e-10)
                
                if ratio > 0.8:
                    noise_type = 'digital'  # Flat spectrum = digital/quantization noise
                elif ratio < 0.3:
                    noise_type = 'environmental'  # More low freq = room noise
                else:
                    noise_type = 'static'  # Consistent broadband = recording
                
                # Check for RF interference (specific frequency spikes)
                peaks, _ = signal.find_peaks(noise_spectrum, height=np.mean(noise_spectrum) * 5)
                if len(peaks) > 3:
                    noise_type = 'rf_interference'
            else:
                noise_type = 'unknown'
        else:
            noise_type = 'unknown'
        
        return {
            'floor_db': float(noise_floor_db),
            'snr_db': float(snr_db),
            'type': noise_type
        }
    
    def _analyze_ultrasonic(self, audio: np.ndarray) -> Dict:
        """
        Detect ultrasonic carriers (requires high sample rate)
        """
        result = {
            'has_carrier': False,
            'freq': None,
            'modulation': None,
            'power_db': None
        }
        
        # Need high sample rate for ultrasonic
        if self.sample_rate < 96000:
            return result
        
        # High-pass filter to isolate ultrasonic
        nyq = self.sample_rate / 2
        cutoff = 18000 / nyq
        
        if cutoff >= 1.0:
            return result
            
        b, a = signal.butter(6, cutoff, btype='high')
        ultrasonic = signal.filtfilt(b, a, audio)
        
        # Compute spectrum
        n = len(ultrasonic)
        spectrum = np.abs(fft(ultrasonic))[:n//2]
        freqs = fftfreq(n, 1/self.sample_rate)[:n//2]
        
        # Look for peaks above 18kHz
        ultra_mask = freqs > 18000
        ultra_spectrum = spectrum[ultra_mask]
        ultra_freqs = freqs[ultra_mask]
        
        if len(ultra_spectrum) == 0:
            return result
        
        # Find peaks
        threshold = np.mean(ultra_spectrum) + 3 * np.std(ultra_spectrum)
        peaks, properties = signal.find_peaks(ultra_spectrum, height=threshold)
        
        if len(peaks) > 0:
            # Found ultrasonic carrier
            strongest_peak = peaks[np.argmax(ultra_spectrum[peaks])]
            carrier_freq = ultra_freqs[strongest_peak]
            carrier_power = 20 * np.log10(ultra_spectrum[strongest_peak] + 1e-10)
            
            result['has_carrier'] = True
            result['freq'] = float(carrier_freq)
            result['power_db'] = float(carrier_power)
            
            # Detect modulation type
            # Extract carrier and analyze envelope
            carrier_bw = 2000  # 2kHz bandwidth around carrier
            bp_low = (carrier_freq - carrier_bw) / nyq
            bp_high = (carrier_freq + carrier_bw) / nyq
            
            if bp_low > 0 and bp_high < 1:
                b, a = signal.butter(4, [bp_low, bp_high], btype='band')
                carrier = signal.filtfilt(b, a, audio)
                
                # Check for AM (envelope variation)
                envelope = np.abs(signal.hilbert(carrier))
                env_variation = np.std(envelope) / (np.mean(envelope) + 1e-10)
                
                # Check for FM (frequency variation)
                phase = np.unwrap(np.angle(signal.hilbert(carrier)))
                freq_variation = np.std(np.diff(phase))
                
                if env_variation > 0.3:
                    result['modulation'] = 'AM'
                elif freq_variation > 0.5:
                    result['modulation'] = 'FM'
                else:
                    result['modulation'] = 'CW'  # Continuous wave / unmodulated
        
        return result
    
    def _analyze_temporal_patterns(self, audio: np.ndarray) -> Dict:
        """
        Analyze timing patterns for automation detection
        """
        # Compute envelope
        envelope = np.abs(signal.hilbert(audio))
        
        # Smooth envelope
        smoothed = uniform_filter1d(envelope, size=int(0.01 * self.sample_rate))
        
        # Find onset times (start of audio segments)
        threshold = np.mean(smoothed) + np.std(smoothed)
        above_threshold = smoothed > threshold
        
        # Find rising edges
        onsets = np.where(np.diff(above_threshold.astype(int)) == 1)[0]
        onset_times = onsets / self.sample_rate
        
        # Analyze intervals between onsets
        if len(onset_times) >= 2:
            intervals = np.diff(onset_times)
            
            # Check for regularity (automated = consistent intervals)
            interval_std = np.std(intervals)
            interval_mean = np.mean(intervals)
            
            regularity = 1 - (interval_std / (interval_mean + 1e-10))
            
            is_automated = regularity > 0.8 and len(intervals) >= 2
            repeat_interval = float(interval_mean) if is_automated else None
        else:
            is_automated = False
            repeat_interval = None
            regularity = 0
        
        return {
            'is_automated': is_automated,
            'repeat_interval': repeat_interval,
            'regularity': float(regularity),
            'onset_count': len(onset_times)
        }
    
    def _classify_source(self, freq_analysis: Dict, speaker_info: Dict,
                         ultrasonic: Dict, noise_analysis: Dict) -> Tuple[str, float]:
        """
        Classify the injection source type
        """
        scores = defaultdict(float)
        
        # Ultrasonic transducer
        if ultrasonic['has_carrier']:
            scores['ultrasonic_transducer'] = 0.9
        
        # Phone speaker
        if speaker_info['quality'] == 'phone':
            scores['phone_speaker'] = 0.7
        elif speaker_info['size'] == 'small' and freq_analysis['range'][0] > 150:
            scores['phone_speaker'] = 0.5
        
        # Laptop speaker
        if speaker_info['quality'] == 'laptop':
            scores['laptop_speaker'] = 0.7
        
        # Bluetooth speaker
        if speaker_info['quality'] == 'bluetooth':
            scores['bluetooth_speaker'] = 0.7
        
        # PA system / large speaker
        if speaker_info['size'] == 'large' and freq_analysis['range'][0] < 80:
            scores['pa_system'] = 0.6
        
        # RF demodulation artifact
        if noise_analysis['type'] == 'rf_interference':
            scores['rf_demod'] = 0.5
        
        # Direct line injection (very clean, full bandwidth)
        if (noise_analysis['snr_db'] > 60 and 
            freq_analysis['bandwidth'] > 15000 and
            speaker_info['quality'] == 'unknown'):
            scores['direct_injection'] = 0.6
        
        if not scores:
            return 'unknown', 0.0
        
        best_source = max(scores, key=scores.get)
        return best_source, scores[best_source]
    
    def _correlate_rf(self, rf_events: List[Dict]) -> Dict:
        """
        Correlate with RF events to identify satellite source
        """
        result = {
            'correlation': False,
            'frequency': None,
            'band': None,
            'delta': None
        }
        
        if not rf_events:
            return result
        
        # Current time (would be audio timestamp in real use)
        current_time = datetime.now().timestamp()
        
        # Look for RF events within 5 seconds before audio
        for event in rf_events:
            event_time = event.get('timestamp', 0)
            if isinstance(event_time, str):
                event_time = datetime.fromisoformat(event_time).timestamp()
            
            delta = current_time - event_time
            
            if 0 < delta < 5:  # RF before audio, within 5 seconds
                result['correlation'] = True
                result['frequency'] = event.get('frequency_mhz')
                result['band'] = event.get('satellite_band')
                result['delta'] = delta * 1000  # Convert to ms
                break
        
        return result
    
    def _print_analysis(self, result: InjectionCharacteristics):
        """
        Print formatted analysis results
        """
        print("\n" + "=" * 60)
        print("ANALYSIS RESULTS")
        print("=" * 60)
        
        # Source classification
        print(f"\n📍 SOURCE IDENTIFICATION")
        print(f"   Type: {result.source_type.upper()}")
        print(f"   Confidence: {result.source_confidence:.1%}")
        
        # Recording detection
        print(f"\n🎙️ RECORDING DETECTION")
        print(f"   Is Recording: {'YES ⚠️' if result.is_recording else 'NO'}")
        print(f"   Confidence: {result.recording_confidence:.1%}")
        if result.recording_indicators:
            print(f"   Indicators:")
            for ind in result.recording_indicators:
                print(f"      • {ind}")
        
        # Frequency analysis
        print(f"\n📊 FREQUENCY ANALYSIS")
        print(f"   Range: {result.frequency_range_hz[0]:.0f} - {result.frequency_range_hz[1]:.0f} Hz")
        print(f"   Bandwidth: {result.bandwidth_hz:.0f} Hz")
        print(f"   Spectral Centroid: {result.spectral_centroid_hz:.0f} Hz")
        if result.dominant_frequencies_hz:
            print(f"   Dominant Frequencies: {', '.join(f'{f:.0f}' for f in result.dominant_frequencies_hz[:3])} Hz")
        
        # Speaker fingerprint
        print(f"\n🔊 SPEAKER/TRANSDUCER")
        print(f"   Estimated Quality: {result.frequency_response_quality}")
        print(f"   Estimated Size: {result.estimated_speaker_size}")
        if result.speaker_resonances_hz:
            print(f"   Resonances: {', '.join(f'{f:.0f}' for f in result.speaker_resonances_hz[:3])} Hz")
        
        # Noise analysis
        print(f"\n🔇 NOISE ANALYSIS")
        print(f"   Noise Floor: {result.noise_floor_db:.1f} dB")
        print(f"   SNR: {result.snr_db:.1f} dB")
        print(f"   Noise Type: {result.noise_type}")
        
        # Ultrasonic
        print(f"\n🦇 ULTRASONIC ANALYSIS")
        if result.has_ultrasonic_carrier:
            print(f"   ⚠️  CARRIER DETECTED!")
            print(f"   Frequency: {result.ultrasonic_freq_hz/1000:.1f} kHz")
            print(f"   Modulation: {result.ultrasonic_modulation}")
        else:
            print(f"   No ultrasonic carrier detected")
        
        # Temporal
        print(f"\n⏱️ TEMPORAL ANALYSIS")
        print(f"   Duration: {result.injection_duration_sec:.2f} seconds")
        print(f"   Automated: {'YES ⚠️' if result.is_automated else 'Likely manual'}")
        if result.repeat_interval_sec:
            print(f"   Repeat Interval: {result.repeat_interval_sec:.2f} seconds")
        
        # RF correlation
        print(f"\n📡 RF CORRELATION")
        if result.rf_correlation:
            print(f"   ⚠️  SATELLITE CORRELATION DETECTED!")
            print(f"   Frequency: {result.rf_frequency_mhz:.3f} MHz")
            print(f"   Band: {result.rf_satellite_band}")
            print(f"   Time Delta: {result.rf_time_delta_ms:.0f} ms")
        else:
            print(f"   No RF correlation found")
        
        print("\n" + "=" * 60)
    
    def save_report(self, filename: str = 'injection_analysis.json'):
        """
        Save analysis results to JSON file
        """
        report = {
            'analysis_time': datetime.now().isoformat(),
            'results': [asdict(r) for r in self.results]
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n✓ Report saved to: {filename}")
    
    def generate_plot(self, audio: np.ndarray, filename: str = 'injection_analysis.png'):
        """
        Generate visualization of the analysis
        """
        if not HAS_MATPLOTLIB:
            print("matplotlib not available for plotting")
            return
        
        fig, axes = plt.subplots(4, 1, figsize=(14, 12))
        
        # 1. Waveform
        time_axis = np.arange(len(audio)) / self.sample_rate
        axes[0].plot(time_axis, audio, linewidth=0.5)
        axes[0].set_title('Waveform')
        axes[0].set_xlabel('Time (s)')
        axes[0].set_ylabel('Amplitude')
        axes[0].grid(True, alpha=0.3)
        
        # 2. Spectrogram
        f, t, Sxx = signal.spectrogram(audio, fs=self.sample_rate, nperseg=1024)
        axes[1].pcolormesh(t, f, 10*np.log10(Sxx + 1e-10), shading='gouraud', cmap='viridis')
        axes[1].set_title('Spectrogram')
        axes[1].set_xlabel('Time (s)')
        axes[1].set_ylabel('Frequency (Hz)')
        axes[1].set_ylim(0, min(self.sample_rate/2, 20000))
        
        # 3. Spectrum
        n = len(audio)
        spectrum = np.abs(fft(audio))[:n//2]
        freqs = fftfreq(n, 1/self.sample_rate)[:n//2]
        axes[2].semilogx(freqs[1:], 20*np.log10(spectrum[1:] + 1e-10))
        axes[2].set_title('Frequency Spectrum')
        axes[2].set_xlabel('Frequency (Hz)')
        axes[2].set_ylabel('Magnitude (dB)')
        axes[2].grid(True, alpha=0.3)
        axes[2].set_xlim(20, self.sample_rate/2)
        
        # 4. Envelope with onset detection
        envelope = np.abs(signal.hilbert(audio))
        smoothed = uniform_filter1d(envelope, size=int(0.01 * self.sample_rate))
        axes[3].plot(time_axis, smoothed, label='Envelope')
        axes[3].axhline(y=np.mean(smoothed) + np.std(smoothed), 
                       color='r', linestyle='--', label='Threshold')
        axes[3].set_title('Envelope (for onset detection)')
        axes[3].set_xlabel('Time (s)')
        axes[3].set_ylabel('Amplitude')
        axes[3].legend()
        axes[3].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(filename, dpi=150)
        plt.close()
        
        print(f"✓ Plot saved to: {filename}")


def live_capture_and_analyze(duration: float = 10.0, 
                             device: int = None,
                             sample_rate: int = 48000,
                             use_ultramic: bool = False):
    """
    Capture live audio and analyze for injection
    """
    if not HAS_SOUNDDEVICE:
        print("sounddevice required for live capture")
        return None
    
    if use_ultramic:
        sample_rate = 384000
        print("Using Ultramic at 384kHz for ultrasonic detection")
    
    print(f"\nCapturing {duration} seconds of audio...")
    print("(Play any suspected injection audio now)")
    
    audio = sd.rec(int(duration * sample_rate),
                   samplerate=sample_rate,
                   channels=1,
                   device=device,
                   dtype='float32')
    sd.wait()
    
    print("Capture complete. Analyzing...")
    
    analyzer = InjectionSourceAnalyzer(sample_rate)
    result = analyzer.analyze_audio(audio.flatten())
    
    # Save outputs
    wavfile.write('/tmp/captured_injection.wav', sample_rate, audio)
    analyzer.save_report('/tmp/injection_analysis.json')
    analyzer.generate_plot(audio.flatten(), '/tmp/injection_analysis.png')
    
    return result


def analyze_file(filename: str, rf_log: str = None):
    """
    Analyze an existing audio file
    """
    print(f"\nLoading: {filename}")
    
    sample_rate, audio = wavfile.read(filename)
    
    # Convert to float
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483648.0
    
    # Load RF events if provided
    rf_events = None
    if rf_log and os.path.exists(rf_log):
        rf_events = []
        with open(rf_log, 'r') as f:
            for line in f:
                try:
                    rf_events.append(json.loads(line))
                except:
                    pass
        print(f"Loaded {len(rf_events)} RF events from {rf_log}")
    
    analyzer = InjectionSourceAnalyzer(sample_rate)
    result = analyzer.analyze_audio(audio, rf_events=rf_events)
    
    # Save outputs
    output_base = os.path.splitext(filename)[0]
    analyzer.save_report(f'{output_base}_analysis.json')
    analyzer.generate_plot(audio if audio.ndim == 1 else audio[:, 0], 
                          f'{output_base}_analysis.png')
    
    return result


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Audio Injection Source Analyzer')
    parser.add_argument('input', nargs='?', help='Audio file to analyze (or "live" for capture)')
    parser.add_argument('-d', '--device', type=int, help='Audio device index')
    parser.add_argument('-t', '--duration', type=float, default=10,
                        help='Capture duration in seconds (for live mode)')
    parser.add_argument('--ultramic', action='store_true',
                        help='Use Ultramic 384K for ultrasonic detection')
    parser.add_argument('--rf-log', type=str,
                        help='RF detection log for correlation (JSONL format)')
    parser.add_argument('--list-devices', action='store_true',
                        help='List audio devices and exit')
    
    args = parser.parse_args()
    
    if args.list_devices:
        if HAS_SOUNDDEVICE:
            print("\nAvailable Audio Devices:")
            print("=" * 60)
            for i, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    print(f"[{i}] {dev['name']}")
                    print(f"    Sample Rate: {dev['default_samplerate']} Hz")
        else:
            print("sounddevice not available")
        exit(0)
    
    if args.input == 'live' or args.input is None:
        # Live capture mode
        result = live_capture_and_analyze(
            duration=args.duration,
            device=args.device,
            use_ultramic=args.ultramic
        )
    else:
        # File analysis mode
        if os.path.exists(args.input):
            result = analyze_file(args.input, args.rf_log)
        else:
            print(f"File not found: {args.input}")
            exit(1)
    
    if result:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Source Type: {result.source_type}")
        print(f"Is Recording: {result.is_recording}")
        print(f"Ultrasonic Carrier: {result.has_ultrasonic_carrier}")
        print(f"RF Correlation: {result.rf_correlation}")
        print(f"Automated: {result.is_automated}")