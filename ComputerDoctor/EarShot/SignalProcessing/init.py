#!/usr/bin/env python3
import sys
from gnuradio import gr, filter, blocks, analog
from gnuradio.filter import firdes
import osmosdr

class Local3ChannelCapture(gr.top_block):
    def __init__(self, room_center_freq, channel_spacing=25000):
        gr.top_block.__init__(self, "3-Channel Local Matrix Capture")
        
        self.samp_rate = 2000000 
        self.decimation = 80
        self.demod_rate = self.samp_rate // self.decimation  # 25,000 Hz
        
        # 1. Wideband Hardware Source
        self.src = osmosdr.source(args="numchan=1 hackrf=0")
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(room_center_freq, 0)
        self.src.set_gain(8, 0)       
        self.src.set_if_gain(30, 0)   
        
        # 2. Digital Impulse Blanker
        self.blanker = analog.noise_blanker_cc(threshold=1.2, beta=0.001, length=15)
        
        # Low pass filter taps shared by all channels
        taps = firdes.low_pass(1.0, self.samp_rate, 8000, 2000, firdes.WIN_HAMMING, 6.76)
        
        # 3. Channel A Tuner (Negative Offset / Left)
        self.tuner_a = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, -channel_spacing, self.samp_rate)
        # 4. Channel B Tuner (Center Frequency)
        self.tuner_b = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        # 5. Channel C Tuner (Positive Offset / Right)
        self.tuner_c = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, channel_spacing, self.samp_rate)
        
        # 6. Quadrature Demodulators
        self.fm_demod_a = analog.quadrature_demod_cf(1.5)
        self.fm_demod_b = analog.quadrature_demod_cf(1.5)
        self.fm_demod_c = analog.quadrature_demod_cf(1.5)
        
        # 7. Bandpass Cleanup Filters
        bp_taps = firdes.band_pass(1.0, self.demod_rate, 80, 4000, 100, firdes.WIN_HAMMING, 6.76)
        self.filter_a = filter.fir_filter_fff(1, bp_taps)
        self.filter_b = filter.fir_filter_fff(1, bp_taps)
        self.filter_c = filter.fir_filter_fff(1, bp_taps)
        
        # 8. File Sinks for Independent Recording
        self.sink_a = blocks.file_sink(gr.sizeof_float, "proximity_carrier_A.raw", False)
        self.sink_b = blocks.file_sink(gr.sizeof_float, "proximity_carrier_B.raw", False)
        self.sink_c = blocks.file_sink(gr.sizeof_float, "proximity_carrier_C.raw", False)
        
        # --- CONNECT THE RF CHANNELS ---
        self.connect((self.src, 0), (self.blanker, 0))
        
        # Path A Connection
        self.connect((self.blanker, 0), (self.tuner_a, 0))
        self.connect((self.tuner_a, 0), (self.fm_demod_a, 0))
        self.connect((self.fm_demod_a, 0), (self.filter_a, 0))
        self.connect((self.filter_a, 0), (self.sink_a, 0))
        
        # Path B Connection
        self.connect((self.blanker, 0), (self.tuner_b, 0))
        self.connect((self.tuner_b, 0), (self.fm_demod_b, 0))
        self.connect((self.fm_demod_b, 0), (self.filter_b, 0))
        self.connect((self.filter_b, 0), (self.sink_b, 0))
        
        # Path C Connection
        self.connect((self.blanker, 0), (self.tuner_c, 0))
        self.connect((self.tuner_c, 0), (self.fm_demod_c, 0))
        self.connect((self.fm_demod_c, 0), (self.filter_c, 0))
        self.connect((self.filter_c, 0), (self.sink_c, 0))

if __name__ == '__main__':
    center_mhz = float(input("Enter center frequency (MHz): "))
    spacing_hz = float(input("Enter channel spacing offset (Hz, e.g. 25000): ") or 25000)
    
    tb = Local3ChannelCapture(room_center_freq=center_mhz * 1e6, channel_spacing=spacing_hz)
    print(f"[*] Capturing a 3-channel matrix around {center_mhz} MHz...")
    try:
        tb.run()
    except KeyboardInterrupt:
        tb.stop()
        tb.wait()
        print("\n[*] 3-Channel capture complete. Files saved.")
