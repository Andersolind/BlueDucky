#!/usr/bin/env python3
import numpy as np
import time

class StructuralMicrophonicsService:
    """
    Decoupled service to detect and extract room acoustic microphonics 
    modulated onto local unshielded structural electronics and RF carriers.
    """
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.baseline_noise_floor = None
        self.microphonic_lock = False
        
        # Historical baseline tracking for room energy anomaly shifts
        self.energy_rolling_window = []

    def extract_microphonic_envelope(self, audio_np):
        """
        Applies a digital notch configuration to strip away the primary electrical 
        carrier hum, amplifying the weak acoustic sideband reflections riding on the line.
        """
        if len(audio_np) < 1024:
            return False, audio_np, 0.0

        # Convert raw audio data chunk into the frequency domain
        fft_data = np.fft.fft(audio_np)
        fft_freqs = np.fft.fftfreq(len(fft_data), 1.0 / self.sample_rate)
        
        # --- DIGITAL CARRIER HUM NOTCH FILTER ---
        # Eliminate the massive 60 Hz mains power or central carrier frequency spike 
        # that masks the delicate structural microphonic vibrations
        mains_idx = np.where((np.abs(fft_freqs) >= 58.0) & (np.abs(fft_freqs) <= 62.0))
        fft_data[mains_idx] = 0.0 + 0.0j
        
        # Reconstruct the cleaned, notched time-domain audio wave
        filtered_audio = np.fft.ifft(fft_data).real
        
        # Measure the residual microphonic signal energy variance
        micro_variance = np.var(filtered_audio)
        
        # Initialize or update the room's environmental baseline noise footprint
        if self.baseline_noise_floor is None:
            self.baseline_noise_floor = micro_variance
            return False, filtered_audio, 0.0
            
        # --- DETECT UNWANTED ENVIRONMENTAL RESONANCE SHIFTS ---
        # Calculate how much the room's current vibrational energy has shifted 
        # relative to your established ambient background baseline
        energy_shift_ratio = micro_variance / (self.baseline_noise_floor + 1e-9)
        
        # Append the current shift to the rolling timeline layout
        self.energy_rolling_window.append(energy_shift_ratio)
        if len(self.energy_rolling_window) > 30:
            self.energy_rolling_window.pop(0)
            
        # If the structural microphonics energy surges by over 2.5x (250%), 
        # a mechanical-to-electrical room conversion anomaly has occurred.
        self.microphonic_lock = energy_shift_ratio > 2.5
        
        return self.microphonic_lock, filtered_audio, energy_shift_ratio
