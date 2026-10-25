#!/usr/bin/env python3
import threading, time, queue, os, csv
import numpy as np
import whisper
import soundfile as sf  
from gnuradio import audio, filter, gr, qtgui, fft, analog, blocks
from gnuradio.filter import firdes
import osmosdr

# Explicitly import modular structural sub-services
from hw_service import SDRHardwareService
from dsp_service import DigitalDSPPipelineService
from analysis_service import MetricAnalysisService
from ctc_service import AcousticCTCDemixService

class SDRScannerEngine(gr.top_block):
    """Orchestrates structural services, block attachments, and execution threads."""
    def __init__(self, start_freq, rf_gain=14, if_gain=24, bb_gain=20, ui_callback=None, text_callback=None, bpm_callback=None, alert_callback=None):
        gr.top_block.__init__(self, "RF Service Orchestrator with Alert Layer")
        
        self.ui_callback = ui_callback
        self.text_callback = text_callback
        self.bpm_callback = bpm_callback
        self.alert_callback = alert_callback # Cross-connection alert portal
        
        print("[*] Loading Whisper Translation Model...")
        self.whisper_model = whisper.load_model("tiny")
        
        # System Constants
        self.samp_rate = 2000000
        self.decimation = 40
        self.intermediate_rate = 50000
        self.audio_rate = 48000
        self.target_base = start_freq
        self.current_freq = start_freq
        self.step_size = 5000
        
        self.is_scanning = True
        self.manual_listen_mode = False
        self.keep_running = True
        self.db_file = "signal_ml_database.csv"
        self.dsp_queue = queue.Queue(maxsize=10)

        # Initialize Sub-Services
        self.hw = SDRHardwareService(start_freq, rf_gain, if_gain, bb_gain, self.samp_rate)
        self.dsp = DigitalDSPPipelineService(self.samp_rate, self.decimation, self.intermediate_rate)
        self.metrics = MetricAnalysisService()
        self.ctc = AcousticCTCDemixService()

        # GUI Visualizer Sinks
        self.qtgui_freq_sink = qtgui.freq_sink_f(1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.intermediate_rate, "Spectrum", 1)
        self.audio_sink_waterfall = qtgui.waterfall_sink_f(1024, fft.window.WIN_BLACKMAN_HARRIS, 0, self.audio_rate, "Waterfall", 1)
        self.qtgui_freq_sink.set_update_time(0.10)
        self.audio_sink_waterfall.set_update_time(0.10)
        self.audio_sink_waterfall.set_color_map(0, 3)

        # IO Sinks
        self.audio_sink = audio.sink(self.audio_rate, "", True)
        self.audio_sink_vector = blocks.vector_sink_f(1)

        # Structural Coupling Matrices
        self.connect((self.hw.source, 0), (self.dsp.digital_tuner, 0))
        self.connect((self.dsp.digital_tuner, 0), (self.dsp.fm_demod, 0))
        self.connect((self.dsp.fm_demod, 0), (self.dsp.voice_filter, 0))
        self.connect((self.dsp.voice_filter, 0), (self.qtgui_freq_sink, 0))
        self.connect((self.dsp.voice_filter, 0), (self.dsp.audio_resampler, 0))
        self.connect((self.dsp.audio_resampler, 0), (self.audio_sink, 0))
        self.connect((self.dsp.audio_resampler, 0), (self.audio_sink_waterfall, 0))
        self.connect((self.dsp.voice_filter, 0), (self.dsp.whisper_resampler, 0))
        self.connect((self.dsp.whisper_resampler, 0), (self.audio_sink_vector, 0))

        # Launch background loops
        threading.Thread(target=self.primary_buffer_harvester, daemon=True).start()
        threading.Thread(target=self.async_metric_processor, daemon=True).start()

    def toggle_manual_listen(self):
        self.manual_listen_mode = not self.manual_listen_mode
        self.is_scanning = not self.manual_listen_mode
        return self.manual_listen_mode

    def primary_buffer_harvester(self):
        time.sleep(2.5)
        calibration_runs = []
        while len(calibration_runs) < 3:
            time.sleep(1.0)
            raw = self.audio_sink_vector.data()
            self.audio_sink_vector.reset()
            if len(raw) > 16000:
                calibration_runs.append(np.sqrt(np.mean(np.array(raw, dtype=np.float32)**2)))
        
        self.metrics.threshold = (sum(calibration_runs) / len(calibration_runs)) * 1.50
        print(f"[+] Calibration complete. Base threshold locked: {self.metrics.threshold:.4f}")
        
        while self.keep_running:
            time.sleep(1.0)
            raw = self.audio_sink_vector.data()
            if len(raw) > 12000:
                audio_np = np.array(raw, dtype=np.float32)
                self.audio_sink_vector.reset()
                try: self.dsp_queue.put_nowait((audio_np, len(raw)))
                except queue.Full: pass

    def async_metric_processor(self):
        while self.keep_running:
            try: audio_np, data_length = self.dsp_queue.get(timeout=1.0)
            except queue.Empty: continue
                
            # Unmix phase inversion envelopes using auto-tuning CTC matrix
            clean_left, clean_right, computed_dist = self.ctc.process_demix_matrix(audio_np)
            
            rms_l = np.sqrt(np.mean(clean_left**2))
            rms_r = np.sqrt(np.mean(clean_right**2))
            target_path = clean_left if rms_l > rms_r else clean_right
            rms = max(rms_l, rms_r)
            
            self.metrics.historical_envelopes.append(rms)
            if len(self.metrics.historical_envelopes) > 60: self.metrics.historical_envelopes.pop(0)

            beat_lock, bpm_out = self.metrics.analyze_rhythm_cadence()
            if beat_lock and self.bpm_callback: self.bpm_callback(bpm_out)
            
            vad_active = rms >= self.metrics.threshold
            motion_flag = self.metrics.analyze_motion_anomaly(data_length, vad_active)
            loop_flag, delay_ms = self.metrics.analyze_beam_cross_loop(target_path)
            
            self.metrics.last_frame = target_path

            # --- FREY OVER-STIMULATION ALERT RADAR ---
            # Triggers if power spikes past 3x baseline while rhythm sync is active
            if rms > (self.metrics.threshold * 3.0) and beat_lock:
                if self.alert_callback:
                    # Instantly fire safety vectors to the graphical layout thread
                    self.alert_callback(self.current_freq / 1e6, computed_dist, bpm_out, rms)

            if vad_active or beat_lock or loop_flag or motion_flag:
                self.is_scanning = False 
                msg = f"[{time.strftime('%H:%M:%S')}] ---> TARGET LOCK INITIALIZED ON {self.current_freq / 1e6:.4f} MHz <---\n"
                msg += f" -> [PERIMETER GEOMETRY]: Estimated spatial loop distance: {computed_dist:.2f} metres.\n"
                if beat_lock: msg += f" -> [BEAT ENTRAPMENT]: Locked rhythm cadence at {bpm_out:.1f} BPM.\n"
                if motion_flag: msg += " -> [VAD MOTION DETECTED]: Instant deviation in path tracking footprint.\n"
                if loop_flag: msg += f" -> [CROSS BEAM LOOP]: Phase delay convergence mapped at {delay_ms:.1f} ms.\n"
                if self.text_callback: self.text_callback(msg)
                
                result = self.whisper_model.transcribe(target_path, fp16=False, temperature=0.0)
                parsed = result["text"].strip()
                
                if parsed and self.text_callback: self.text_callback(f" -> [Audio Payload]: {parsed}\n")
                elif self.text_callback: self.text_callback(" -> [Audio Payload]: [Demodulated Spatial Pulse Encounter]\n")
                
                sf.write(f"event_{int(time.time())}.wav", target_path, 16000)
                
                # Write features directly to the database writer line
                f_exists = os.path.isfile(self.db_file)
                with open(self.db_file, mode='a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    if not f_exists:
                        writer.writerow(["Timestamp", "Frequency_MHz", "Calculated_Distance_m", "Phase_Delay_ms", "Cadence_BPM", "Signal_RMS", "Payload_Text"])
                    writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), self.current_freq / 1e6, round(computed_dist, 3), delay_ms, bpm_out, rms, parsed if parsed else "[Pulse Input]"])
            else:
                if self.manual_listen_mode:
                    self.is_scanning = False
                    if self.ui_callback: self.ui_callback(f"!!! [MANUAL LISTEN PINNED]: MONITORING {self.current_freq / 1e6:.4f} MHz !!!")
                else:
                    self.is_scanning = True
                    self.current_freq += self.step_size
                    if self.current_freq > (self.target_base + 1000000): self.current_freq = self.target_base - 1000000
                    self.hw.tune_frequency(self.current_freq)
                    if self.ui_callback: self.ui_callback(f"SCANNING SPACE (Squelch: {self.metrics.threshold:.3f})... TARGET: {self.current_freq / 1e6:.4f} MHz")
            
            self.dsp_queue.task_done()
