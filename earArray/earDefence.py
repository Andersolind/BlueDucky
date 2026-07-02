#!/usr/bin/env python3
"""
EarArray Real-Time Monitoring System
=====================================

Real-time DolphinAttack detection using live microphone input.
Supports multiple audio backends and provides visual/audio alerts.

Requirements:
    pip install numpy sounddevice

Optional (for enhanced features):
    pip install pyaudio          # Alternative audio backend
    pip install playsound        # For audio alerts
    pip install rich             # For better terminal UI

Usage:
    python eararray_realtime.py                    # Use default microphone
    python eararray_realtime.py --list-devices    # List available audio devices
    python eararray_realtime.py --device 2        # Use specific device
    python eararray_realtime.py --channels 4      # Specify number of channels
    python eararray_realtime.py --simulate        # Run in simulation mode (no mic needed)
"""

import numpy as np
import threading
import queue
import time
import argparse
import sys
import os
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, List, Tuple
from collections import deque
import json
import logging

# Configure logging
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
    """Audio capture configuration."""
    sample_rate: int = 44100
    channels: int = 2                # Most laptops have stereo mics
    chunk_size: int = 4410           # 100ms chunks
    device_index: Optional[int] = None
    
@dataclass 
class DetectionConfig:
    """Detection algorithm configuration."""
    window_size: float = 0.4         # seconds
    overlap: float = 0.2             # seconds
    low_freq: float = 50.0           # Hz
    high_freq: float = 2000.0        # Hz
    detection_threshold: float = 0.5
    alert_cooldown: float = 2.0      # seconds
    nperseg: int = 256
    noverlap: int = 128


class ThreatLevel(Enum):
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"  
    ATTACK_DETECTED = "ATTACK_DETECTED"


class Direction(Enum):
    NORTH = "North"
    SOUTH = "South"
    EAST = "East"
    WEST = "West"
    LEFT = "Left"
    RIGHT = "Right"
    UNKNOWN = "Unknown"


# =============================================================================
# SIGNAL PROCESSING
# =============================================================================

class SignalProcessor:
    """Audio signal processing utilities."""
    
    def __init__(self, sample_rate: int, low_freq: float, high_freq: float):
        self.sample_rate = sample_rate
        self.low_freq = low_freq
        self.high_freq = high_freq
        
    def bandpass_filter(self, signal: np.ndarray) -> np.ndarray:
        """Apply FIR bandpass filter."""
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
        
        if signal.ndim == 1:
            return np.convolve(signal, h, mode='same')
        return np.array([np.convolve(ch, h, mode='same') for ch in signal])
    
    def compute_band_power(self, signal: np.ndarray, nperseg: int = 256) -> float:
        """Compute power in frequency band using Welch's method."""
        nperseg = min(nperseg, len(signal))
        
        freqs = np.fft.rfftfreq(nperseg, 1/self.sample_rate)
        
        window = np.hanning(nperseg)
        segment = signal[:nperseg] * window
        fft_result = np.fft.rfft(segment)
        psd = np.abs(fft_result) ** 2
        
        idx_low = np.searchsorted(freqs, self.low_freq)
        idx_high = np.searchsorted(freqs, self.high_freq)
        
        if idx_high > idx_low:
            return np.sum(psd[idx_low:idx_high])
        return 0.0
    
    def compute_psd(self, signal: np.ndarray, nperseg: int = 256) -> Tuple[np.ndarray, np.ndarray]:
        """Compute Power Spectral Density."""
        nperseg = min(nperseg, len(signal))
        freqs = np.fft.rfftfreq(nperseg, 1/self.sample_rate)
        
        window = np.hanning(nperseg)
        segment = signal[:nperseg] * window
        psd = np.abs(np.fft.rfft(segment)) ** 2
        
        return freqs, psd


# =============================================================================
# FEATURE EXTRACTION & CLASSIFICATION
# =============================================================================

class FeatureExtractor:
    """Extract features for attack detection."""
    
    def __init__(self, processor: SignalProcessor, nperseg: int = 256):
        self.processor = processor
        self.nperseg = nperseg
        
    def extract(self, multichannel: np.ndarray) -> dict:
        """Extract detection features from multichannel audio."""
        num_channels = multichannel.shape[0]
        
        band_powers = []
        spectra = []
        
        for ch in range(num_channels):
            filtered = self.processor.bandpass_filter(multichannel[ch])
            bp = self.processor.compute_band_power(filtered, self.nperseg)
            band_powers.append(bp)
            
            _, psd = self.processor.compute_psd(filtered, self.nperseg)
            spectra.append(psd)
        
        band_powers = np.array(band_powers)
        
        # Normalize
        max_bp = np.max(band_powers)
        if max_bp > 0:
            band_powers_norm = band_powers / max_bp
        else:
            band_powers_norm = band_powers
        
        # Features
        range_bp = np.max(band_powers_norm) - np.min(band_powers_norm)
        std_bp = np.std(band_powers_norm)
        
        # Correlation
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
        
        return {
            'range_bp': range_bp,
            'std_bp': std_bp,
            'correlation': corr,
            'band_powers': band_powers.tolist(),
            'feature_vector': np.array([range_bp, std_bp, corr])
        }


class Classifier:
    """SVM-based attack classifier."""
    
    def __init__(self):
        # Pre-trained weights
        self.weights = np.array([2.5, 3.0, -1.5])
        self.bias = -0.8
        
    def predict(self, features: np.ndarray) -> Tuple[int, float]:
        """Predict attack probability."""
        decision = np.dot(features, self.weights) + self.bias
        confidence = 1 / (1 + np.exp(-decision))
        prediction = 1 if confidence > 0.5 else 0
        return prediction, confidence


class Localizer:
    """Determine attack direction."""
    
    def __init__(self, num_channels: int):
        self.num_channels = num_channels
        
    def localize(self, band_powers: List[float]) -> Direction:
        """Determine direction based on power distribution."""
        if len(band_powers) < 2:
            return Direction.UNKNOWN
            
        max_idx = np.argmax(band_powers)
        
        if self.num_channels == 2:
            # Stereo: Left/Right
            return Direction.LEFT if max_idx == 0 else Direction.RIGHT
        else:
            # Multi-channel: Cardinal directions
            angle = max_idx * (360 / self.num_channels)
            if 315 <= angle or angle < 45:
                return Direction.NORTH
            elif 45 <= angle < 135:
                return Direction.EAST
            elif 135 <= angle < 225:
                return Direction.SOUTH
            else:
                return Direction.WEST


# =============================================================================
# ALERT SYSTEM
# =============================================================================

class AlertManager:
    """Manages detection alerts."""
    
    def __init__(self, cooldown: float = 2.0):
        self.cooldown = cooldown
        self.last_alert_time = 0
        self.callbacks: List[Callable] = []
        self.history = deque(maxlen=100)
        self.alert_count = 0
        
    def register_callback(self, callback: Callable):
        """Register alert callback."""
        self.callbacks.append(callback)
        
    def trigger(self, threat_level: ThreatLevel, direction: Direction,
                confidence: float, features: dict) -> bool:
        """Trigger alert if cooldown elapsed."""
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
                'correlation': features['correlation']
            }
        }
        
        self.history.append(alert_data)
        
        # Trigger callbacks
        for callback in self.callbacks:
            try:
                callback(alert_data)
            except Exception as e:
                logger.error(f"Callback error: {e}")
                
        return True


# =============================================================================
# AUDIO CAPTURE BACKENDS
# =============================================================================

class AudioBackend:
    """Base class for audio backends."""
    
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
    """Audio capture using sounddevice library."""
    
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
            # Convert to (channels, samples) format
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
        logger.info(f"Audio capture started (sounddevice)")
        
    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.is_running = False
        logger.info("Audio capture stopped")
        
    @staticmethod
    def list_devices():
        """List available audio devices."""
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


class PyAudioBackend(AudioBackend):
    """Audio capture using PyAudio library."""
    
    def __init__(self, config: AudioConfig):
        super().__init__(config)
        self.pyaudio = None
        self.stream = None
        self.capture_thread = None
        
    def start(self):
        try:
            import pyaudio
        except ImportError:
            raise ImportError("pyaudio not installed. Run: pip install pyaudio")
        
        self.pyaudio = pyaudio.PyAudio()
        
        self.stream = self.pyaudio.open(
            format=pyaudio.paFloat32,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            input_device_index=self.config.device_index,
            frames_per_buffer=self.config.chunk_size
        )
        
        self.is_running = True
        self.capture_thread = threading.Thread(target=self._capture_loop)
        self.capture_thread.start()
        logger.info("Audio capture started (PyAudio)")
        
    def _capture_loop(self):
        import pyaudio
        while self.is_running:
            try:
                data = self.stream.read(self.config.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                audio = audio.reshape(-1, self.config.channels).T
                self.audio_queue.put_nowait(audio)
            except Exception as e:
                if self.is_running:
                    logger.error(f"Capture error: {e}")
                    
    def stop(self):
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.pyaudio:
            self.pyaudio.terminate()
        logger.info("Audio capture stopped")


class SimulationBackend(AudioBackend):
    """Simulated audio for testing without microphone."""
    
    def __init__(self, config: AudioConfig, attack_probability: float = 0.1):
        super().__init__(config)
        self.attack_probability = attack_probability
        self.sim_thread = None
        
    def start(self):
        self.is_running = True
        self.sim_thread = threading.Thread(target=self._simulation_loop)
        self.sim_thread.start()
        logger.info("Simulation mode started")
        
    def _simulation_loop(self):
        while self.is_running:
            # Generate simulated audio
            if np.random.random() < self.attack_probability:
                audio = self._generate_attack()
            else:
                audio = self._generate_normal()
                
            try:
                self.audio_queue.put_nowait(audio)
            except queue.Full:
                pass
                
            time.sleep(self.config.chunk_size / self.config.sample_rate)
            
    def _generate_normal(self) -> np.ndarray:
        """Generate normal voice-like signal."""
        t = np.linspace(0, self.config.chunk_size / self.config.sample_rate, 
                       self.config.chunk_size)
        
        signal = np.zeros(self.config.chunk_size)
        for h in range(1, 6):
            signal += (1/h) * np.sin(2 * np.pi * 150 * h * t)
        
        signal *= 0.1
        
        # Uniform across channels (normal voice characteristic)
        multichannel = np.zeros((self.config.channels, self.config.chunk_size))
        for ch in range(self.config.channels):
            variation = 1.0 + np.random.uniform(-0.1, 0.1)
            multichannel[ch] = signal * variation
            
        multichannel += np.random.randn(*multichannel.shape) * 0.01
        return multichannel
        
    def _generate_attack(self) -> np.ndarray:
        """Generate DolphinAttack-like signal."""
        t = np.linspace(0, self.config.chunk_size / self.config.sample_rate,
                       self.config.chunk_size)
        
        signal = np.zeros(self.config.chunk_size)
        for h in range(1, 6):
            signal += (1/h) * np.sin(2 * np.pi * 150 * h * t)
        
        signal *= 0.1
        
        # Non-uniform across channels (attack characteristic)
        multichannel = np.zeros((self.config.channels, self.config.chunk_size))
        attack_dir = np.random.randint(0, self.config.channels)
        
        for ch in range(self.config.channels):
            angle_diff = abs(ch - attack_dir)
            attenuation = np.exp(-angle_diff * 1.5)
            multichannel[ch] = signal * attenuation
            
        multichannel += np.random.randn(*multichannel.shape) * 0.01
        return multichannel
        
    def stop(self):
        self.is_running = False
        if self.sim_thread:
            self.sim_thread.join()
        logger.info("Simulation stopped")


# =============================================================================
# MAIN DETECTOR
# =============================================================================

class RealTimeDetector:
    """Real-time DolphinAttack detection system."""
    
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
        self.extractor = FeatureExtractor(self.processor, detection_config.nperseg)
        self.classifier = Classifier()
        self.localizer = Localizer(audio_config.channels)
        self.alert_manager = AlertManager(detection_config.alert_cooldown)
        
        # Audio backend
        self.backend_type = backend
        self.audio_backend = None
        
        # Processing
        self.is_running = False
        self.process_thread = None
        self.audio_buffer = deque(maxlen=int(audio_config.sample_rate * 2))
        
        # Statistics
        self.stats = {
            'chunks_processed': 0,
            'attacks_detected': 0,
            'start_time': None
        }
        
    def _create_backend(self) -> AudioBackend:
        """Create appropriate audio backend."""
        if self.backend_type == 'simulate':
            return SimulationBackend(self.audio_config)
        elif self.backend_type == 'pyaudio':
            return PyAudioBackend(self.audio_config)
        else:
            return SoundDeviceBackend(self.audio_config)
            
    def start(self):
        """Start real-time monitoring."""
        self.audio_backend = self._create_backend()
        self.audio_backend.start()
        
        self.is_running = True
        self.stats['start_time'] = datetime.now().isoformat()
        
        self.process_thread = threading.Thread(target=self._process_loop)
        self.process_thread.start()
        
        logger.info("Real-time detection started")
        
    def stop(self):
        """Stop monitoring."""
        self.is_running = False
        
        if self.process_thread:
            self.process_thread.join()
            
        if self.audio_backend:
            self.audio_backend.stop()
            
        logger.info("Real-time detection stopped")
        
    def _process_loop(self):
        """Main processing loop."""
        samples_needed = int(self.detection_config.window_size * 
                           self.audio_config.sample_rate)
        
        buffer = np.zeros((self.audio_config.channels, 0))
        
        while self.is_running:
            # Get audio chunk
            audio = self.audio_backend.get_audio(timeout=0.5)
            
            if audio is None:
                continue
                
            # Append to buffer
            buffer = np.concatenate([buffer, audio], axis=1)
            
            # Process when we have enough samples
            while buffer.shape[1] >= samples_needed:
                # Extract window
                window = buffer[:, :samples_needed]
                
                # Slide buffer
                step = int(self.detection_config.overlap * self.audio_config.sample_rate)
                buffer = buffer[:, step:]
                
                # Process window
                self._process_window(window)
                
    def _process_window(self, audio: np.ndarray):
        """Process a single audio window."""
        self.stats['chunks_processed'] += 1
        
        # Extract features
        features = self.extractor.extract(audio)
        
        # Classify
        prediction, confidence = self.classifier.predict(features['feature_vector'])
        
        # Determine threat level
        if prediction == 1 and confidence > 0.7:
            threat_level = ThreatLevel.ATTACK_DETECTED
            self.stats['attacks_detected'] += 1
        elif prediction == 1 or confidence > 0.4:
            threat_level = ThreatLevel.SUSPICIOUS
        else:
            threat_level = ThreatLevel.SAFE
            
        # Localize if attack
        direction = Direction.UNKNOWN
        if prediction == 1:
            direction = self.localizer.localize(features['band_powers'])
            
        # Trigger alert
        if threat_level != ThreatLevel.SAFE:
            self.alert_manager.trigger(threat_level, direction, confidence, features)
            
    def register_alert_callback(self, callback: Callable):
        """Register callback for alerts."""
        self.alert_manager.register_callback(callback)
        
    def get_stats(self) -> dict:
        """Get current statistics."""
        return self.stats.copy()


# =============================================================================
# TERMINAL UI
# =============================================================================

class TerminalUI:
    """Terminal-based user interface."""
    
    def __init__(self, detector: RealTimeDetector):
        self.detector = detector
        self.running = False
        
        # Register alert callback
        detector.register_alert_callback(self._on_alert)
        
    def _on_alert(self, alert_data: dict):
        """Handle alert."""
        threat = alert_data['threat_level']
        
        if threat == ThreatLevel.ATTACK_DETECTED.value:
            self._print_attack_alert(alert_data)
        else:
            self._print_suspicious_alert(alert_data)
            
    def _print_attack_alert(self, alert_data: dict):
        """Print attack alert."""
        print("\n" + "!" * 70)
        print("!!! 🚨 DOLPHINATTACK DETECTED 🚨 !!!")
        print("!" * 70)
        print(f"    Time:       {alert_data['timestamp']}")
        print(f"    Direction:  {alert_data['direction']}")
        print(f"    Confidence: {alert_data['confidence']:.1%}")
        print(f"    Features:")
        print(f"      - Range BP: {alert_data['features']['range_bp']:.4f}")
        print(f"      - Std BP:   {alert_data['features']['std_bp']:.4f}")
        print(f"      - Corr:     {alert_data['features']['correlation']:.4f}")
        print("!" * 70 + "\n")
        
        # Try to play alert sound
        self._play_alert_sound()
        
    def _print_suspicious_alert(self, alert_data: dict):
        """Print suspicious activity alert."""
        print(f"\n⚠️  Suspicious activity - Direction: {alert_data['direction']}, "
              f"Confidence: {alert_data['confidence']:.1%}")
              
    def _play_alert_sound(self):
        """Play alert sound if available."""
        try:
            # Try system bell
            print('\a', end='', flush=True)
        except:
            pass
            
    def run(self):
        """Run the terminal UI."""
        self.running = True
        
        print("\n" + "=" * 70)
        print("   EARARRAY REAL-TIME DOLPHINATTACK DETECTION")
        print("=" * 70)
        print("\n  Press Ctrl+C to stop monitoring\n")
        print("-" * 70)
        
        try:
            self.detector.start()
            
            # Status update loop
            while self.running:
                time.sleep(5)
                stats = self.detector.get_stats()
                print(f"  [STATUS] Chunks: {stats['chunks_processed']}, "
                      f"Attacks: {stats['attacks_detected']}")
                      
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            self.detector.stop()
            self._print_summary()
            
    def _print_summary(self):
        """Print session summary."""
        stats = self.detector.get_stats()
        
        print("\n" + "=" * 70)
        print("   SESSION SUMMARY")
        print("=" * 70)
        print(f"  Started:          {stats['start_time']}")
        print(f"  Chunks processed: {stats['chunks_processed']}")
        print(f"  Attacks detected: {stats['attacks_detected']}")
        print(f"  Alert history:    {len(self.detector.alert_manager.history)} events")
        print("=" * 70 + "\n")


# =============================================================================
# WEBHOOK/NOTIFICATION INTEGRATION
# =============================================================================

class WebhookNotifier:
    """Send alerts to webhook endpoints."""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        
    def __call__(self, alert_data: dict):
        """Send alert to webhook."""
        try:
            import urllib.request
            
            data = json.dumps(alert_data).encode('utf-8')
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=5) as response:
                logger.info(f"Webhook notification sent: {response.status}")
                
        except Exception as e:
            logger.error(f"Webhook error: {e}")


class FileLogger:
    """Log alerts to file."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        
    def __call__(self, alert_data: dict):
        """Log alert to file."""
        try:
            with open(self.filepath, 'a') as f:
                f.write(json.dumps(alert_data) + '\n')
        except Exception as e:
            logger.error(f"File logging error: {e}")


class EmailNotifier:
    """Send email alerts (template)."""
    
    def __init__(self, smtp_server: str, sender: str, recipient: str,
                 username: str = None, password: str = None):
        self.smtp_server = smtp_server
        self.sender = sender
        self.recipient = recipient
        self.username = username
        self.password = password
        
    def __call__(self, alert_data: dict):
        """Send email alert."""
        if alert_data['threat_level'] != ThreatLevel.ATTACK_DETECTED.value:
            return  # Only email for confirmed attacks
            
        try:
            import smtplib
            from email.mime.text import MIMEText
            
            subject = f"🚨 DolphinAttack Detected - {alert_data['timestamp']}"
            body = f"""
DolphinAttack Detection Alert
=============================

Time: {alert_data['timestamp']}
Direction: {alert_data['direction']}
Confidence: {alert_data['confidence']:.1%}

Features:
- Range BP: {alert_data['features']['range_bp']:.4f}
- Std BP: {alert_data['features']['std_bp']:.4f}
- Correlation: {alert_data['features']['correlation']:.4f}

This is an automated alert from EarArray Detection System.
"""
            
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.sender
            msg['To'] = self.recipient
            
            with smtplib.SMTP(self.smtp_server) as server:
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(msg)
                
            logger.info("Email notification sent")
            
        except Exception as e:
            logger.error(f"Email error: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='EarArray Real-Time DolphinAttack Detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python eararray_realtime.py                    # Start with default settings
  python eararray_realtime.py --list-devices    # List audio devices
  python eararray_realtime.py --device 2        # Use device #2
  python eararray_realtime.py --simulate        # Test without microphone
  python eararray_realtime.py --log alerts.json # Log alerts to file
        """
    )
    
    parser.add_argument('--list-devices', action='store_true',
                       help='List available audio devices')
    parser.add_argument('--device', type=int, default=None,
                       help='Audio device index')
    parser.add_argument('--channels', type=int, default=2,
                       help='Number of audio channels (default: 2)')
    parser.add_argument('--sample-rate', type=int, default=44100,
                       help='Sample rate in Hz (default: 44100)')
    parser.add_argument('--backend', choices=['sounddevice', 'pyaudio', 'simulate'],
                       default='sounddevice', help='Audio backend')
    parser.add_argument('--simulate', action='store_true',
                       help='Run in simulation mode (no microphone needed)')
    parser.add_argument('--log', type=str, default=None,
                       help='Log alerts to file')
    parser.add_argument('--webhook', type=str, default=None,
                       help='Webhook URL for alerts')
    parser.add_argument('--threshold', type=float, default=0.5,
                       help='Detection threshold (default: 0.5)')
    parser.add_argument('--cooldown', type=float, default=2.0,
                       help='Alert cooldown in seconds (default: 2.0)')
    
    args = parser.parse_args()
    
    # List devices
    if args.list_devices:
        SoundDeviceBackend.list_devices()
        return
        
    # Configure
    audio_config = AudioConfig(
        sample_rate=args.sample_rate,
        channels=args.channels,
        device_index=args.device
    )
    
    detection_config = DetectionConfig(
        detection_threshold=args.threshold,
        alert_cooldown=args.cooldown
    )
    
    # Determine backend
    backend = 'simulate' if args.simulate else args.backend
    
    # Create detector
    detector = RealTimeDetector(audio_config, detection_config, backend)
    
    # Add notifiers
    if args.log:
        detector.register_alert_callback(FileLogger(args.log))
        logger.info(f"Logging alerts to: {args.log}")
        
    if args.webhook:
        detector.register_alert_callback(WebhookNotifier(args.webhook))
        logger.info(f"Webhook configured: {args.webhook}")
    
    # Run UI
    ui = TerminalUI(detector)
    ui.run()


if __name__ == '__main__':
    main()