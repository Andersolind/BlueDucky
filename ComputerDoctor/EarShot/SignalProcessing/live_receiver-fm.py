#!/usr/bin/env python3
import sys
from gnuradio import gr, filter, blocks, analog, audio
from gnuradio.filter import firdes
from gnuradio.fft import window  # <-- Fix 1: Import the window namespace directly
import osmosdr

class ClearVoiceReceiver(gr.top_block):
    def __init__(self, captured_freq_hz, audio_boost_factor=25.0):
        gr.top_block.__init__(self, "Clear Proximity Voice Demodulator")
        
        self.samp_rate = 2000000
        self.decimation = 80
        self.demod_rate = self.samp_rate // self.decimation # 25,000 Hz
        self.audio_rate = 48000
        
        # 1. Hardware Source 
        self.src = osmosdr.source(args="numchan=1 hackrf=0")
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(captured_freq_hz, 0)
        self.src.set_gain(12, 0)       
        self.src.set_if_gain(32, 0)    
        
        # 2. Narrowband Channel Selection Filter (Fix 2: Use window.WIN_HAMMING)
        taps = firdes.low_pass(1.0, self.samp_rate, 3500, 1000, window.WIN_HAMMING, 6.76)
        self.tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        
        # 3. Narrowband FM Quadrature Demodulator
        self.fm_demod = analog.quadrature_demod_cf(3.0) 
        
        # 4. High-Gain Pre-Amplifier Boost Stage
        self.preamp = blocks.multiply_const_ff(audio_boost_factor)
        
        # 5. Acoustic Cleanup Bandpass Filter (Fix 3: Use window.WIN_HAMMING)
        audio_taps = firdes.band_pass(1.0, self.demod_rate, 150, 3000, 100, window.WIN_HAMMING, 6.76)
        self.audio_filter = filter.fir_filter_fff(1, audio_taps)
        
        # 6. Rational Resampler
        self.resampler = filter.rational_resampler_fff(
            interpolation=48,
            decimation=25,
            taps=[],
            fractional_bw=0.4
        )
        
        # 7. Physical Audio Output Hardware Sink
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        
        # --- PIPELINE LINKING ---
        self.connect((self.src, 0), (self.tuner, 0))
        self.connect((self.tuner, 0), (self.fm_demod, 0))
        self.connect((self.fm_demod, 0), (self.preamp, 0))
        self.connect((self.preamp, 0), (self.audio_filter, 0))
        self.connect((self.audio_filter, 0), (self.resampler, 0))
        self.connect((self.resampler, 0), (self.audio_sink, 0))

if __name__ == '__main__':
    # Map back to the absolute 27.1200 MHz carrier confirmed by your scanner
    VERIFIED_FREQ = 27.1200e6 
    
    tb = ClearVoiceReceiver(captured_freq_hz=VERIFIED_FREQ, audio_boost_factor=25.0)
    print(f"[*] Locking onto verified center carrier at {VERIFIED_FREQ / 1e6:.4f} MHz...")
    print("[*] Demodulating clear room audio loop. Press Ctrl+C to exit.")
    
    try:
        tb.run()
    except KeyboardInterrupt:
        tb.stop()
        tb.wait()
        print("\n[*] Receiver pipeline cleanly deactivated.")
