#!/usr/bin/env python3
"""
DolphinAttack Forensic Diagnostic Tool
=======================================

Helps identify the SOURCE of ultrasonic attack signals by:
1. Recording audio clips when attacks are detected
2. Showing detailed frequency spectrum analysis
3. Logging timing patterns to identify periodic sources
4. Generating spectrograms for visual analysis

Common sources to check:
- Smart speakers (Alexa, Google Home, HomePod)
- Smart TVs (ultrasonic ad beacons - ACR/tracking)
- Phones/tablets (ultrasonic cross-device tracking)
- Ultrasonic pest repellers
- Cheap electronics with noisy switching power supplies
- Some LED dimmers/drivers
- Wireless chargers
- Printers, scanners
- Some security systems

Usage:
    pip install numpy sounddevice scipy matplotlib

    python dolphin_forensics.py                     # Start forensic capture
    python dolphin_forensics.py --duration 300      # Run for 5 minutes
    python dolphin_forensics.py --save-all          # Save all audio (not just attacks)
"""

import numpy as np
import threading
import queue
import time
import argparse
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
from collections import deque
import json
import wave
import struct

# Optional imports
try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    print("WARNING: sounddevice not installed. Run: pip install sounddevice")

try:
    from scipy import signal as scipy_signal
    from scipy.io import wavfile
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("WARNING: scipy not installed. Run: pip install scipy")

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("WARNING: matplotlib not installed. Spectrograms disabled.")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ForensicConfig:
    sample_rate: int = 44100
    channels: int = 2
    chunk_size: int = 4410
    device_index: Optional[int] = None
    
    # Detection
    window_size: float = 0.4
    detection_threshold: float = 0.4
    
    # Forensic capture
    output_dir: str = "./dolphin_forensics"
    save_clips: bool = True
    clip_duration: float = 2.0  # seconds before+after detection
    save_spectrograms: bool = True
    
    # Analysis
    fft_size: int = 4096  # Higher resolution for frequency analysis
    

# =============================================================================
# FREQUENCY ANALYZER
# =============================================================================

class FrequencyAnalyzer:
    """Detailed frequency analysis to identify signal source."""
    
    # Known ultrasonic beacon frequencies (Hz)
    KNOWN_FREQUENCIES = {
        (18000, 19000): "SilverPush/Shopkick ultrasonic beacon",
        (19000, 20000): "Google Nearby / Chromecast",
        (17000, 18000): "Lisnr ultrasonic data",
        (16000, 17000): "Some TV ACR systems",
        (20000, 22000): "Generic ultrasonic communication",
        (23000, 25000): "Ultrasonic pest repeller",
        (15000, 16000): "CRT TV flyback (old TVs)",
    }
    
    def __init__(self, sample_rate: int, fft_size: int = 4096):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.nyquist = sample_rate / 2
        
    def analyze(self, audio: np.ndarray) -> dict:
        """Perform detailed frequency analysis."""
        # Use single channel or average
        if audio.ndim > 1:
            mono = np.mean(audio, axis=0)
        else:
            mono = audio
            
        # High-resolution FFT
        freqs = np.fft.rfftfreq(self.fft_size, 1/self.sample_rate)
        
        # Window and FFT
        if len(mono) >= self.fft_size:
            segment = mono[:self.fft_size]
        else:
            segment = np.pad(mono, (0, self.fft_size - len(mono)))
            
        window = np.hanning(self.fft_size)
        spectrum = np.abs(np.fft.rfft(segment * window))
        spectrum_db = 20 * np.log10(spectrum + 1e-10)
        
        # Find peaks
        peaks = self._find_peaks(freqs, spectrum_db)
        
        # Analyze different frequency bands
        bands = {
            'sub_bass': (20, 60),
            'bass': (60, 250),
            'low_mid': (250, 500),
            'mid': (500, 2000),
            'high_mid': (2000, 4000),
            'presence': (4000, 6000),
            'brilliance': (6000, 10000),
            'near_ultrasonic': (10000, 16000),
            'ultrasonic_low': (16000, 18000),
            'ultrasonic_mid': (18000, 20000),
            'ultrasonic_high': (20000, self.nyquist),
        }
        
        band_powers = {}
        for name, (low, high) in bands.items():
            if high > self.nyquist:
                high = self.nyquist
            idx_low = np.searchsorted(freqs, low)
            idx_high = np.searchsorted(freqs, high)
            if idx_high > idx_low:
                band_powers[name] = float(np.mean(spectrum_db[idx_low:idx_high]))
            else:
                band_powers[name] = -100.0
                
        # Check for known beacon frequencies
        detected_beacons = []
        for (low, high), name in self.KNOWN_FREQUENCIES.items():
            if high > self.nyquist:
                continue
            idx_low = np.searchsorted(freqs, low)
            idx_high = np.searchsorted(freqs, high)
            if idx_high > idx_low:
                power = np.max(spectrum_db[idx_low:idx_high])
                if power > -40:  # Significant power
                    detected_beacons.append({
                        'name': name,
                        'freq_range': (low, high),
                        'power_db': float(power)
                    })
                    
        # Find dominant ultrasonic frequency
        ultrasonic_start = np.searchsorted(freqs, 15000)
        if ultrasonic_start < len(spectrum_db):
            ultrasonic_spectrum = spectrum_db[ultrasonic_start:]
            ultrasonic_freqs = freqs[ultrasonic_start:]
            if len(ultrasonic_spectrum) > 0:
                max_idx = np.argmax(ultrasonic_spectrum)
                dominant_ultrasonic = float(ultrasonic_freqs[max_idx])
                dominant_ultrasonic_power = float(ultrasonic_spectrum[max_idx])
            else:
                dominant_ultrasonic = 0
                dominant_ultrasonic_power = -100
        else:
            dominant_ultrasonic = 0
            dominant_ultrasonic_power = -100
            
        return {
            'peaks': peaks,
            'band_powers': band_powers,
            'detected_beacons': detected_beacons,
            'dominant_ultrasonic_hz': dominant_ultrasonic,
            'dominant_ultrasonic_db': dominant_ultrasonic_power,
            'spectrum': spectrum_db.tolist(),
            'freqs': freqs.tolist()
        }
        
    def _find_peaks(self, freqs: np.ndarray, spectrum_db: np.ndarray, 
                    threshold_db: float = -50, min_distance: int = 20) -> List[dict]:
        """Find significant peaks in spectrum."""
        peaks = []
        
        for i in range(min_distance, len(spectrum_db) - min_distance):
            if spectrum_db[i] > threshold_db:
                # Check if local maximum
                if (spectrum_db[i] > spectrum_db[i-min_distance:i].max() and
                    spectrum_db[i] > spectrum_db[i+1:i+min_distance+1].max()):
                    peaks.append({
                        'freq_hz': float(freqs[i]),
                        'power_db': float(spectrum_db[i])
                    })
                    
        # Sort by power
        peaks.sort(key=lambda x: x['power_db'], reverse=True)
        return peaks[:20]  # Top 20 peaks


# =============================================================================
# TIMING ANALYZER  
# =============================================================================

class TimingAnalyzer:
    """Analyze timing patterns to identify periodic sources."""
    
    def __init__(self):
        self.detection_times = deque(maxlen=1000)
        self.direction_history = deque(maxlen=1000)
        
    def add_detection(self, timestamp: float, direction: str):
        self.detection_times.append(timestamp)
        self.direction_history.append(direction)
        
    def analyze(self) -> dict:
        """Analyze timing patterns."""
        if len(self.detection_times) < 3:
            return {'pattern': 'insufficient_data'}
            
        times = np.array(list(self.detection_times))
        intervals = np.diff(times)
        
        if len(intervals) == 0:
            return {'pattern': 'insufficient_data'}
            
        analysis = {
            'total_detections': len(times),
            'duration_seconds': times[-1] - times[0] if len(times) > 1 else 0,
            'mean_interval': float(np.mean(intervals)),
            'std_interval': float(np.std(intervals)),
            'min_interval': float(np.min(intervals)),
            'max_interval': float(np.max(intervals)),
        }
        
        # Check for periodicity
        if analysis['std_interval'] < analysis['mean_interval'] * 0.3:
            analysis['pattern'] = 'PERIODIC'
            analysis['period_seconds'] = analysis['mean_interval']
            analysis['likely_source'] = self._guess_periodic_source(analysis['mean_interval'])
        elif analysis['std_interval'] < analysis['mean_interval'] * 0.6:
            analysis['pattern'] = 'SEMI_PERIODIC'
        else:
            analysis['pattern'] = 'IRREGULAR'
            
        # Direction analysis
        directions = list(self.direction_history)
        left_count = directions.count('Left')
        right_count = directions.count('Right')
        total = left_count + right_count
        
        if total > 0:
            analysis['direction_bias'] = {
                'left_percent': left_count / total * 100,
                'right_percent': right_count / total * 100,
                'dominant': 'Left' if left_count > right_count else 'Right'
            }
            
        # Check for bursts
        burst_threshold = 0.5  # seconds
        burst_count = 0
        current_burst = 1
        for interval in intervals:
            if interval < burst_threshold:
                current_burst += 1
            else:
                if current_burst > 2:
                    burst_count += 1
                current_burst = 1
                
        analysis['burst_pattern'] = burst_count > len(intervals) * 0.1
        
        return analysis
        
    def _guess_periodic_source(self, period: float) -> str:
        """Guess source based on period."""
        if 0.9 < period < 1.1:
            return "1-second beacon (common in TV ACR)"
        elif 1.9 < period < 2.1:
            return "2-second beacon (ad tracking)"
        elif 4.9 < period < 5.1:
            return "5-second beacon (Nearby/presence)"
        elif 9.9 < period < 10.1:
            return "10-second beacon (background tracking)"
        elif 29 < period < 31:
            return "30-second beacon (periodic check-in)"
        elif 59 < period < 61:
            return "1-minute beacon (low-power tracking)"
        elif period < 0.5:
            return "High-frequency (data transmission or interference)"
        else:
            return f"Unknown periodic source ({period:.1f}s interval)"


# =============================================================================
# AUDIO RECORDER
# =============================================================================

class ClipRecorder:
    """Records and saves audio clips around detections."""
    
    def __init__(self, config: ForensicConfig):
        self.config = config
        self.sample_rate = config.sample_rate
        self.channels = config.channels
        
        # Circular buffer for pre-detection audio
        buffer_samples = int(config.clip_duration * config.sample_rate)
        self.audio_buffer = deque(maxlen=buffer_samples)
        
        # Create output directory
        os.makedirs(config.output_dir, exist_ok=True)
        
    def add_audio(self, audio: np.ndarray):
        """Add audio to buffer."""
        # Flatten multichannel to interleaved samples
        if audio.ndim > 1:
            for i in range(audio.shape[1]):
                for ch in range(audio.shape[0]):
                    self.audio_buffer.append(audio[ch, i])
        else:
            for sample in audio:
                self.audio_buffer.append(sample)
                
    def save_clip(self, detection_id: int, metadata: dict) -> str:
        """Save buffered audio as WAV file."""
        filename = f"detection_{detection_id:04d}_{datetime.now().strftime('%H%M%S')}.wav"
        filepath = os.path.join(self.config.output_dir, filename)
        
        # Convert buffer to numpy array
        audio_data = np.array(list(self.audio_buffer), dtype=np.float32)
        
        # Reshape to channels
        if len(audio_data) > 0:
            # Trim to complete frames
            samples_per_frame = self.channels
            complete_samples = (len(audio_data) // samples_per_frame) * samples_per_frame
            audio_data = audio_data[:complete_samples]
            audio_data = audio_data.reshape(-1, self.channels)
            
            # Save as WAV
            self._save_wav(filepath, audio_data)
            
            # Save metadata
            meta_path = filepath.replace('.wav', '.json')
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)
                
        return filepath
        
    def _save_wav(self, filepath: str, audio: np.ndarray):
        """Save audio as WAV file."""
        # Normalize to int16 range
        audio_int16 = (audio * 32767).astype(np.int16)
        
        with wave.open(filepath, 'w') as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(self.sample_rate)
            wav.writeframes(audio_int16.tobytes())


# =============================================================================
# SPECTROGRAM GENERATOR
# =============================================================================

class SpectrogramGenerator:
    """Generate spectrograms for visual analysis."""
    
    def __init__(self, config: ForensicConfig):
        self.config = config
        self.sample_rate = config.sample_rate
        
    def generate(self, audio: np.ndarray, detection_id: int, 
                 freq_analysis: dict) -> Optional[str]:
        """Generate and save spectrogram."""
        if not HAS_MATPLOTLIB:
            return None
            
        # Use mono
        if audio.ndim > 1:
            mono = np.mean(audio, axis=0)
        else:
            mono = audio
            
        if len(mono) < 256:
            return None
            
        filename = f"spectrogram_{detection_id:04d}_{datetime.now().strftime('%H%M%S')}.png"
        filepath = os.path.join(self.config.output_dir, filename)
        
        fig, axes = plt.subplots(3, 1, figsize=(12, 10))
        
        # 1. Full spectrogram
        ax1 = axes[0]
        if HAS_SCIPY:
            f, t, Sxx = scipy_signal.spectrogram(mono, self.sample_rate, 
                                                  nperseg=1024, noverlap=512)
            ax1.pcolormesh(t, f, 10 * np.log10(Sxx + 1e-10), shading='gouraud', cmap='viridis')
        else:
            # Fallback: simple spectrogram
            ax1.specgram(mono, Fs=self.sample_rate, cmap='viridis')
        ax1.set_ylabel('Frequency (Hz)')
        ax1.set_title('Full Spectrum Spectrogram')
        ax1.set_ylim(0, self.sample_rate/2)
        
        # 2. Ultrasonic band (15kHz+)
        ax2 = axes[1]
        if HAS_SCIPY:
            ax2.pcolormesh(t, f, 10 * np.log10(Sxx + 1e-10), shading='gouraud', cmap='magma')
            ax2.set_ylim(15000, self.sample_rate/2)
        ax2.set_ylabel('Frequency (Hz)')
        ax2.set_title('Ultrasonic Band (15kHz+) - ATTACK FREQUENCIES')
        
        # 3. Frequency spectrum with peaks
        ax3 = axes[2]
        if 'freqs' in freq_analysis and 'spectrum' in freq_analysis:
            freqs = np.array(freq_analysis['freqs'])
            spectrum = np.array(freq_analysis['spectrum'])
            ax3.plot(freqs, spectrum, 'b-', linewidth=0.5)
            ax3.axvline(x=15000, color='r', linestyle='--', label='Ultrasonic threshold')
            ax3.axvline(x=18000, color='orange', linestyle='--', label='Common beacon freq')
            ax3.axvline(x=20000, color='red', linestyle='--', label='20kHz')
            
            # Mark peaks
            for peak in freq_analysis.get('peaks', [])[:10]:
                if peak['freq_hz'] > 10000:
                    ax3.axvline(x=peak['freq_hz'], color='green', alpha=0.5)
                    ax3.annotate(f"{peak['freq_hz']:.0f}Hz", 
                               xy=(peak['freq_hz'], peak['power_db']),
                               fontsize=8)
        ax3.set_xlabel('Frequency (Hz)')
        ax3.set_ylabel('Power (dB)')
        ax3.set_title('Frequency Spectrum with Peaks')
        ax3.legend()
        ax3.set_xlim(0, self.sample_rate/2)
        ax3.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(filepath, dpi=150)
        plt.close()
        
        return filepath


# =============================================================================
# CHANNEL ANALYZER
# =============================================================================

class ChannelAnalyzer:
    """Analyze per-channel characteristics to help localize source."""
    
    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        
    def analyze(self, multichannel: np.ndarray) -> dict:
        """Analyze each channel separately."""
        results = {
            'channels': [],
            'channel_difference': {},
            'localization_hints': []
        }
        
        for ch_idx in range(multichannel.shape[0]):
            channel = multichannel[ch_idx]
            
            rms = np.sqrt(np.mean(channel ** 2))
            peak = np.max(np.abs(channel))
            
            # FFT for this channel
            spectrum = np.abs(np.fft.rfft(channel))
            freqs = np.fft.rfftfreq(len(channel), 1/self.sample_rate)
            
            # Ultrasonic power
            ultra_idx = np.searchsorted(freqs, 15000)
            if ultra_idx < len(spectrum):
                ultrasonic_power = np.mean(spectrum[ultra_idx:])
            else:
                ultrasonic_power = 0
                
            results['channels'].append({
                'index': ch_idx,
                'name': 'Left' if ch_idx == 0 else 'Right',
                'rms': float(rms),
                'peak': float(peak),
                'ultrasonic_power': float(ultrasonic_power)
            })
            
        # Compare channels
        if len(results['channels']) >= 2:
            ch0 = results['channels'][0]
            ch1 = results['channels'][1]
            
            rms_diff = ch0['rms'] - ch1['rms']
            ultra_diff = ch0['ultrasonic_power'] - ch1['ultrasonic_power']
            
            results['channel_difference'] = {
                'rms_difference': float(rms_diff),
                'ultrasonic_difference': float(ultra_diff),
                'stronger_channel': 'Left' if ultra_diff > 0 else 'Right'
            }
            
            # Localization hints
            ratio = max(ch0['ultrasonic_power'], ch1['ultrasonic_power']) / \
                   (min(ch0['ultrasonic_power'], ch1['ultrasonic_power']) + 1e-10)
                   
            if ratio > 3:
                results['localization_hints'].append(
                    f"Strong directional signal - source likely on {results['channel_difference']['stronger_channel']} side"
                )
            elif ratio > 1.5:
                results['localization_hints'].append(
                    f"Moderate directional bias toward {results['channel_difference']['stronger_channel']}"
                )
            else:
                results['localization_hints'].append(
                    "Signal relatively balanced - source may be centered or distant"
                )
                
        return results


# =============================================================================
# MAIN FORENSIC DETECTOR
# =============================================================================

class ForensicDetector:
    """Main forensic detection and analysis system."""
    
    def __init__(self, config: ForensicConfig):
        self.config = config
        self.is_running = False
        
        # Components
        self.freq_analyzer = FrequencyAnalyzer(config.sample_rate, config.fft_size)
        self.timing_analyzer = TimingAnalyzer()
        self.channel_analyzer = ChannelAnalyzer(config.sample_rate)
        self.clip_recorder = ClipRecorder(config) if config.save_clips else None
        self.spectrogram_gen = SpectrogramGenerator(config) if config.save_spectrograms else None
        
        # Audio
        self.audio_queue = queue.Queue(maxsize=100)
        self.stream = None
        
        # State
        self.detection_count = 0
        self.start_time = None
        self.all_detections = []
        
    def start(self):
        if not HAS_SOUNDDEVICE:
            raise RuntimeError("sounddevice required")
            
        def audio_callback(indata, frames, time_info, status):
            if status:
                pass
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
        self.start_time = time.time()
        
        print(f"\n{'='*70}")
        print("  DOLPHINATTACK FORENSIC ANALYZER")
        print(f"{'='*70}")
        print(f"  Output directory: {self.config.output_dir}")
        print(f"  Sample rate: {self.config.sample_rate} Hz")
        print(f"  Channels: {self.config.channels}")
        print(f"  Saving clips: {self.config.save_clips}")
        print(f"  Saving spectrograms: {self.config.save_spectrograms}")
        print(f"\n  Listening... Press Ctrl+C to stop and see report\n")
        print(f"{'='*70}\n")
        
    def stop(self):
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            
    def run(self, duration: Optional[float] = None):
        """Run forensic analysis."""
        self.start()
        
        buffer = np.zeros((self.config.channels, 0))
        samples_needed = int(self.config.window_size * self.config.sample_rate)
        
        try:
            while self.is_running:
                if duration and (time.time() - self.start_time) > duration:
                    print("\nDuration reached, stopping...")
                    break
                    
                try:
                    audio = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                    
                # Add to clip recorder buffer
                if self.clip_recorder:
                    self.clip_recorder.add_audio(audio)
                    
                # Buffer for window
                buffer = np.concatenate([buffer, audio], axis=1)
                
                while buffer.shape[1] >= samples_needed:
                    window = buffer[:, :samples_needed]
                    buffer = buffer[:, int(samples_needed * 0.5):]  # 50% overlap
                    
                    self._analyze_window(window)
                    
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            self.stop()
            self._print_report()
            
    def _analyze_window(self, audio: np.ndarray):
        """Analyze a window of audio."""
        # Quick check for channel imbalance (attack indicator)
        ch_powers = [np.sqrt(np.mean(audio[i]**2)) for i in range(audio.shape[0])]
        max_power = max(ch_powers)
        min_power = min(ch_powers) + 1e-10
        imbalance = max_power / min_power
        
        # Check for significant ultrasonic content
        mono = np.mean(audio, axis=0)
        spectrum = np.abs(np.fft.rfft(mono))
        freqs = np.fft.rfftfreq(len(mono), 1/self.config.sample_rate)
        
        ultra_idx = np.searchsorted(freqs, 15000)
        audible_power = np.mean(spectrum[:ultra_idx]) if ultra_idx > 0 else 1
        ultrasonic_power = np.mean(spectrum[ultra_idx:]) if ultra_idx < len(spectrum) else 0
        
        ultra_ratio = ultrasonic_power / (audible_power + 1e-10)
        
        # Detection threshold
        is_attack = imbalance > 1.5 and ultra_ratio > 0.1
        
        if is_attack:
            self._process_detection(audio)
            
    def _process_detection(self, audio: np.ndarray):
        """Process a detected attack."""
        self.detection_count += 1
        timestamp = time.time()
        
        # Detailed analysis
        freq_analysis = self.freq_analyzer.analyze(audio)
        channel_analysis = self.channel_analyzer.analyze(audio)
        
        direction = channel_analysis['channel_difference'].get('stronger_channel', 'Unknown')
        self.timing_analyzer.add_detection(timestamp, direction)
        
        detection_data = {
            'id': self.detection_count,
            'timestamp': datetime.now().isoformat(),
            'unix_time': timestamp,
            'direction': direction,
            'frequency_analysis': {
                'dominant_ultrasonic_hz': freq_analysis['dominant_ultrasonic_hz'],
                'dominant_ultrasonic_db': freq_analysis['dominant_ultrasonic_db'],
                'detected_beacons': freq_analysis['detected_beacons'],
                'top_peaks': freq_analysis['peaks'][:5]
            },
            'channel_analysis': channel_analysis,
        }
        
        self.all_detections.append(detection_data)
        
        # Save clip
        clip_path = None
        if self.clip_recorder:
            clip_path = self.clip_recorder.save_clip(self.detection_count, detection_data)
            
        # Save spectrogram
        spec_path = None
        if self.spectrogram_gen:
            mono = np.mean(audio, axis=0)
            # Extend with buffer data if available
            if self.clip_recorder and len(self.clip_recorder.audio_buffer) > 0:
                extended = np.array(list(self.clip_recorder.audio_buffer))
                if len(extended) > self.config.channels:
                    extended = extended[::self.config.channels]  # Take one channel
                    spec_path = self.spectrogram_gen.generate(extended, self.detection_count, freq_analysis)
            else:
                spec_path = self.spectrogram_gen.generate(mono, self.detection_count, freq_analysis)
        
        # Print detection
        self._print_detection(detection_data, clip_path, spec_path)
        
    def _print_detection(self, data: dict, clip_path: Optional[str], spec_path: Optional[str]):
        """Print detection details."""
        print(f"\n{'!'*70}")
        print(f"  DETECTION #{data['id']} - {data['timestamp']}")
        print(f"{'!'*70}")
        print(f"  Direction: {data['direction']}")
        print(f"  Dominant ultrasonic: {data['frequency_analysis']['dominant_ultrasonic_hz']:.0f} Hz "
              f"({data['frequency_analysis']['dominant_ultrasonic_db']:.1f} dB)")
        
        # Beacon detection
        beacons = data['frequency_analysis']['detected_beacons']
        if beacons:
            print(f"\n  ⚠️  POSSIBLE BEACON IDENTIFIED:")
            for beacon in beacons:
                print(f"      - {beacon['name']}")
                print(f"        Frequency: {beacon['freq_range'][0]}-{beacon['freq_range'][1]} Hz")
                print(f"        Power: {beacon['power_db']:.1f} dB")
        
        # Top frequency peaks
        print(f"\n  Top ultrasonic peaks:")
        for peak in data['frequency_analysis']['top_peaks'][:5]:
            if peak['freq_hz'] > 10000:
                print(f"      {peak['freq_hz']:.0f} Hz ({peak['power_db']:.1f} dB)")
                
        # Channel info
        hints = data['channel_analysis'].get('localization_hints', [])
        if hints:
            print(f"\n  Localization hints:")
            for hint in hints:
                print(f"      → {hint}")
                
        # Files saved
        if clip_path:
            print(f"\n  📁 Audio saved: {os.path.basename(clip_path)}")
        if spec_path:
            print(f"  📊 Spectrogram: {os.path.basename(spec_path)}")
            
        print(f"{'!'*70}\n")
        
    def _print_report(self):
        """Print final forensic report."""
        print(f"\n{'='*70}")
        print("  FORENSIC ANALYSIS REPORT")
        print(f"{'='*70}")
        
        duration = time.time() - self.start_time if self.start_time else 0
        print(f"\n  Duration: {duration:.1f} seconds")
        print(f"  Total detections: {self.detection_count}")
        print(f"  Detection rate: {self.detection_count / (duration/60):.1f} per minute")
        
        # Timing analysis
        print(f"\n  TIMING ANALYSIS:")
        timing = self.timing_analyzer.analyze()
        print(f"    Pattern: {timing.get('pattern', 'Unknown')}")
        if 'mean_interval' in timing:
            print(f"    Mean interval: {timing['mean_interval']:.2f}s")
            print(f"    Std deviation: {timing['std_interval']:.2f}s")
        if 'likely_source' in timing:
            print(f"    ⚠️  Likely source: {timing['likely_source']}")
        if 'direction_bias' in timing:
            bias = timing['direction_bias']
            dominant = bias['dominant'].lower()
            pct = bias.get(f'{dominant}_percent', 0)
            print(f"    Direction bias: {bias['dominant']} ({pct:.1f}%)")
            
        # Frequency analysis summary
        if self.all_detections:
            print(f"\n  FREQUENCY ANALYSIS:")
            all_freqs = [d['frequency_analysis']['dominant_ultrasonic_hz'] 
                        for d in self.all_detections]
            print(f"    Most common ultrasonic freq: {np.median(all_freqs):.0f} Hz")
            print(f"    Frequency range: {min(all_freqs):.0f} - {max(all_freqs):.0f} Hz")
            
            # Beacon summary
            all_beacons = []
            for d in self.all_detections:
                all_beacons.extend(d['frequency_analysis']['detected_beacons'])
            if all_beacons:
                beacon_names = [b['name'] for b in all_beacons]
                from collections import Counter
                beacon_counts = Counter(beacon_names)
                print(f"\n  DETECTED BEACON TYPES:")
                for name, count in beacon_counts.most_common():
                    print(f"    - {name}: {count} detections")
                    
        # Investigation suggestions
        print(f"\n  INVESTIGATION SUGGESTIONS:")
        print("    1. Check devices on the DOMINANT side of detections")
        
        if timing.get('pattern') == 'PERIODIC':
            print(f"    2. Look for device with ~{timing.get('mean_interval', 0):.1f}s update cycle")
            
        if self.all_detections:
            median_freq = np.median(all_freqs)
            if 18000 < median_freq < 20000:
                print("    3. ⚠️  18-20kHz range suggests smart TV or ad beacon")
                print("       → Check TVs, streaming devices, smart speakers")
            elif median_freq > 20000:
                print("    3. >20kHz suggests ultrasonic device or interference")
                print("       → Check pest repellers, motion sensors, wireless chargers")
            elif 15000 < median_freq < 18000:
                print("    3. 15-18kHz may be CRT/old electronics or specialized beacon")
                
        print(f"\n  Output files saved to: {self.config.output_dir}")
        print(f"{'='*70}\n")
        
        # Save full report
        report_path = os.path.join(self.config.output_dir, 
                                   f"forensic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(report_path, 'w') as f:
            json.dump({
                'summary': {
                    'duration': duration,
                    'total_detections': self.detection_count,
                    'timing_analysis': timing
                },
                'detections': self.all_detections
            }, f, indent=2)
        print(f"  Full report saved: {report_path}\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='DolphinAttack Forensic Analyzer')
    parser.add_argument('--device', type=int, default=None, help='Audio device index')
    parser.add_argument('--duration', type=float, default=None, help='Run duration in seconds')
    parser.add_argument('--output', type=str, default='./dolphin_forensics', help='Output directory')
    parser.add_argument('--no-clips', action='store_true', help='Disable audio clip saving')
    parser.add_argument('--no-spectrograms', action='store_true', help='Disable spectrogram generation')
    parser.add_argument('--list-devices', action='store_true', help='List audio devices')
    
    args = parser.parse_args()
    
    if args.list_devices:
        if HAS_SOUNDDEVICE:
            print(sd.query_devices())
        return
        
    config = ForensicConfig(
        device_index=args.device,
        output_dir=args.output,
        save_clips=not args.no_clips,
        save_spectrograms=not args.no_spectrograms and HAS_MATPLOTLIB
    )
    
    detector = ForensicDetector(config)
    detector.run(duration=args.duration)


if __name__ == '__main__':
    main()