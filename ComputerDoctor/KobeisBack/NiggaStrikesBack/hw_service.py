#!/usr/bin/env python3
import osmosdr

class SDRHardwareService:
    """Manages the raw HackRF One physical configuration and tuning registers."""
    def __init__(self, start_freq, rf_gain, if_gain, bb_gain, samp_rate):
        self.source = osmosdr.source(args="numchan=1 hackrf=0")
        self.source.set_sample_rate(samp_rate)
        self.source.set_center_freq(start_freq, 0)
        self.source.set_gain_mode(False, 0)
        self.source.set_gain(rf_gain, 0)
        self.source.set_if_gain(if_gain, 0)
        self.source.set_bb_gain(bb_gain, 0)

    def tune_frequency(self, target_frequency):
        self.source.set_center_freq(target_frequency, 0)
