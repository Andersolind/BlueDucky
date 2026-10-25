#!/usr/bin/env python3
import numpy as np
from gnuradio import filter, fft, analog
from gnuradio.filter import firdes

class DigitalDSPPipelineService:
    """Constructs the translation mixers, demodulators, and filtering arrays."""
    def __init__(self, samp_rate, decimation, intermediate_rate):
        # 12.5 kHz tight tuner window
        taps = firdes.low_pass(1.0, samp_rate, 12500, 5000, fft.window.WIN_HAMMING, 6.76)
        self.digital_tuner = filter.freq_xlating_fir_filter_ccc(decimation, taps, 0, samp_rate)
        
        # Quadrature FM demodulator
        self.fm_demod = analog.quadrature_demod_cf(intermediate_rate / (2 * np.pi * 5000))
        
        # 300Hz - 3.5kHz vocal passband
        bp_taps = firdes.band_pass(1.0, intermediate_rate, 300, 3500, 400, fft.window.WIN_HAMMING, 6.76)
        self.voice_filter = filter.fir_filter_fff(1, bp_taps)
        
        # Dual resamplers
        self.audio_resampler = filter.rational_resampler_fff(48, 50, [], 0.4)
        self.whisper_resampler = filter.rational_resampler_fff(16, 50, [], 0.4)
