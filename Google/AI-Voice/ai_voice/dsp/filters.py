"""
AI-Voice Digital Signal Processing (DSP) Module
===============================================
Implements:
1. Vocal bandpass filtering (Butterworth 4th order, 80Hz - 8kHz)
2. Electronic coil whine & power brick notch filter array
3. High-frequency ultrasonic windowing (3.5kHz - 45kHz)
4. Dynamic spectral gating & adaptive noise floor power subtraction
5. Mechanical friction / cable tug rejection gate
6. Hilbert transform envelope demodulation (ultrasound-to-audible conversion)
"""

import numpy as np
import scipy.signal as signal
from typing import List, Tuple, Optional
from ai_voice.config import DspFilterConfig

class AudioFilterEngine:
    """Core DSP filter bank for vocal enhancement and noise nullification."""

    def __init__(self, sample_rate: int = 48000, config: Optional[DspFilterConfig] = None):
        self.sample_rate = sample_rate
        self.config = config or DspFilterConfig()
        
        # 1. Base Vocal Bandpass
        nyquist = 0.5 * self.sample_rate
        low = max(1.0, min(self.config.vocal_low_cutoff, nyquist - 10))
        high = max(low + 10, min(self.config.vocal_high_cutoff, nyquist - 10))
        self.b_vocal, self.a_vocal = signal.butter(
            self.config.filter_order,
            [low / nyquist, high / nyquist],
            btype='band'
        )

        # 2. Multi-Notch Array for Electronic Whine & AC Harmonics
        self.notches: List[Tuple[np.ndarray, np.ndarray]] = []
        for freq in self.config.electronic_notch_frequencies:
            if freq < nyquist:
                b, a = signal.iirnotch(freq, Q=self.config.notch_q, fs=self.sample_rate)
                self.notches.append((b, a))

        # 3. Dynamic Spectral Noise Subtraction state
        self.noise_floor_estimate: Optional[np.ndarray] = None
        self.last_frame_energy: float = 0.0

    def apply_vocal_enhancement(self, audio_chunk: np.ndarray) -> np.ndarray:
        """Applies bandpass filtering and coil whine notch filters."""
        if len(audio_chunk) < 16:
            return audio_chunk
        try:
            # Bandpass
            filtered = signal.filtfilt(self.b_vocal, self.a_vocal, audio_chunk)
            # Notches
            for b, a in self.notches:
                filtered = signal.filtfilt(b, a, filtered)
            return filtered
        except Exception:
            return audio_chunk

    def check_mechanical_cable_spike(self, audio_chunk: np.ndarray) -> Tuple[bool, float, float]:
        """
        Detects sudden mechanical thuds, contact pressure surges, or cable friction.
        Returns: (is_spike_rejected, current_energy, energy_derivative)
        """
        current_energy = float(np.sqrt(np.mean(audio_chunk**2) + 1e-12))
        energy_derivative = abs(current_energy - self.last_frame_energy)
        self.last_frame_energy = current_energy
        is_spike = energy_derivative > self.config.cable_friction_gate_threshold
        return is_spike, current_energy, energy_derivative

    def reset_noise_floor(self):
        self.noise_floor_estimate = None
        self.last_frame_energy = 0.0


class UltrasonicDemodulator:
    """
    Processes high-speed ultrasonic recordings (e.g. 192kHz Dodotronic)
    to isolate acoustic beams, apply spectral gating, and envelope demodulate to audible sound.
    """

    def __init__(self, sample_rate: int = 192000, config: Optional[DspFilterConfig] = None):
        self.sample_rate = sample_rate
        self.config = config or DspFilterConfig()
        nyquist = 0.5 * self.sample_rate
        
        hp_cutoff = max(100.0, min(self.config.ultrasound_highpass_cutoff, nyquist - 100))
        lp_cutoff = max(hp_cutoff + 100, min(self.config.ultrasound_lowpass_cutoff, nyquist - 100))
        
        self.b_hp, self.a_hp = signal.butter(6, hp_cutoff / nyquist, btype='high')
        self.b_lp, self.a_lp = signal.butter(6, lp_cutoff / nyquist, btype='low')
        
        self.noise_floor_estimate: Optional[np.ndarray] = None
        self.alpha = self.config.noise_floor_alpha

    def process_ultrasound_frame(self, raw_frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        Takes raw 192kHz audio frame, filters, performs dynamic spectral gating,
        and applies Hilbert envelope demodulation.
        Returns: (unmasked_ultrasound, demodulated_audible_envelope, peak_amplitude)
        """
        if len(raw_frame) < 16:
            return raw_frame, raw_frame, 0.0

        try:
            # 1. Frequency Windowing
            filtered = signal.filtfilt(self.b_hp, self.a_hp, raw_frame)
            filtered = signal.filtfilt(self.b_lp, self.a_lp, filtered)

            # 2. Dynamic Spectral Gating
            fft_frame = np.fft.rfft(filtered)
            magnitude = np.abs(fft_frame)
            phase = np.angle(fft_frame)

            if self.noise_floor_estimate is None or len(self.noise_floor_estimate) != len(magnitude):
                self.noise_floor_estimate = (magnitude * 0.1).copy()
            else:
                self.noise_floor_estimate = (self.alpha * self.noise_floor_estimate) + ((1.0 - self.alpha) * magnitude)

            cleaned_magnitude = np.maximum(
                magnitude - (self.noise_floor_estimate * self.config.noise_subtraction_multiplier),
                0.0
            )
            cleaned_fft = cleaned_magnitude * np.exp(1j * phase)
            unmasked_audio = np.fft.irfft(cleaned_fft, n=len(raw_frame))

            # 3. Envelope Demodulation via Analytic Signal (Hilbert Transform)
            analytic_signal = signal.hilbert(unmasked_audio)
            demodulated_beam = np.abs(analytic_signal)
            peak_amp = float(np.max(demodulated_beam)) if len(demodulated_beam) > 0 else 0.0

            return unmasked_audio, demodulated_beam, peak_amp
        except Exception as e:
            return raw_frame, raw_frame, 0.0
