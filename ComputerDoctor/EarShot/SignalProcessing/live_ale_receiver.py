#!/usr/bin/env python3
import sys
import threading
import math
import numpy as np
from PyQt5 import Qt
from gnuradio import gr, filter, blocks, analog, audio, qtgui
from gnuradio.filter import firdes
from gnuradio.fft import window
import osmosdr
import sip

from faster_whisper import WhisperModel

# Global buffers for the live thread handoff
audio_buffer_lock = threading.Lock()
transcription_queue = []

# ==============================================================================
# REAL-TIME ADAPTIVE LINE ENHANCER (LMS ALGORITHM)
# ==============================================================================
class AdaptiveLineEnhancer:
    def __init__(self, filter_order=48, mu=0.01, delay=4):
        """
        Tracks and cancels real-world masking tones arriving from 8 metres.
        filter_order (M): Number of adaptive filter taps.
        mu (mu): Convergence step size (tuned to handle 8m path attenuation).
        delay (Delta): Decorrelation delay to isolate speech from continuous tones.
        """
        self.M = filter_order
        self.mu = mu
        self.delay = delay
        self.weights = np.zeros(self.M, dtype=np.float32)
        self.buffer = np.zeros(self.M + self.delay, dtype=np.float32)

    def process_block(self, input_signal):
        """
        Processes real hardware blocks, tracking and nulling the active masking tone.
        """
        output_clean = np.zeros_like(input_signal)
        for idx in range(len(input_signal)):
            x_n = input_signal[idx]
            
            # Shift buffer
            self.buffer = np.roll(self.buffer, 1)
            self.buffer[0] = x_n
            
            # Extract delayed reference vector
            x_vector = self.buffer[self.delay : self.delay + self.M]
            
            # Predict the highly correlated masking tone
            y_n = np.dot(self.weights, x_vector)
            
            # Subtract predicted mask to isolate the proximity voice print
            e_n = x_n - y_n
            output_clean[idx] = e_n
            
            # Standard LMS Recursion update
            self.weights += 2.0 * self.mu * e_n * x_vector
            
        return output_clean

# ==============================================================================
# HARDWARE CAPTURE FLOWGRAPH
# ==============================================================================
class ClearVoiceReceiver(gr.top_block):
    def __init__(self, captured_freq_hz, audio_boost_factor=25.0):
        gr.top_block.__init__(self, "Clear Proximity Voice Demodulator")
        
        self.samp_rate = 2000000
        self.decimation = 80
        self.demod_rate = self.samp_rate // self.decimation # 25,000 Hz
        self.audio_rate = 48000
        
        # 1. Hardware Source - Configured for 1-2m proximity focus
        self.src = osmosdr.source(args="numchan=1 hackrf=0")
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(captured_freq_hz, 0)
        self.src.set_gain(0, 0)        # Keeps the local loop stable
        self.src.set_if_gain(16, 0)    
        
        # 2. Narrowband Channel Selection Filter
        taps = firdes.low_pass(1.0, self.samp_rate, 3500, 1000, window.WIN_HAMMING, 6.76)
        self.tuner = filter.freq_xlating_fir_filter_ccc(self.decimation, taps, 0, self.samp_rate)
        
        # 3. AM Demodulator (Magnitude Envelope Detector)
        self.am_demod = blocks.complex_to_mag(1)
        
        # 4. Automatic Gain Control (AGC) - Stabilizes incoming signal fluctuations
        self.agc = analog.agc_ff(rate=1e-4, reference=1.0, gain=1.0, max_gain=4000.0)
        
        # 5. Pre-Amplifier Boost Stage
        self.preamp = blocks.multiply_const_ff(audio_boost_factor)
        
        # 6. Acoustic Cleanup Bandpass Filter 
        audio_taps = firdes.band_pass(1.0, self.demod_rate, 150, 3000, 100, window.WIN_HAMMING, 6.76)
        self.audio_filter = filter.fir_filter_fff(1, audio_taps)
        
        # 7. Live Visual Oscilloscope (QT GUI Time Sink)
        self.qtgui_time_sink = qtgui.time_sink_f(
            1024, self.demod_rate, "Live Waveform Scope", 1
        )
        self.qtgui_time_sink.set_y_axis(-2, 2)
        self.qtgui_time_sink.set_update_time(0.05) 
        
        # Explicit SIP Pointer Wrapping for PyQt window container UI
        self.pyqt_container = sip.wrapinstance(self.qtgui_time_sink.qwidget(), Qt.QWidget)
        self.pyqt_container.setMinimumSize(800, 350)
        self.pyqt_container.setWindowTitle("Adaptive Carrier Oscillation Scope")
        self.pyqt_container.show()
        
        # 8. Audio Resampler to match Whisper Model (25 kHz -> 16 kHz)
        self.whisper_resampler = filter.rational_resampler_fff(
            interpolation=16, decimation=25, taps=[], fractional_bw=0.4
        )
        self.whisper_sink = blocks.vector_sink_f(1)
        
        # 9. Hardware Speaker Output path
        self.resampler = filter.rational_resampler_fff(48, 25, [], 0.4)
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        
        # --- PIPELINE ROUTING ---
        self.connect((self.src, 0), (self.tuner, 0))
        self.connect((self.tuner, 0), (self.am_demod, 0))
        self.connect((self.am_demod, 0), (self.agc, 0))
        self.connect((self.agc, 0), (self.preamp, 0))
        self.connect((self.preamp, 0), (self.audio_filter, 0))
        
        # Forking distribution paths
        self.connect((self.audio_filter, 0), (self.qtgui_time_sink, 0))
        self.connect((self.audio_filter, 0), (self.resampler, 0))
        self.connect((self.resampler, 0), (self.audio_sink, 0))
        
        # Connect to the AI vector capture buffer
        self.connect((self.audio_filter, 0), (self.whisper_resampler, 0))
        self.connect((self.whisper_resampler, 0), (self.whisper_sink, 0))

    def collect_ai_samples(self):
        try:
            data = self.whisper_sink.data()
            if len(data) > 0:
                global transcription_queue
                with audio_buffer_lock:
                    transcription_queue.extend(data)
                self.whisper_sink.clear()
        except Exception:
            pass

# ==============================================================================
# BACKGROUND TRANSCRIBER & LIVE ADAPTIVE FILTER THREAD
# ==============================================================================
def whisper_transcription_worker():
    print("[*] Initializing Local Faster-Whisper Transformer Core (CPU)...")
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    
    # Instantiate our Adaptive Line Enhancer directly inside the transcription engine
    # Setting an active learning rate to continuously counter the 8m distant mask
    ale = AdaptiveLineEnhancer(filter_order=48, mu=0.01, delay=4)
    print("[+] AI Engine & Adaptive Enhancer ready. Monitoring proximity zone...")
    
    global transcription_queue
    accumulated_chunk = []
    sample_rate = 16000
    required_samples = int(sample_rate * 2.0) # 2-second segments
    
    while True:
        import time
        time.sleep(0.5) 
        
        with audio_buffer_lock:
            if len(transcription_queue) > 0:
                accumulated_chunk.extend(transcription_queue)
                transcription_queue.clear()
                
        if len(accumulated_chunk) >= required_samples:
            raw_segment = np.array(accumulated_chunk[:required_samples], dtype=np.float32)
            accumulated_chunk = accumulated_chunk[required_samples:]
            
            # RUN REAL-TIME ADAPTIVE FILTERING FIRST:
            # This strips the live 8m high-pitch masking tone out of the hardware block
            cleaned_segment = ale.process_block(raw_segment)
            
            # Run VAD validation on the cleaned audio stream
            rms_energy = np.sqrt(np.mean(cleaned_segment**2))
            
            if rms_energy > 0.02: 
                segments, info = model.transcribe(
                    cleaned_segment, 
                    beam_size=3,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=300)
                )
                
                for segment in segments:
                    if len(segment.text.strip()) > 0:
                        print(f"\r[TRANSCRIPT] {segment.text}", flush=True)

# ==============================================================================
# RUNTIME LAYOUT ENTRY POINT
# ==============================================================================
if __name__ == '__main__':
    VERIFIED_FREQ = 27.1200e6 
    qapp = Qt.QApplication(sys.argv)
    
    tb = ClearVoiceReceiver(captured_freq_hz=VERIFIED_FREQ, audio_boost_factor=30.0)
    print(f"[*] Locking hardware matrix onto verified carrier...")
    
    ai_thread = threading.Thread(target=whisper_transcription_worker, daemon=True)
    ai_thread.start()
    
    tb.start()
    
    timer = Qt.QTimer()
    timer.timeout.connect(tb.collect_ai_samples)
    timer.start(200) 
    
    sys.exit(qapp.exec_())
