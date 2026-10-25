#!/usr/bin/env python3
import numpy as np

class MetricAnalysisService:
    """Calculates phase delay correlation loops, rhythms, and motion variations."""
    def __init__(self, auto_squelch=0.08):
        self.threshold = auto_squelch
        self.historical_envelopes = []
        self.last_frame = None
        self.last_vad_duration = 0.0

    def analyze_rhythm_cadence(self):
        if len(self.historical_envelopes) < 16:
            return False, 0.0
        env_fft = np.abs(np.fft.fft(self.historical_envelopes))
        peak_idx = np.argmax(env_fft[1:len(env_fft)//2]) + 1
        if env_fft[peak_idx] > 0.45:
            bpm = (peak_idx / len(self.historical_envelopes)) * 60.0
            return (bpm > 20.0), bpm
        return False, 0.0

    def analyze_motion_anomaly(self, data_length, vad_active):
        if vad_active and self.last_vad_duration > 0:
            delta = abs(data_length - self.last_vad_duration) / self.last_vad_duration
            self.last_vad_duration = data_length
            return delta > 0.30
        if vad_active:
            self.last_vad_duration = data_length
        return False

    def analyze_beam_cross_loop(self, audio_np):
        if self.last_frame is not None and len(self.last_frame) == len(audio_np):
            correlation = np.correlate(audio_np, self.last_frame, mode='full')
            peak_lag = np.argmax(np.abs(correlation)) - (len(audio_np) - 1)
            if np.max(np.abs(correlation)) > 0.55 and abs(peak_lag) > 120:
                delay_ms = (abs(peak_lag) / 16000.0) * 1000.0
                return True, delay_ms
        return False, 0.0
