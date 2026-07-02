#!/usr/bin/env python3
"""
EarArray Real-Time Monitoring System (Improved)
================================================

Enhanced DolphinAttack detection with better false positive filtering:
- Temporal consistency checking (attacks must persist across frames)
- Environmental baseline calibration  
- Adaptive thresholds based on recent history
- Multi-stage validation pipeline
- Expanded feature set for better discrimination

Requirements:
    pip install numpy sounddevice

Usage:
    python eararray_realtime_improved.py --simulate --calibration-time 10
"""

import numpy as np
import threading
import queue
import time
import argparse
import sys
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, List, Tuple, Dict
from collections import deque
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('EarArray')


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class AudioConfig:
    sample_rate: int = 44100
    channels: int = 2
    chunk_size: int = 4410  # 100ms chunks
    device_index: Optional[int] = None

@dataclass
class DetectionConfig:
    # Window settings
    window_size: float = 0.4
    overlap: float = 0.2
    low_freq: float = 50.0
    high_freq: float = 2000.0
    nperseg: int = 256
    noverlap: int = 128
    
    # Detection thresholds
    detection_threshold: float = 0.5
    high_confidence_threshold: float = 0.75
    alert_cooldown: float = 2.0
    
    # FALSE POSITIVE REDUCTION SETTINGS
    # Temporal consistency - require N detections in M windows
    temporal_window: int = 5          # Number of recent windows to consider
    min_detections_required: int = 3  # Must detect in at least 3 of 5 windows
    
    # Calibration
    calibration_time: float = 5.0     # Seconds to calibrate baseline
    baseline_update_rate: float = 0.01  # How fast baseline adapts (0-1)
    
    # Anomaly detection
    std_multiplier: float = 3.0       # Signal must be N std devs from baseline
    min_snr_db: float = 6.0           # Minimum signal-to-noise ratio
    
    # Directional consistency
    direction_consistency_required: float = 0.6  # 60% of detections same direction


class ThreatLevel(Enum):
    SAFE = "SAFE"
    MONITORING = "MONITORING"      # Possible activity, gathering data
    SUSPICIOUS = "SUSPICIOUS"      # Multiple indicators but not confirmed
    ATTACK_DETECTED = "ATTACK_DETECTED"


class Direction(Enum):
    LEFT = "Left"
    RIGHT = "Right"
    UNKNOWN = "Unknown"


# =============================================================================
# SIGNAL PROCESSING
# =============================================================================

class SignalProcessor:
    def __init__(self, sample_rate: int, low_freq: float, high_freq: float):
        self.sample_rate = sample_rate
        self.low_freq = low_freq
        self.high_freq = high_freq
        self._filter_coeffs = self._design_filter()
        
    def _design_filter(self) -> np.ndarray:
        """Pre-compute filter coefficients."""
        N = 101
        n = np.arange(N)
        fc_low = self.low_freq / self.sample_rate
        fc_high = self.high_freq / self.sample_rate
        
        h_low = np.sinc(2 * fc_high * (n - (N-1)/2)) * 2 * fc_high
        h_high = np.sinc(2 * fc_low * (n - (N-1)/2)) * 2 * fc_low
        h = h_low - h_high
        
        window = 0.54 - 0.46 * np.cos(2 * np.pi * n / (N-1))
        h = h * window
        h = h / np.sum(np.abs(h))
        return h
        
    def bandpass_filter(self, signal: np.ndarray) -> np.ndarray:
        if signal.ndim == 1:
            return np.convolve(signal, self._filter_coeffs, mode='same')
        return np.array([np.convolve(ch, self._filter_coeffs, mode='same') for ch in signal])
    
    def compute_band_power(self, signal: np.ndarray, nperseg: int = 256) -> float:
        nperseg = min(nperseg, len(signal))
        freqs = np.fft.rfftfreq(nperseg, 1/self.sample_rate)
        
        window = np.hanning(nperseg)
        segment = signal[:nperseg] * window
        psd = np.abs(np.fft.rfft(segment)) ** 2
        
        idx_low = np.searchsorted(freqs, self.low_freq)
        idx_high = np.searchsorted(freqs, self.high_freq)
        
        return np.sum(psd[idx_low:idx_high]) if idx_high > idx_low else 0.0
    
    def compute_psd(self, signal: np.ndarray, nperseg: int = 256) -> Tuple[np.ndarray, np.ndarray]:
        nperseg = min(nperseg, len(signal))
        freqs = np.fft.rfftfreq(nperseg, 1/self.sample_rate)
        window = np.hanning(nperseg)
        segment = signal[:nperseg] * window
        psd = np.abs(np.fft.rfft(segment)) ** 2
        return freqs, psd


# =============================================================================
# ENHANCED FEATURE EXTRACTION
# =============================================================================

class EnhancedFeatureExtractor:
    """Extract comprehensive features for attack detection."""
    
    def __init__(self, processor: SignalProcessor, nperseg: int = 256):
        self.processor = processor
        self.nperseg = nperseg
        
    def extract(self, multichannel: np.ndarray) -> dict:
        num_channels = multichannel.shape[0]
        
        band_powers = []
        spectra = []
        rms_values = []
        zcr_values = []  # Zero crossing rate
        crest_factors = []
        spectral_centroids = []
        spectral_flatness = []
        
        for ch in range(num_channels):
            signal = multichannel[ch]
            filtered = self.processor.bandpass_filter(signal)
            
            # Band power
            bp = self.processor.compute_band_power(filtered, self.nperseg)
            band_powers.append(bp)
            
            # PSD
            freqs, psd = self.processor.compute_psd(filtered, self.nperseg)
            spectra.append(psd)
            
            # RMS energy
            rms = np.sqrt(np.mean(signal ** 2))
            rms_values.append(rms)
            
            # Zero crossing rate (voice vs synthetic signals)
            zcr = np.sum(np.abs(np.diff(np.sign(signal)))) / (2 * len(signal))
            zcr_values.append(zcr)
            
            # Crest factor (peak to RMS ratio) - attacks often have different crest
            peak = np.max(np.abs(signal))
            crest = peak / rms if rms > 0 else 0
            crest_factors.append(crest)
            
            # Spectral centroid
            if np.sum(psd) > 0:
                centroid = np.sum(freqs * psd) / np.sum(psd)
            else:
                centroid = 0
            spectral_centroids.append(centroid)
            
            # Spectral flatness (tone vs noise) - attacks are more tonal
            geometric_mean = np.exp(np.mean(np.log(psd + 1e-10)))
            arithmetic_mean = np.mean(psd)
            flatness = geometric_mean / arithmetic_mean if arithmetic_mean > 0 else 0
            spectral_flatness.append(flatness)
        
        band_powers = np.array(band_powers)
        
        # Normalize band powers
        max_bp = np.max(band_powers)
        band_powers_norm = band_powers / max_bp if max_bp > 0 else band_powers
        
        # Inter-channel features (key for attack detection)
        range_bp = np.max(band_powers_norm) - np.min(band_powers_norm)
        std_bp = np.std(band_powers_norm)
        
        # Cross-channel correlation
        max_idx = np.argmax(band_powers)
        min_idx = np.argmin(band_powers)
        
        if max_idx != min_idx and len(spectra[max_idx]) > 0:
            spec1, spec2 = spectra[max_idx], spectra[min_idx]
            if np.std(spec1) > 0 and np.std(spec2) > 0:
                corr = np.corrcoef(spec1, spec2)[0, 1]
                corr = 1.0 if np.isnan(corr) else corr
            else:
                corr = 1.0
        else:
            corr = 1.0
        
        # Channel imbalance ratio (more robust than range)
        sorted_bp = np.sort(band_powers_norm)[::-1]
        if len(sorted_bp) >= 2 and sorted_bp[1] > 0:
            imbalance_ratio = sorted_bp[0] / sorted_bp[1]
        else:
            imbalance_ratio = 1.0
            
        # Cross-channel RMS difference
        rms_range = np.max(rms_values) - np.min(rms_values)
        rms_ratio = np.max(rms_values) / np.min(rms_values) if np.min(rms_values) > 0 else 1.0
        
        # Spectral consistency across channels
        centroid_std = np.std(spectral_centroids)
        flatness_std = np.std(spectral_flatness)
        
        return {
            # Primary features
            'range_bp': range_bp,
            'std_bp': std_bp,
            'correlation': corr,
            'imbalance_ratio': imbalance_ratio,
            
            # Energy features
            'rms_values': rms_values,
            'rms_range': rms_range,
            'rms_ratio': rms_ratio,
            'total_energy': np.sum(rms_values),
            
            # Temporal features
            'zcr_values': zcr_values,
            'zcr_mean': np.mean(zcr_values),
            'crest_factors': crest_factors,
            'crest_mean': np.mean(crest_factors),
            
            # Spectral features
            'spectral_centroids': spectral_centroids,
            'centroid_std': centroid_std,
            'spectral_flatness': spectral_flatness,
            'flatness_mean': np.mean(spectral_flatness),
            'flatness_std': flatness_std,
            
            # Raw data for further analysis
            'band_powers': band_powers.tolist(),
            'band_powers_norm': band_powers_norm.tolist(),
            'spectra': spectra,
            
            # Feature vector for classifier
            'feature_vector': np.array([
                range_bp,
                std_bp,
                corr,
                imbalance_ratio,
                rms_ratio,
                np.mean(spectral_flatness)
            ])
        }


# =============================================================================
# ENVIRONMENTAL BASELINE
# =============================================================================

class EnvironmentalBaseline:
    """Track baseline statistics to detect anomalies."""
    
    def __init__(self, config: DetectionConfig):
        self.config = config
        self.is_calibrated = False
        self.calibration_samples = []
        self.calibration_start = None
        
        # Baseline statistics
        self.baseline_mean = None
        self.baseline_std = None
        self.baseline_range_bp = None
        self.baseline_range_bp_std = None
        
        # Adaptive baseline (exponential moving average)
        self.ema_features = None
        self.ema_alpha = config.baseline_update_rate
        
    def start_calibration(self):
        """Start calibration period."""
        self.calibration_samples = []
        self.calibration_start = time.time()
        logger.info(f"Starting baseline calibration ({self.config.calibration_time}s)...")
        
    def add_calibration_sample(self, features: dict) -> bool:
        """Add sample during calibration. Returns True when calibration complete."""
        if self.is_calibrated:
            return True
            
        self.calibration_samples.append(features)
        
        elapsed = time.time() - self.calibration_start
        if elapsed >= self.config.calibration_time:
            self._finalize_calibration()
            return True
        return False
        
    def _finalize_calibration(self):
        """Compute baseline statistics from calibration samples."""
        if len(self.calibration_samples) < 10:
            logger.warning("Insufficient calibration samples, using defaults")
            self.baseline_range_bp = 0.3
            self.baseline_range_bp_std = 0.15
            self.is_calibrated = True
            return
            
        range_bps = [s['range_bp'] for s in self.calibration_samples]
        std_bps = [s['std_bp'] for s in self.calibration_samples]
        correlations = [s['correlation'] for s in self.calibration_samples]
        rms_ranges = [s['rms_range'] for s in self.calibration_samples]
        
        self.baseline_range_bp = np.mean(range_bps)
        self.baseline_range_bp_std = np.std(range_bps)
        self.baseline_std_bp = np.mean(std_bps)
        self.baseline_std_bp_std = np.std(std_bps)
        self.baseline_corr = np.mean(correlations)
        self.baseline_rms_range = np.mean(rms_ranges)
        self.baseline_rms_range_std = np.std(rms_ranges)
        
        # Initialize EMA
        self.ema_features = {
            'range_bp': self.baseline_range_bp,
            'std_bp': self.baseline_std_bp,
            'rms_range': self.baseline_rms_range
        }
        
        self.is_calibrated = True
        logger.info(f"Calibration complete. Baseline range_bp: {self.baseline_range_bp:.4f} "
                   f"(±{self.baseline_range_bp_std:.4f})")
        
    def update_baseline(self, features: dict):
        """Update adaptive baseline with new sample (only if not anomalous)."""
        if not self.is_calibrated or self.ema_features is None:
            return
            
        # Only update baseline if this looks like normal audio
        if self.is_anomalous(features):
            return
            
        # EMA update
        for key in self.ema_features:
            if key in features:
                self.ema_features[key] = (
                    self.ema_alpha * features[key] + 
                    (1 - self.ema_alpha) * self.ema_features[key]
                )
                
    def is_anomalous(self, features: dict) -> bool:
        """Check if features are anomalous compared to baseline."""
        if not self.is_calibrated:
            return False
            
        # Check if range_bp is significantly above baseline
        if self.baseline_range_bp_std > 0:
            z_score = (features['range_bp'] - self.baseline_range_bp) / self.baseline_range_bp_std
            if z_score > self.config.std_multiplier:
                return True
                
        # Check RMS range anomaly
        if hasattr(self, 'baseline_rms_range_std') and self.baseline_rms_range_std > 0:
            z_score = (features['rms_range'] - self.baseline_rms_range) / self.baseline_rms_range_std
            if z_score > self.config.std_multiplier:
                return True
                
        return False
        
    def get_anomaly_score(self, features: dict) -> float:
        """Get normalized anomaly score (0-1)."""
        if not self.is_calibrated or self.baseline_range_bp_std == 0:
            return 0.0
            
        z_score = (features['range_bp'] - self.baseline_range_bp) / self.baseline_range_bp_std
        # Convert z-score to 0-1 probability using sigmoid
        return 1 / (1 + np.exp(-z_score + self.config.std_multiplier))


# =============================================================================
# TEMPORAL CONSISTENCY TRACKER
# =============================================================================

class TemporalConsistencyTracker:
    """Track detections over time to filter transient false positives."""
    
    def __init__(self, config: DetectionConfig):
        self.config = config
        self.detection_history = deque(maxlen=config.temporal_window)
        self.direction_history = deque(maxlen=config.temporal_window)
        
    def add_detection(self, is_attack: bool, direction: Direction, confidence: float):
        """Add detection result to history."""
        self.detection_history.append({
            'is_attack': is_attack,
            'confidence': confidence,
            'timestamp': time.time()
        })
        if is_attack:
            self.direction_history.append(direction)
            
    def is_temporally_consistent(self) -> Tuple[bool, float]:
        """
        Check if recent detections are temporally consistent.
        Returns (is_consistent, consistency_score).
        """
        if len(self.detection_history) < self.config.temporal_window:
            return False, 0.0
            
        # Count recent detections
        recent_attacks = sum(1 for d in self.detection_history if d['is_attack'])
        detection_ratio = recent_attacks / len(self.detection_history)
        
        # Check if we meet minimum detection threshold
        is_consistent = recent_attacks >= self.config.min_detections_required
        
        return is_consistent, detection_ratio
        
    def get_dominant_direction(self) -> Tuple[Direction, float]:
        """Get the most common direction and its consistency."""
        if not self.direction_history:
            return Direction.UNKNOWN, 0.0
            
        direction_counts = {}
        for d in self.direction_history:
            direction_counts[d] = direction_counts.get(d, 0) + 1
            
        dominant = max(direction_counts, key=direction_counts.get)
        consistency = direction_counts[dominant] / len(self.direction_history)
        
        return dominant, consistency
        
    def is_direction_consistent(self) -> bool:
        """Check if attack direction is consistent (not random noise)."""
        _, consistency = self.get_dominant_direction()
        return consistency >= self.config.direction_consistency_required
        
    def clear(self):
        """Clear detection history."""
        self.detection_history.clear()
        self.direction_history.clear()


# =============================================================================
# MULTI-STAGE VALIDATOR
# =============================================================================

class MultiStageValidator:
    """Multi-stage validation to reduce false positives."""
    
    def __init__(self, config: DetectionConfig):
        self.config = config
        
    def validate(self, features: dict, raw_prediction: int, raw_confidence: float,
                 baseline: EnvironmentalBaseline, 
                 temporal: TemporalConsistencyTracker) -> Tuple[ThreatLevel, float, List[str]]:
        """
        Run multi-stage validation.
        Returns (threat_level, adjusted_confidence, rejection_reasons).
        """
        rejection_reasons = []
        confidence_adjustments = []
        
        # Stage 1: Check raw classifier output
        if raw_prediction == 0:
            return ThreatLevel.SAFE, raw_confidence, ["classifier_negative"]
            
        # Stage 2: Check minimum feature thresholds
        if features['range_bp'] < 0.3:
            rejection_reasons.append("range_bp_too_low")
            confidence_adjustments.append(-0.2)
            
        if features['imbalance_ratio'] < 1.5:
            rejection_reasons.append("imbalance_ratio_too_low")
            confidence_adjustments.append(-0.15)
            
        # Stage 3: Check against baseline (is this actually anomalous?)
        if baseline.is_calibrated:
            if not baseline.is_anomalous(features):
                rejection_reasons.append("within_baseline_range")
                confidence_adjustments.append(-0.3)
            else:
                # Boost confidence if clearly anomalous
                anomaly_score = baseline.get_anomaly_score(features)
                confidence_adjustments.append(anomaly_score * 0.2)
                
        # Stage 4: Check signal energy (filter out very quiet signals)
        if features['total_energy'] < 0.01:
            rejection_reasons.append("signal_too_quiet")
            confidence_adjustments.append(-0.25)
            
        # Stage 5: Check spectral characteristics
        # Real DolphinAttacks tend to have low spectral flatness (more tonal)
        if features['flatness_mean'] > 0.5:
            rejection_reasons.append("too_noise_like")
            confidence_adjustments.append(-0.1)
            
        # Stage 6: Check temporal consistency
        is_temporal_consistent, temporal_score = temporal.is_temporally_consistent()
        if not is_temporal_consistent:
            rejection_reasons.append("temporally_inconsistent")
            confidence_adjustments.append(-0.25)
        else:
            # Boost confidence for temporally consistent detections
            confidence_adjustments.append(temporal_score * 0.15)
            
        # Stage 7: Check direction consistency
        if is_temporal_consistent and not temporal.is_direction_consistent():
            rejection_reasons.append("direction_inconsistent")
            confidence_adjustments.append(-0.15)
            
        # Calculate adjusted confidence
        adjusted_confidence = raw_confidence + sum(confidence_adjustments)
        adjusted_confidence = np.clip(adjusted_confidence, 0.0, 1.0)
        
        # Determine threat level
        if adjusted_confidence < 0.4:
            threat_level = ThreatLevel.SAFE
        elif adjusted_confidence < 0.6:
            threat_level = ThreatLevel.MONITORING
        elif adjusted_confidence < self.config.high_confidence_threshold:
            threat_level = ThreatLevel.SUSPICIOUS
        else:
            # Final gate: require temporal consistency for confirmed attacks
            if is_temporal_consistent:
                threat_level = ThreatLevel.ATTACK_DETECTED
            else:
                threat_level = ThreatLevel.SUSPICIOUS
                
        return threat_level, adjusted_confidence, rejection_reasons


# =============================================================================
# ENHANCED CLASSIFIER
# =============================================================================

class EnhancedClassifier:
    """Improved classifier with multiple feature considerations."""
    
    def __init__(self):
        # Weights for extended feature vector
        self.weights = np.array([
            2.0,    # range_bp
            2.5,    # std_bp  
            -1.2,   # correlation (negative = attack)
            1.5,    # imbalance_ratio
            0.8,    # rms_ratio
            -0.5    # flatness_mean (lower = more tonal = attack)
        ])
        self.bias = -1.2  # More conservative bias
        
    def predict(self, features: np.ndarray) -> Tuple[int, float]:
        """Predict attack probability."""
        decision = np.dot(features, self.weights) + self.bias
        confidence = 1 / (1 + np.exp(-decision))
        prediction = 1 if confidence > 0.5 else 0
        return prediction, confidence


# =============================================================================
# LOCALIZER
# =============================================================================

class Localizer:
    def __init__(self, num_channels: int):
        self.num_channels = num_channels
        
    def localize(self, band_powers: List[float]) -> Direction:
        if len(band_powers) < 2:
            return Direction.UNKNOWN
        max_idx = np.argmax(band_powers)
        return Direction.LEFT if max_idx == 0 else Direction.RIGHT


# =============================================================================
# ALERT SYSTEM
# =============================================================================

class AlertManager:
    def __init__(self, cooldown: float = 2.0):
        self.cooldown = cooldown
        self.last_alert_time = 0
        self.callbacks: List[Callable] = []
        self.history = deque(maxlen=100)
        self.alert_count = 0
        
    def register_callback(self, callback: Callable):
        self.callbacks.append(callback)
        
    def trigger(self, threat_level: ThreatLevel, direction: Direction,
                confidence: float, features: dict, 
                validation_info: dict = None) -> bool:
        current_time = time.time()
        
        if current_time - self.last_alert_time < self.cooldown:
            return False
            
        self.last_alert_time = current_time
        self.alert_count += 1
        
        alert_data = {
            'id': self.alert_count,
            'timestamp': datetime.now().isoformat(),
            'threat_level': threat_level.value,
            'direction': direction.value,
            'confidence': confidence,
            'features': {
                'range_bp': features['range_bp'],
                'std_bp': features['std_bp'],
                'correlation': features['correlation'],
                'imbalance_ratio': features.get('imbalance_ratio', 0),
                'rms_ratio': features.get('rms_ratio', 0),
                'flatness_mean': features.get('flatness_mean', 0)
            },
            'validation': validation_info or {}
        }
        
        self.history.append(alert_data)
        
        for callback in self.callbacks:
            try:
                callback(alert_data)
            except Exception as e:
                logger.error(f"Callback error: {e}")
                
        return True


# =============================================================================
# AUDIO BACKENDS
# =============================================================================

class AudioBackend:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.is_running = False
        self.audio_queue = queue.Queue(maxsize=100)
        
    def start(self):
        raise NotImplementedError
        
    def stop(self):
        raise NotImplementedError
        
    def get_audio(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None


class SoundDeviceBackend(AudioBackend):
    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self.stream = None
        
    def start(self):
        try:
            import sounddevice as sd
        except ImportError:
            raise ImportError("sounddevice not installed. Run: pip install sounddevice")
        
        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
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
            callback=audio_callback
        )
        
        self.stream.start()
        self.is_running = True
        logger.info("Audio capture started (sounddevice)")
        
    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.is_running = False
        
    @staticmethod
    def list_devices():
        try:
            import sounddevice as sd
            print("\n" + "=" * 60)
            print("Available Audio Devices:")
            print("=" * 60)
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    print(f"  [{i}] {dev['name']}")
                    print(f"      Channels: {dev['max_input_channels']}, "
                          f"Sample Rate: {dev['default_samplerate']}")
            print("=" * 60 + "\n")
        except ImportError:
            print("sounddevice not installed. Run: pip install sounddevice")


class SimulationBackend(AudioBackend):
    """Simulated audio with configurable attack patterns."""
    
    def __init__(self, config: AudioConfig, attack_probability: float = 0.08,
                 burst_mode: bool = True):
        super().__init__(config)
        self.attack_probability = attack_probability
        self.burst_mode = burst_mode  # Attacks come in bursts (more realistic)
        self.sim_thread = None
        self.in_attack_burst = False
        self.burst_remaining = 0
        
    def start(self):
        self.is_running = True
        self.sim_thread = threading.Thread(target=self._simulation_loop)
        self.sim_thread.start()
        logger.info("Simulation mode started")
        
    def _simulation_loop(self):
        while self.is_running:
            # Determine if we should generate attack
            generate_attack = False
            
            if self.burst_mode:
                if self.in_attack_burst and self.burst_remaining > 0:
                    generate_attack = True
                    self.burst_remaining -= 1
                    if self.burst_remaining == 0:
                        self.in_attack_burst = False
                elif np.random.random() < self.attack_probability:
                    self.in_attack_burst = True
                    self.burst_remaining = np.random.randint(3, 8)  # Burst of 3-8 frames
                    generate_attack = True
            else:
                generate_attack = np.random.random() < self.attack_probability
            
            if generate_attack:
                audio = self._generate_attack()
            else:
                audio = self._generate_normal()
                
            try:
                self.audio_queue.put_nowait(audio)
            except queue.Full:
                pass
                
            time.sleep(self.config.chunk_size / self.config.sample_rate)
            
    def _generate_normal(self) -> np.ndarray:
        """Generate normal ambient/voice-like signal."""
        t = np.linspace(0, self.config.chunk_size / self.config.sample_rate, 
                       self.config.chunk_size)
        
        # Voice-like harmonics
        signal = np.zeros(self.config.chunk_size)
        f0 = np.random.uniform(100, 200)  # Fundamental frequency
        for h in range(1, 6):
            signal += (1/h) * np.sin(2 * np.pi * f0 * h * t + np.random.uniform(0, 2*np.pi))
        
        signal *= 0.1
        
        # UNIFORM across channels (key characteristic of normal audio)
        multichannel = np.zeros((self.config.channels, self.config.chunk_size))
        for ch in range(self.config.channels):
            variation = 1.0 + np.random.uniform(-0.05, 0.05)  # Small variation
            multichannel[ch] = signal * variation
            
        multichannel += np.random.randn(*multichannel.shape) * 0.01
        return multichannel
        
    def _generate_attack(self) -> np.ndarray:
        """Generate DolphinAttack-like signal with directional characteristics."""
        t = np.linspace(0, self.config.chunk_size / self.config.sample_rate,
                       self.config.chunk_size)
        
        # More tonal signal (lower spectral flatness)
        signal = np.zeros(self.config.chunk_size)
        f0 = np.random.uniform(150, 250)
        for h in range(1, 4):  # Fewer harmonics = more tonal
            signal += (1/h**1.5) * np.sin(2 * np.pi * f0 * h * t)
        
        signal *= 0.15  # Slightly louder
        
        # NON-UNIFORM across channels (key attack characteristic)
        multichannel = np.zeros((self.config.channels, self.config.chunk_size))
        attack_dir = np.random.randint(0, self.config.channels)
        
        for ch in range(self.config.channels):
            if ch == attack_dir:
                multichannel[ch] = signal * 1.0
            else:
                attenuation = np.random.uniform(0.2, 0.5)  # Significant difference
                multichannel[ch] = signal * attenuation
            
        multichannel += np.random.randn(*multichannel.shape) * 0.008
        return multichannel
        
    def stop(self):
        self.is_running = False
        if self.sim_thread:
            self.sim_thread.join()


# =============================================================================
# MAIN DETECTOR
# =============================================================================

class ImprovedRealTimeDetector:
    """Real-time DolphinAttack detection with false positive reduction."""
    
    def __init__(self, audio_config: AudioConfig, detection_config: DetectionConfig,
                 backend: str = 'sounddevice'):
        self.audio_config = audio_config
        self.detection_config = detection_config
        
        # Initialize components
        self.processor = SignalProcessor(
            audio_config.sample_rate,
            detection_config.low_freq,
            detection_config.high_freq
        )
        self.extractor = EnhancedFeatureExtractor(self.processor, detection_config.nperseg)
        self.classifier = EnhancedClassifier()
        self.localizer = Localizer(audio_config.channels)
        self.alert_manager = AlertManager(detection_config.alert_cooldown)
        
        # FALSE POSITIVE REDUCTION COMPONENTS
        self.baseline = EnvironmentalBaseline(detection_config)
        self.temporal_tracker = TemporalConsistencyTracker(detection_config)
        self.validator = MultiStageValidator(detection_config)
        
        # Audio backend
        self.backend_type = backend
        self.audio_backend = None
        
        # Processing
        self.is_running = False
        self.process_thread = None
        
        # Statistics
        self.stats = {
            'chunks_processed': 0,
            'raw_detections': 0,
            'confirmed_attacks': 0,
            'filtered_false_positives': 0,
            'start_time': None
        }
        
    def _create_backend(self) -> AudioBackend:
        if self.backend_type == 'simulate':
            return SimulationBackend(self.audio_config)
        else:
            return SoundDeviceBackend(self.audio_config)
            
    def start(self):
        self.audio_backend = self._create_backend()
        self.audio_backend.start()
        
        self.is_running = True
        self.stats['start_time'] = datetime.now().isoformat()
        
        # Start calibration
        self.baseline.start_calibration()
        
        self.process_thread = threading.Thread(target=self._process_loop)
        self.process_thread.start()
        
        logger.info("Real-time detection started")
        
    def stop(self):
        self.is_running = False
        if self.process_thread:
            self.process_thread.join()
        if self.audio_backend:
            self.audio_backend.stop()
        logger.info("Real-time detection stopped")
        
    def _process_loop(self):
        samples_needed = int(self.detection_config.window_size * 
                           self.audio_config.sample_rate)
        
        buffer = np.zeros((self.audio_config.channels, 0))
        
        while self.is_running:
            audio = self.audio_backend.get_audio(timeout=0.5)
            
            if audio is None:
                continue
                
            buffer = np.concatenate([buffer, audio], axis=1)
            
            while buffer.shape[1] >= samples_needed:
                window = buffer[:, :samples_needed]
                step = int(self.detection_config.overlap * self.audio_config.sample_rate)
                buffer = buffer[:, step:]
                self._process_window(window)
                
    def _process_window(self, audio: np.ndarray):
        self.stats['chunks_processed'] += 1
        
        # Extract features
        features = self.extractor.extract(audio)
        
        # Handle calibration
        if not self.baseline.is_calibrated:
            if self.baseline.add_calibration_sample(features):
                logger.info("Calibration complete, starting detection")
            return
            
        # Raw classification
        raw_prediction, raw_confidence = self.classifier.predict(features['feature_vector'])
        
        # Localize
        direction = self.localizer.localize(features['band_powers'])
        
        # Track for temporal consistency
        self.temporal_tracker.add_detection(
            raw_prediction == 1, 
            direction, 
            raw_confidence
        )
        
        if raw_prediction == 1:
            self.stats['raw_detections'] += 1
        
        # MULTI-STAGE VALIDATION
        threat_level, adjusted_confidence, rejection_reasons = self.validator.validate(
            features,
            raw_prediction,
            raw_confidence,
            self.baseline,
            self.temporal_tracker
        )
        
        # Update baseline with normal samples
        if threat_level == ThreatLevel.SAFE:
            self.baseline.update_baseline(features)
            
        # Count filtered false positives
        if raw_prediction == 1 and threat_level == ThreatLevel.SAFE:
            self.stats['filtered_false_positives'] += 1
            
        # Get consistent direction for confirmed attacks
        if threat_level in [ThreatLevel.SUSPICIOUS, ThreatLevel.ATTACK_DETECTED]:
            direction, dir_consistency = self.temporal_tracker.get_dominant_direction()
            
        # Trigger alerts
        if threat_level == ThreatLevel.ATTACK_DETECTED:
            self.stats['confirmed_attacks'] += 1
            self.alert_manager.trigger(
                threat_level, direction, adjusted_confidence, features,
                {'rejection_reasons': rejection_reasons, 
                 'raw_confidence': raw_confidence}
            )
        elif threat_level == ThreatLevel.SUSPICIOUS:
            self.alert_manager.trigger(
                threat_level, direction, adjusted_confidence, features,
                {'rejection_reasons': rejection_reasons}
            )
            
    def register_alert_callback(self, callback: Callable):
        self.alert_manager.register_callback(callback)
        
    def get_stats(self) -> dict:
        return self.stats.copy()


# =============================================================================
# TERMINAL UI
# =============================================================================

class ImprovedTerminalUI:
    def __init__(self, detector: ImprovedRealTimeDetector):
        self.detector = detector
        self.running = False
        detector.register_alert_callback(self._on_alert)
        
    def _on_alert(self, alert_data: dict):
        threat = alert_data['threat_level']
        
        if threat == ThreatLevel.ATTACK_DETECTED.value:
            self._print_attack_alert(alert_data)
        elif threat == ThreatLevel.SUSPICIOUS.value:
            self._print_suspicious_alert(alert_data)
            
    def _print_attack_alert(self, alert_data: dict):
        print("\n" + "!" * 70)
        print("!!! 🚨 CONFIRMED DOLPHINATTACK 🚨 !!!")
        print("!" * 70)
        print(f"    Time:       {alert_data['timestamp']}")
        print(f"    Direction:  {alert_data['direction']}")
        print(f"    Confidence: {alert_data['confidence']:.1%}")
        print(f"    Features:")
        print(f"      - Range BP:   {alert_data['features']['range_bp']:.4f}")
        print(f"      - Std BP:     {alert_data['features']['std_bp']:.4f}")
        print(f"      - Corr:       {alert_data['features']['correlation']:.4f}")
        print(f"      - Imbalance:  {alert_data['features']['imbalance_ratio']:.4f}")
        if alert_data.get('validation'):
            raw_conf = alert_data['validation'].get('raw_confidence', 0)
            print(f"    Validation:")
            print(f"      - Raw conf:   {raw_conf:.1%}")
        print("!" * 70 + "\n")
        print('\a', end='', flush=True)
        
    def _print_suspicious_alert(self, alert_data: dict):
        reasons = alert_data.get('validation', {}).get('rejection_reasons', [])
        reason_str = f" [{', '.join(reasons)}]" if reasons else ""
        print(f"\n⚠️  Suspicious: Dir={alert_data['direction']}, "
              f"Conf={alert_data['confidence']:.1%}{reason_str}")
              
    def run(self):
        self.running = True
        
        print("\n" + "=" * 70)
        print("   EARARRAY IMPROVED DOLPHINATTACK DETECTION")
        print("   (with false positive reduction)")
        print("=" * 70)
        print("\n  Features:")
        print("    ✓ Environmental baseline calibration")
        print("    ✓ Temporal consistency checking")
        print("    ✓ Multi-stage validation")
        print("    ✓ Direction consistency verification")
        print("\n  Press Ctrl+C to stop monitoring\n")
        print("-" * 70)
        
        try:
            self.detector.start()
            
            while self.running:
                time.sleep(5)
                stats = self.detector.get_stats()
                fp_rate = (stats['filtered_false_positives'] / max(1, stats['raw_detections'])) * 100
                print(f"  [STATUS] Chunks: {stats['chunks_processed']:,}, "
                      f"Raw: {stats['raw_detections']}, "
                      f"Confirmed: {stats['confirmed_attacks']}, "
                      f"Filtered: {stats['filtered_false_positives']} ({fp_rate:.0f}%)")
                      
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            self.detector.stop()
            self._print_summary()
            
    def _print_summary(self):
        stats = self.detector.get_stats()
        
        print("\n" + "=" * 70)
        print("   SESSION SUMMARY")
        print("=" * 70)
        print(f"  Started:              {stats['start_time']}")
        print(f"  Chunks processed:     {stats['chunks_processed']:,}")
        print(f"  Raw detections:       {stats['raw_detections']}")
        print(f"  Confirmed attacks:    {stats['confirmed_attacks']}")
        print(f"  Filtered FPs:         {stats['filtered_false_positives']}")
        if stats['raw_detections'] > 0:
            reduction = (stats['filtered_false_positives'] / stats['raw_detections']) * 100
            print(f"  FP reduction rate:    {reduction:.1f}%")
        print("=" * 70 + "\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='EarArray Improved DolphinAttack Detection',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--device', type=int, default=None)
    parser.add_argument('--channels', type=int, default=2)
    parser.add_argument('--sample-rate', type=int, default=44100)
    parser.add_argument('--simulate', action='store_true')
    parser.add_argument('--calibration-time', type=float, default=5.0,
                       help='Baseline calibration duration (seconds)')
    parser.add_argument('--temporal-window', type=int, default=5,
                       help='Number of windows for temporal consistency')
    parser.add_argument('--min-detections', type=int, default=3,
                       help='Minimum detections required in temporal window')
    parser.add_argument('--cooldown', type=float, default=2.0)
    
    args = parser.parse_args()
    
    if args.list_devices:
        SoundDeviceBackend.list_devices()
        return
        
    audio_config = AudioConfig(
        sample_rate=args.sample_rate,
        channels=args.channels,
        device_index=args.device
    )
    
    detection_config = DetectionConfig(
        alert_cooldown=args.cooldown,
        calibration_time=args.calibration_time,
        temporal_window=args.temporal_window,
        min_detections_required=args.min_detections
    )
    
    backend = 'simulate' if args.simulate else 'sounddevice'
    
    detector = ImprovedRealTimeDetector(audio_config, detection_config, backend)
    ui = ImprovedTerminalUI(detector)
    ui.run()


if __name__ == '__main__':
    main()