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

class ScanningSDRDashboard(gr.top_block, QtWidgets.QWidget):
    def __init__(self, start_freq, rf_gain=14, if_gain=24, bb_gain=20):
        gr.top_block.__init__(self, "RF FM Audio Scanner Matrix")
        QtWidgets.QWidget.__init__(self)
        
        print("[*] Loading OpenAI Whisper Model ('tiny' engine)...")
        self.whisper_model = whisper.load_model("tiny")
        print("[+] Whisper Engine Active.")

        # Main Layout Setup
        self.setWindowTitle("RF FM Audio Scanner & Transcription Dashboard")
        self.resize(1280, 950)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)

        # Signal Rate Variables
        self.samp_rate = 2000000       # 2 MHz baseband capture
        self.decimation = 40 
        self.intermediate_rate = self.samp_rate // self.decimation  # 50,000 Hz
        self.audio_rate = 48000
        
        # Scanner Bounds Anchors
        self.target_base = start_freq
        self.current_freq = start_freq

        # ----------------------------------------------------------------
        # 1. HARDWARE CAPTURE SOURCE
        # ----------------------------------------------------------------
        self.osmosdr_source = osmosdr.source(args="numchan=1 hackrf=0")
        self.osmosdr_source.set_sample_rate(self.samp_rate)
        self.osmosdr_source.set_center_freq(self.current_freq, 0)
        self.osmosdr_source.set_gain(rf_gain, 0)
        self.osmosdr_source.set_if_gain(if_gain, 0)
        self.osmosdr_source.set_bb_gain(bb_gain, 0)
        
        # ----------------------------------------------------------------
        # 2. DIGITAL FM AUDIO TUNER PIPELINE
        # ----------------------------------------------------------------
        taps = firdes.low_pass(1.0, self.samp_rate, 12500, 5000, fft.window.WIN_HAMMING, 6.76)
        self.digital_tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        
        # FM Quadrature Demodulation Setup
        self.fm_demod = analog.quadrature_demod_cf(self.intermediate_rate / (2 * np.pi * 5000)) 
        
        # ----------------------------------------------------------------
        # 3. GRAPHICAL USER INTERFACE VISUALIZERS
        # ----------------------------------------------------------------
        self.qtgui_freq_sink = qtgui.freq_sink_f(
            1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.intermediate_rate,
            "Demodulated FM Baseband Spectrum", 1
        )
        self.qtgui_freq_sink.set_update_time(0.10)
        self.qtgui_freq_sink.set_y_axis(-140, 10)
        
        self.audio_sink_waterfall = qtgui.waterfall_sink_f(
            1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.audio_rate,
            "Audio Spectrogram - Voice Node Demodulation", 1
        )
        self.audio_sink_waterfall.set_update_time(0.10)
        self.audio_sink_waterfall.set_color_map(0, 3) 

        # Add UI Controls for Scanning
        self.scan_label = QtWidgets.QLabel(f"CURRENT TUNING TARGET: {self.current_freq / 1e6:.4f} MHz")
        self.scan_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #00ff00;")
        self.main_layout.addWidget(self.scan_label)

        self.rf_widget = sip.wrapinstance(self.qtgui_freq_sink.qwidget(), QtWidgets.QWidget)
        self.audio_widget = sip.wrapinstance(self.audio_sink_waterfall.qwidget(), QtWidgets.QWidget)
        self.main_layout.addWidget(self.rf_widget)
        self.main_layout.addWidget(self.audio_widget)

        self.text_display = QtWidgets.QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setFontPointSize(14)
        self.main_layout.addWidget(self.text_display)

        # ----------------------------------------------------------------
        # 4. FILTERING & DUAL AUDIO PATHWAYS
        # ----------------------------------------------------------------
        bp_taps = firdes.band_pass(1.0, self.intermediate_rate, 300, 3500, 400, fft.window.WIN_HAMMING, 6.76)
        self.voice_filter = filter.fir_filter_fff(1, bp_taps)
        
        # Audio Resampler (50kHz -> 48kHz for Speaker)
        self.audio_resampler = filter.rational_resampler_fff(
            interpolation=48, decimation=50, taps=[], fractional_bw=0.4
        )
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        
        # Whisper Resampler (50kHz -> 16kHz for AI Processing)
        self.whisper_resampler = filter.rational_resampler_fff(
            interpolation=16, decimation=50, taps=[], fractional_bw=0.4
        )
        self.audio_sink_vector = blocks.vector_sink_f(1)

        # ----------------------------------------------------------------
        # 5. MATRIX BLOCK CONNECTIONS
        # ----------------------------------------------------------------
        self.connect((self.osmosdr_source, 0), (self.digital_tuner, 0))
        self.connect((self.digital_tuner, 0), (self.fm_demod, 0))
        self.connect((self.fm_demod, 0), (self.voice_filter, 0))
        
        self.connect((self.voice_filter, 0), (self.qtgui_freq_sink, 0))
        self.connect((self.voice_filter, 0), (self.audio_resampler, 0))
        self.connect((self.audio_resampler, 0), (self.audio_sink, 0))
        self.connect((self.audio_resampler, 0), (self.audio_sink_waterfall, 0))
        
        self.connect((self.voice_filter, 0), (self.whisper_resampler, 0))
        self.connect((self.whisper_resampler, 0), (self.audio_sink_vector, 0))

        # ----------------------------------------------------------------
        # 6. ASYNCHRONOUS AUTOSCAN & AI PROCESSING THREAD
        # ----------------------------------------------------------------
        self.keep_running = True
        self.is_scanning = True
        self.step_size = 25000  # Jump by standard 25 kHz channel steps
        
        self.worker_thread = threading.Thread(target=self.scanner_and_whisper_worker)
        self.worker_thread.daemon = True
        self.worker_thread.start()

    def scanner_and_whisper_worker(self):
        """Scans frequencies until audio energy is detected, then transcribes."""
        print("[*] Autoscan and Whisper Processing Thread Active.")
        time.sleep(2) # Hardware safety sync window
        
        while self.keep_running:
            time.sleep(1.0) 
            
            raw_samples = self.audio_sink_vector.data()
            data_length = len(raw_samples)
            
            if data_length > 16000:
                audio_np = np.array(raw_samples, dtype=np.float32)
                self.audio_sink_vector.reset()
                
                rms_energy = np.sqrt(np.mean(audio_np**2))
                
                # SQUELCH SCAN CHECK TRACK
                if rms_energy < 0.08:  # Adjusted for noise floor variations
                    if self.is_scanning:
                        self.current_freq += self.step_size
                        
                        # Use local self boundary tracking to prevent crashes
                        if self.current_freq > (self.target_base + 1e6):
                            self.current_freq = self.target_base - 1e6
                            
                        self.osmosdr_source.set_center_freq(self.current_freq, 0)
                        
                        # FIXED: Closed the incomplete text update method call safely
                        QtCore.QMetaObject.invokeMethod(
                            self.scan_label, "setText", 
                            QtCore.Qt.QueuedConnection, 
                            QtCore.Q_ARG(str, f"SCANNING... CURRENT CHANNEL: {self.current_freq / 1e6:.4f} MHz")
                        )
                else:
                    # Signal lock engaged
                    if self.is_scanning:
                        print(f"[+] Active Audio Found at {self.current_freq / 1e6:.4f} MHz! Locking receiver.")
                        self.is_scanning = False
                        QtCore.QMetaObject.invokeMethod(
                            self.scan_label, "setText", 
                            QtCore.Qt.QueuedConnection, 
                            QtCore.Q_ARG(str, f"[LOCKED AUDIO CHANNEL]: {self.current_freq / 1e6:.4f} MHz")
                        )
                    
                    # Direct data link to OpenAI Whisper transcription loop
                    result = self.whisper_model.transcribe(audio_np, fp16=False)
                    parsed_string = result["text"].strip()
                    
                    if parsed_string:
                        QtCore.QMetaObject.invokeMethod(
                            self.text_display, "append", 
                            QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"[Transcribed]: {parsed_string}")
                        )
                    else:
                        # Unlock and continue scan if channel contains zero parsed speech data
                        self.is_scanning = True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Automated FM Audio Scanner & AI Matrix.")
    parser.add_argument("--freq", type=str, choices=["13", "27"], required=True, 
                        help="Select '13' for 13.56MHz or '27' for 27.12MHz sector scanning")
    args = parser.parse_args()
    
    freq_map = {"13": 13.56e6, "27": 27.12e6}
    selected_base_freq = freq_map[args.freq]
    
    qapp = QtWidgets.QApplication(sys.argv)
    
    print(f"[*] Booting FM Audio Search Loop centered around: {selected_base_freq / 1e6} MHz...")
    dashboard = ScanningSDRDashboard(start_freq=selected_base_freq)
    dashboard.show()
    
    dashboard.start()
