import sys
from gnuradio import gr, filter, blocks, analog, qtgui, fft
from gnuradio.filter import firdes
import osmosdr
from PyQt5 import QtWidgets, QtCore
import sip # Required to wrap internal C++ GUI pointers safely for PyQt5

class VisualFMModulationDetector(gr.top_block, QtWidgets.QWidget):
    def __init__(self, target_freq=13.56e6):
        gr.top_block.__init__(self, "FM Modulation Detector")
        QtWidgets.QWidget.__init__(self)
        
        # ----------------------------------------------------------------
        # SYSTEM WINDOW LAYOUT SETUP
        # ----------------------------------------------------------------
        self.setWindowTitle("Live Room Modulation & Microphonics Monitor")
        self.resize(1000, 750)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        
        # Operational parameters
        self.samp_rate = 2000000
        self.decimation = 40
        self.demod_rate = self.samp_rate // self.decimation # 50,000 Hz
        
        # 1. Hardware Source (HackRF)
        self.src = osmosdr.source(args="numchan=1 hackrf=0")
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(target_freq, 0)
        self.src.set_gain_mode(False, 0)
        self.src.set_gain(14, 0) 
        self.src.set_if_gain(32, 0)
        self.src.set_bb_gain(20, 0)
        
        # 2. Digital Tuner (Isolate the carrier core)
        taps = firdes.low_pass(1.0, self.samp_rate, 15000, 5000, fft.window.WIN_HAMMING, 6.76)
        self.tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        
        # 3. FM Quadrature Demodulator
        self.fm_demod = analog.quadrature_demod_cf(1.5)
        
        # 4. Bandpass Filter (Isolate voice/vibration frequencies: 60Hz to 4000Hz)
        bp_taps = firdes.band_pass(1.0, self.demod_rate, 60, 4000, 100, fft.window.WIN_HAMMING, 6.76)
        self.vibration_filter = filter.fir_filter_fff(1, bp_taps)
        
        # ----------------------------------------------------------------
        # VISUAL GUIDE CHANNELS (O-Scope & Audio Spectrogram)
        # ----------------------------------------------------------------
        # Graphical Sink A: Time Domain (Oscilloscope grid to track transient room clicks)
        self.gui_time_sink = qtgui.time_sink_f(
            1024,                  # Buffer frame size
            self.demod_rate,       # Matches filtered stream speed
            "Demodulated Microphonic Waveform (Time Domain)", # Title
            1                      # Inputs
        )
        self.gui_time_sink.set_update_time(0.05)
        self.gui_time_sink.set_y_axis(-1.0, 1.0)
        
        # Graphical Sink B: Frequency Domain (Spectrum analyzer to trace carrier sidebands)
        self.gui_freq_sink = qtgui.freq_sink_f(
            1024,                  # FFT Parameter window block size
            fft.window.WIN_BLACKMAN_HARRIS,
            0,                     # Relative Center Freq
            self.demod_rate,       # Sample speed
            "Demodulated Baseband Acoustic Resonance (Frequency Domain)", # Title
            1
        )
        self.gui_freq_sink.set_update_time(0.05)
        self.gui_freq_sink.set_y_axis(-140, 10)
        
        # Wrap C++ GUI pointers into PyQt5 widgets using SIP to prevent syntax crashes
        self.time_widget = sip.wrapinstance(self.gui_time_sink.qwidget(), QtWidgets.QWidget)
        self.freq_widget = sip.wrapinstance(self.gui_freq_sink.qwidget(), QtWidgets.QWidget)
        
        # Mount the visual grids onto the window layout canvas
        self.layout.addWidget(self.time_widget)
        self.layout.addWidget(self.freq_widget)
        
        # 5. File Sink (Logs raw audio data continuously)
        self.file_sink = blocks.file_sink(gr.sizeof_float, "captured_room_modulation.raw", False)
        self.file_sink.set_unbuffered(False)
        
        # ----------------------------------------------------------------
        # COUPLING STRATEGY CONNECTIONS
        # ----------------------------------------------------------------
        self.connect((self.src, 0), (self.tuner, 0))
        self.connect((self.tuner, 0), (self.fm_demod, 0))
        self.connect((self.fm_demod, 0), (self.vibration_filter, 0))
        
        # Fork the final filtered stream out into the logging file and both visual monitors
        self.connect((self.vibration_filter, 0), (self.file_sink, 0))
        self.connect((self.vibration_filter, 0), (self.gui_time_sink, 0))
        self.connect((self.vibration_filter, 0), (self.gui_freq_sink, 0))

if __name__ == '__main__':
    # Initialize the mandatory graphical environment engine
    qapp = QtWidgets.QApplication(sys.argv)
    
    print("[*] Launching Visual Guide Monitor Matrix... Target: 13.56 MHz")
    tb = VisualFMModulationDetector()
    tb.show()
    
    # Run the hardware background processing workers
    tb.start()
    
    # Hand over execution loop controls to the active Qt Window frame context
    sys.exit(qapp.exec_())
