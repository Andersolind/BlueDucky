#!/usr/bin/env python3
import sys
import argparse
from PyQt5 import Qt
from gnuradio import analog
from gnuradio import audio
from gnuradio import blocks
from gnuradio import filter
from gnuradio import gr
from gnuradio import qtgui
from gnuradio.filter import firdes, window
import osmosdr

# Inherit from gr.top_block but structure it to work inside a Qt Application
class RF_GUI_Demodulator(gr.top_block):
    def __init__(self, target_freq, rf_gain=0, if_gain=32, bb_gain=32):
        gr.top_block.__init__(self, "RF Subvocal Signal Analyzer")
        
        self.samp_rate = 2000000
        self.audio_rate = 48000
        self.decimation = 40 
        self.intermediate_rate = self.samp_rate // self.decimation # 50,000 Hz
        
        # --- Hardware Source ---
        self.osmosdr_source = osmosdr.source(args="numchan=1 hackrf=0")
        self.osmosdr_source.set_sample_rate(self.samp_rate)
        self.osmosdr_source.set_center_freq(target_freq, 0)
        self.osmosdr_source.set_gain(rf_gain, 0)
        self.osmosdr_source.set_if_gain(if_gain, 0)
        self.osmosdr_source.set_bb_gain(bb_gain, 0)
        
        # --- Digital Tuner ---
        taps = firdes.low_pass(1.0, self.samp_rate, 20000, 10000, window.WIN_HAMMING, 6.76)
        self.digital_tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        
        # --- Envelope Detector ---
        self.envelope_detector = blocks.complex_to_mag(1)
        
        # --- Live Visual Spectrum Sink (FFT) ---
        # This creates a GUI window displaying frequencies from 0 to 25 kHz (Nyquist for 50 kHz)
        self.qtgui_freq_sink = qtgui.freq_sink_f(
            1024,                      # FFT Size
            window.WIN_BLACKMAN_HARRIS,# Window Type
            0,                         # Center Frequency
            self.intermediate_rate,    # Sample Rate of the incoming stream
            "Demodulated Baseband Spectrum", # Window Title
            1                          # Number of Inputs
        )
        self.qtgui_freq_sink.set_update_time(0.10)
        self.qtgui_freq_sink.set_y_axis(-140, 10)
        
        # Wrap the GUI widget so PyQt can render it
        self.pyqt_widget = Qt.QWidget.createWindowContainer(
            Qt.QWindow.fromWinId(self.qtgui_freq_sink.qwidget())
        )
        self.pyqt_widget.setMinimumSize(800, 600)
        self.pyqt_widget.setWindowTitle("Live Muscle Frequency Monitor")
        self.pyqt_widget.show()
        
        # --- Filtering & Audio Path ---
        # Tuned to focus on 60 Hz to 4,000 Hz where throat friction and voice data reside
        bp_taps = firdes.band_pass(1.0, self.intermediate_rate, 60, 4000, 100, window.WIN_HAMMING, 6.76)
        self.bone_conduction_filter = filter.fir_filter_fff(1, bp_taps)
        
        # Audio Resampler (50,000 Hz -> 48,000 Hz)
        self.audio_resampler = filter.rational_resampler_fff(
            interpolation=48,
            decimation=50,
            taps=[],
            fractional_bw=0.4
        )
        
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        
        # --- Connections ---
        # Source to Tuner to Envelope Detector
        self.connect((self.osmosdr_source, 0), (self.digital_tuner, 0))
        self.connect((self.digital_tuner, 0), (self.envelope_detector, 0))
        
        # Fork the signal: one path goes to the visual GUI, the other goes to the speaker
        self.connect((self.envelope_detector, 0), (self.qtgui_freq_sink, 0))
        
        # Audio processing path
        self.connect((self.envelope_detector, 0), (self.bone_conduction_filter, 0))
        self.connect((self.bone_conduction_filter, 0), (self.audio_resampler, 0))
        self.connect((self.audio_resampler, 0), (self.audio_sink, 0))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Demodulate and visually graph loop signals.")
    parser.add_argument("--freq", type=str, choices=["13", "27"], required=True, help="Select '13' for 13.56MHz or '27' for 27.12MHz")
    args = parser.parse_args()
    
    freq_map = {"13": 13.56e6, "27": 27.12e6}
    selected_freq = freq_map[args.freq]
    
    # Initialize the mandatory Qt Application framework
    qapp = Qt.QApplication(sys.argv)
    
    print(f"[*] Starting GUI pipeline on {selected_freq / 1e6} MHz...")
    tb = RF_GUI_Demodulator(target_freq=selected_freq)
    
    # Start the GNU Radio processing blocks
    tb.start()
    
    # Hand execution control over to the Qt window loop instance
    sys.exit(qapp.exec_())
