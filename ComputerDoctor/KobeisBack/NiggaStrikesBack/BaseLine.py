#!/usr/bin/env python3
import sys
from gnuradio import audio
from gnuradio import filter
from gnuradio import gr
from gnuradio import qtgui
from gnuradio import fft  
from gnuradio.filter import firdes
import osmosdr  
from gnuradio import analog
from PyQt5 import QtCore, QtWidgets
import sip  

class GnuRadioDashboard(gr.top_block, QtWidgets.QWidget):
    def __init__(self):
        gr.top_block.__init__(self, "RF Beamforming & VAD Dashboard")
        QtWidgets.QWidget.__init__(self)
        
        # Window setup
        self.setWindowTitle("RF & Acoustic Analysis Dashboard")
        self.resize(1280, 800)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        # Variables
        self.samp_rate = 2000000       # 2 MHz bandwidth to catch the signal mesh
        self.audio_rate = 48000        # Standard Linux audio output sample rate
        self.center_freq = 145000000   # Default starting frequency (145 MHz VHF)

        # ----------------------------------------------------------------
        # 1. HARDWARE SOURCE BLOCK (Handles Explicit USB Identifiers)
        # ----------------------------------------------------------------
        self.sdr_source = osmosdr.source(args="hackrf=0,numchan=1")
        self.sdr_source.set_sample_rate(self.samp_rate)
        self.sdr_source.set_center_freq(self.center_freq, 0)
        self.sdr_source.set_gain_mode(False, 0)
        
        # Optimized gain settings for HackRF front-end tracking
        self.sdr_source.set_gain(14, 0)      
        self.sdr_source.set_if_gain(24, 0)   
        self.sdr_source.set_bb_gain(20, 0)   

        # ----------------------------------------------------------------
        # 2. RF VISUALIZATION (Solomon Filter Matrix)
        # ----------------------------------------------------------------
        self.rf_sink = qtgui.freq_sink_c(
            1024, fft.window.WIN_BLACKMAN_HARRIS, self.center_freq, self.samp_rate,
            "RF Spectrum - Look for Flat Rectangular Filter Walls", 1
        )
        self.rf_sink.set_update_time(0.10)
        self.rf_sink.set_y_axis(-140, 10)
        
        self.rf_py_widget = sip.wrapinstance(self.rf_sink.qwidget(), QtWidgets.QWidget)
        self.layout.addWidget(self.rf_py_widget)

        # ----------------------------------------------------------------
        # 3. DSP PROCESSING LOOP (Demodulation & Audio Filter)
        # ----------------------------------------------------------------
        self.demod = analog.quadrature_demod_cf(1.0)
        
        self.audio_lpf = filter.fir_filter_fff(
            1, firdes.low_pass(1.0, self.samp_rate, 4000, 400)
        )
        
        self.resampler = filter.rational_resampler_fff(
            interpolation=self.audio_rate,
            decimation=int(self.samp_rate),
            taps=[]
        )

        # ----------------------------------------------------------------
        # 4. ACOUSTIC VISUALIZATION (VAD & Ghost Echo Track)
        # ----------------------------------------------------------------
        self.audio_sink_waterfall = qtgui.waterfall_sink_f(
            1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.audio_rate,
            "Audio Spectrogram - Track VAD Edges and Parallel Echo Lines", 1
        )
        self.audio_sink_waterfall.set_update_time(0.10)
        
        # Corrected: targeting stream index 0 with color map scheme 3
        self.audio_sink_waterfall.set_color_map(0, 3) 
        
        self.audio_py_widget = sip.wrapinstance(self.audio_sink_waterfall.qwidget(), QtWidgets.QWidget)
        self.layout.addWidget(self.audio_py_widget)

        # ----------------------------------------------------------------
        # 5. HARDWARE AUDIO SINK (To hear the audio live)
        # ----------------------------------------------------------------
        self.audio_output = audio.sink(self.audio_rate, "", True)

        # ----------------------------------------------------------------
        # CONNECTING THE DATA FLOW MATRIX
        # ----------------------------------------------------------------
        self.connect((self.sdr_source, 0), (self.rf_sink, 0))
        self.connect((self.sdr_source, 0), (self.demod, 0))
        self.connect((self.demod, 0), (self.audio_lpf, 0))
        self.connect((self.audio_lpf, 0), (self.resampler, 0))
        
        self.connect((self.resampler, 0), (self.audio_sink_waterfall, 0))
        self.connect((self.resampler, 0), (self.audio_output, 0))

if __name__ == '__main__':
    qapp = QtWidgets.QApplication(sys.argv)
    
    dashboard = GnuRadioDashboard()
    dashboard.show()
    dashboard.start()
    
    sys.exit(qapp.exec_())
