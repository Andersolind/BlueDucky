"""
AI-Voice Resampling Module
==========================
Provides robust, anti-aliased resampling between physical sampling rates:
- 192 kHz (Dodotronic ultrasound) -> 48 kHz (PANNs / Audible)
- 48 kHz / 44.1 kHz -> 16 kHz (HuBERT speech tokenization)
- 16 kHz -> 24 kHz / 44.1 kHz (StyleTTS2 / Playback)
"""

import numpy as np
import scipy.signal as signal
from typing import Optional

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False

class AudioResampler:
    """Handles rate conversions with high-order anti-aliasing filtering."""

    @staticmethod
    def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        if orig_sr == target_sr or len(audio) == 0:
            return audio

        if HAS_LIBROSA:
            try:
                # Librosa uses resampy with high quality Kaiser windowing
                return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)
            except Exception:
                pass

        # Fallback to scipy signal resample with anti-aliasing pre-filter
        num_target_samples = int(len(audio) * (target_sr / orig_sr))
        if target_sr < orig_sr:
            # Low-pass filter before decimation to prevent aliasing
            nyquist_target = 0.5 * target_sr
            nyquist_orig = 0.5 * orig_sr
            cutoff = min(0.95 * nyquist_target, nyquist_orig - 100)
            if cutoff > 0 and cutoff < nyquist_orig:
                b, a = signal.butter(8, cutoff / nyquist_orig, btype='low')
                audio = signal.filtfilt(b, a, audio)
        
        return signal.resample(audio, num_target_samples)

    @staticmethod
    def prepare_dodotronic_for_panns(raw_audio: np.ndarray, orig_sr: int = 192000, target_sr: int = 48000) -> np.ndarray:
        """
        Downsamples 192kHz Dodotronic data to 48kHz while preserving
        subharmonic acoustic anomalies in the 20kHz - 24kHz window.
        """
        resampled = AudioResampler.resample(raw_audio, orig_sr, target_sr)
        max_val = np.max(np.abs(resampled))
        if max_val > 0:
            resampled = resampled / max_val
        return resampled

    @staticmethod
    def prepare_for_hubert(audio: np.ndarray, orig_sr: int) -> np.ndarray:
        """Converts audio chunk to HuBERT 16kHz standard."""
        return AudioResampler.resample(audio, orig_sr, 16000)

    @staticmethod
    def prepare_for_playback(audio: np.ndarray, orig_sr: int = 16000, target_sr: int = 44100) -> np.ndarray:
        """Prepares synthesized voice for system DAC playback."""
        out = AudioResampler.resample(audio, orig_sr, target_sr)
        out = out - np.mean(out)
        max_val = np.max(np.abs(out))
        if max_val > 0:
            out = out / (max_val + 1e-5)
        return out
