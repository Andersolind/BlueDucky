#!/usr/bin/env python3
import sys
import argparse
import threading
import time
import numpy as np
import whisper  # Real-time local speech-to-text

from gnuradio import audio, filter, gr, qtgui, fft, analog, blocks
from gnuradio.filter import firdes
import osmosdr  
from PyQt5 import QtCore, QtWidgets
import sip  

class CombinedSDRDashboard(gr.top_block, QtWidgets.QWidget):
    def __init__(self, target_freq, rf_gain=14, if_gain=24, bb_gain=20):
        gr.top_block.__init__(self, "RF Subvocal & VAD Whisper Analyzer")
        QtWidgets.QWidget.__init__(self)
        
        print("[*] Loading OpenAI Whisper Model ('tiny' engine)...")
        self.whisper_model = whisper.load_model("tiny")
        print("[+] Whisper Engine Active.")

        # Main Layout Setup
        self.setWindowTitle("Unified RF Matrix & AI Transcription Dashboard")
        self.resize(1280, 950)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)

        # Signal Rate Variables
        self.samp_rate = 2000000
        self.decimation = 40 
        self.intermediate_rate = self.samp_rate // self.decimation  # 50,000 Hz
        self.audio_rate = 48000
        self.whisper_rate = 16000  

        # 1. HARDWARE CAPTURE SOURCE
        self.osmosdr_source = osmosdr.source(args="numchan=1 hackrf=0")
        self.osmosdr_source.set_sample_rate(self.samp_rate)
        self.osmosdr_source.set_center_freq(target_freq, 0)
        self.osmosdr_source.set_gain(rf_gain, 0)
        self.osmosdr_source.set_if_gain(if_gain, 0)
        self.osmosdr_source.set_bb_gain(bb_gain, 0)
        
        # 2. DIGITAL AM ENVELOPE DETECTOR PIPELINE
        taps = firdes.low_pass(1.0, self.samp_rate, 20000, 10000, fft.window.WIN_HAMMING, 6.76)
        self.digital_tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        self.envelope_detector = blocks.complex_to_mag(1)
        
        # 3. GRAPHICAL USER INTERFACE VISUALIZERS
        self.qtgui_freq_sink = qtgui.freq_sink_f(
            1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.intermediate_rate,
            "Demodulated Baseband Spectrum", 1
        )
        self.qtgui_freq_sink.set_update_time(0.10)
        self.qtgui_freq_sink.set_y_axis(-140, 10)
        
        self.audio_sink_waterfall = qtgui.waterfall_sink_f(
            1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.audio_rate,
            "Audio Spectrogram - Track VAD Edges and Parallel Echo Lines", 1
        )
        self.audio_sink_waterfall.set_update_time(0.10)
        self.audio_sink_waterfall.set_color_map(0, 3) 

        self.rf_widget = sip.wrapinstance(self.qtgui_freq_sink.qwidget(), QtWidgets.QWidget)
        self.audio_widget = sip.wrapinstance(self.audio_sink_waterfall.qwidget(), QtWidgets.QWidget)
        
        self.main_layout.addWidget(self.rf_widget)
        self.main_layout.addWidget(self.audio_widget)

        # Bottom UI Component: Whisper Output Panel
        self.text_display = QtWidgets.QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setFontPointSize(14)
        self.main_layout.addWidget(self.text_display)

        # 4. FILTERING & DUAL AUDIO PATHWAYS
        bp_taps = firdes.band_pass(1.0, self.intermediate_rate, 60, 4000, 100, fft.window.WIN_HAMMING, 6.76)
        self.bone_conduction_filter = filter.fir_filter_fff(1, bp_taps)
        
        self.audio_resampler = filter.rational_resampler_fff(
            interpolation=48, decimation=50, taps=[], fractional_bw=0.4
        )
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        
        self.whisper_resampler = filter.rational_resampler_fff(
            interpolation=16, decimation=50, taps=[], fractional_bw=0.4
        )
        self.audio_sink_vector = blocks.vector_sink_f(1)

        # 5. MATRIX COUPLING & BLOCK CONNECTIONS
        self.connect((self.osmosdr_source, 0), (self.digital_tuner, 0))
        self.connect((self.digital_tuner, 0), (self.envelope_detector, 0))
        
        self.connect((self.envelope_detector, 0), (self.qtgui_freq_sink, 0))
        self.connect((self.envelope_detector, 0), (self.bone_conduction_filter, 0))
        
        self.connect((self.bone_conduction_filter, 0), (self.audio_resampler, 0))
        self.connect((self.audio_resampler, 0), (self.audio_sink, 0))
        self.connect((self.audio_resampler, 0), (self.audio_sink_waterfall, 0))
        
        self.connect((self.bone_conduction_filter, 0), (self.whisper_resampler, 0))
        self.connect((self.whisper_resampler, 0), (self.audio_sink_vector, 0))

        # 6. ASYNCHRONOUS WHISPER WORKER LAYER
        self.keep_running = True
        self.whisper_thread = threading.Thread(target=self.whisper_worker)
        self.whisper_thread.daemon = True
        self.whisper_thread.start()

    def whisper_worker(self):
        """Asynchronously processes voice segments based on software VAD metrics."""
        print("[*] Whisper Processing Engine Thread Active.")
        while self.keep_running:
            time.sleep(1.5) 
            
            raw_samples = self.audio_sink_vector.data()
            data_length = len(raw_samples)  # Safe native length mapping
            
            if data_length > 16000: 
                audio_np = np.array(raw_samples, dtype=np.float32)
                self.audio_sink_vector.reset()  # Flushes internal block index safely
                
                rms_energy = np.sqrt(np.mean(audio_np**2))
                
                if rms_energy > 0.015:
                    result = self.whisper_model.transcribe(audio_np, fp16=False)
                    parsed_string = result["text"].strip()
                    
                    if parsed_string:
                        QtCore.QMetaObject.invokeMethod(
                            self.text_display, "append", 
                            QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"[VAD Speak]: {parsed_string}")
                        )

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Demodulate, visually graph, and transcribe loop signals.")
    parser.add_argument("--freq", type=str, choices=["13", "27"], required=True, 
                        help="Select '13' for 13.56MHz or '27' for 27.12MHz tracking")
    args = parser.parse_args()
    
    freq_map = {"13": 13.56e6, "27": 27.12e6}
    selected_freq = freq_map[args.freq]
    
    qapp = QtWidgets.QApplication(sys.argv)
    
    print(f"[*] Dispatching Workspace Pipeline Matrix on target frequency: {selected_freq / 1e6} MHz...")
    dashboard = CombinedSDRDashboard(target_freq=selected_freq)
    dashboard.show()
    
    dashboard.start()
    sys.exit(qapp.exec_())
