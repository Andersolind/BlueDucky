#!/usr/bin/env python3
import sys
from PyQt5 import Qt
from gnuradio import gr, filter, blocks, analog, audio, qtgui
from gnuradio.filter import firdes
from gnuradio.fft import window
import osmosdr
import sip

class ClearVoiceReceiver(gr.top_block):
    def __init__(self, captured_freq_hz, audio_boost_factor=25.0):
        gr.top_block.__init__(self, "Clear Proximity Voice Demodulator")
        
        self.samp_rate = 2000000
        self.decimation = 80
        self.demod_rate = self.samp_rate // self.decimation # 25,000 Hz
        self.audio_rate = 48000
        
        # 1. Hardware Source - Attenuated Gains for Extreme Close-Range Proximity
        self.src = osmosdr.source(args="numchan=1 hackrf=0")
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(captured_freq_hz, 0)
        self.src.set_gain(0, 0)        # Minimized to avoid clipping near the loop antenna
        self.src.set_if_gain(16, 0)    # Attenuated intermediate amplification
        
        # 2. Narrowband Channel Selection Filter
        taps = firdes.low_pass(1.0, self.samp_rate, 3500, 1000, window.WIN_HAMMING, 6.76)
        self.tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        
        # 3. AM Demodulator (Magnitude Envelope Detector to pull audio from power ripples)
        self.am_demod = blocks.complex_to_mag(1)
        
        # 4. Automatic Gain Control (AGC) - Smooths out proximity audio surges
        self.agc = analog.agc_ff(
            rate=1e-4,        # Adaptation rate to physical spatial changes
            reference=1.0,    # Target output normalized amplitude level
            gain=1.0,         # Initial baseline gain level
            max_gain=4000.0   # Cap maximum noise floor amplification
        )
        
        # 5. Pre-Amplifier Boost Stage
        self.preamp = blocks.multiply_const_ff(audio_boost_factor)
        
        # 6. Acoustic Cleanup Bandpass Filter 
        audio_taps = firdes.band_pass(1.0, self.demod_rate, 150, 3000, 100, window.WIN_HAMMING, 6.76)
        self.audio_filter = filter.fir_filter_fff(1, audio_taps)
        
        # 7. Live Visual Oscilloscope (QT GUI Time Sink)
        self.qtgui_time_sink = qtgui.time_sink_f(
            1024,                  # Signal buffer size per frame window
            self.demod_rate,       # Sample timeline scale based on 25kHz stream
            "Live Waveform Scope", # Display Window Title
            1                      # Number of active input channels
        )
        self.qtgui_time_sink.set_y_axis(-2, 2)
        self.qtgui_time_sink.set_update_time(0.05) # Refresh layout viewport every 50ms
        
        # Safely wrap the internal C++ widget into a Python QWidget layout
        # self.pyqt_container = sip.wrapinstance(self.qtgui_time_sink.pyqwidget(), Qt.QWidget)
        self.pyqt_container = sip.wrapinstance(self.qtgui_time_sink.qwidget(), Qt.QWidget)
        self.pyqt_container.setMinimumSize(800, 400)
        self.pyqt_container.setWindowTitle("Acoustic Vibration Oscilloscope Matrix")
        self.pyqt_container.show()
        
        # 8. Rational Resampler (Translates internal 25 kHz stream to standard audio hardware)
        self.resampler = filter.rational_resampler_fff(
            interpolation=48,
            decimation=25,
            taps=[],
            fractional_bw=0.4
        )
        
        # 9. Physical Audio Output Hardware Sink
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        
        # --- PIPELINE CONTEXT LINKING ---
        self.connect((self.src, 0), (self.tuner, 0))
        self.connect((self.tuner, 0), (self.am_demod, 0))
        self.connect((self.am_demod, 0), (self.agc, 0))
        self.connect((self.agc, 0), (self.preamp, 0))
        self.connect((self.preamp, 0), (self.audio_filter, 0))
        
        # FORK SIGNAL ENVELOPE:
        # Path A -> Real-time display screen rendering
        self.connect((self.audio_filter, 0), (self.qtgui_time_sink, 0))
        
        # Path B -> Final downsampled audio output delivery
        self.connect((self.audio_filter, 0), (self.resampler, 0))
        self.connect((self.resampler, 0), (self.audio_sink, 0))

if __name__ == '__main__':
    # Map back to the absolute 27.1200 MHz carrier confirmed by your scanner script
    VERIFIED_FREQ = 27.1200e6 
    
    # Instantiate the mandatory graphical framework application environment
    qapp = Qt.QApplication(sys.argv)
    
    tb = ClearVoiceReceiver(captured_freq_hz=VERIFIED_FREQ, audio_boost_factor=25.0)
    print(f"[*] Locking onto verified AM center carrier at {VERIFIED_FREQ / 1e6:.4f} MHz...")
    print("[*] Launching graphical dashboard workspace layout...")
    
    # Start the background GNU Radio digital signal processing engines
    tb.start()
    
    # Hand execution control over to the visible PyQt window thread lifecycle
    sys.exit(qapp.exec_())
