import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from rtlsdr import RtlSdr
import threading
import sys
import time
import wave
import struct
import math
import scipy.signal as signal
import whisper
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

class AutonomousSignalStation:
    def __init__(self, target_freq=98.1e6, sample_rate=2.4e6, fft_size=1024):
        self.target_freq = target_freq
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.is_running = False
        
        # Audio Engine Parameters
        self.audio_rate = 44100
        self.decimation_factor = int(self.sample_rate / self.audio_rate)
        self.is_recording = False
        self.wav_file = None
        self.current_filename = None
        self.last_burst_time = 0
        self.hold_time_seconds = 1.5 
        
        # Adaptive Squelch parameters
        self.noise_floor_variance = 0.002  
        self.alpha_adaptation = 0.05       
        self.trigger_sensitivity = 2.5     

        # --- UPDATE: SPATIAL VECTORS & LOCAL POSITION TRACKING ---
        self.base_lat, self.base_lon = 43.5183, -79.8774   # Milton Base Station Origin
        self.my_lat, self.my_lon = 43.491826, -79.835807   # Your Exact Location Coordinates
        self.doa_bearing = self.calculate_direction_of_arrival()

        # --- UPDATE: UPGRADED WHISPER "BASE" MODEL LAYER ---
        print("[*] Instantiating high-fidelity OpenAI Whisper 'base' language profile...")
        self.whisper_model = whisper.load_model("base")
        print("[+] AI engine stabilized. Standby for over-the-air capture.")
        
        # Voice-Isolating Bandpass FIR Matrix (300 Hz - 3400 Hz)
        self.bandpass_coeffs = signal.firwin(101, [300.0/22050.0, 3400.0/22050.0], pass_zero='bandpass')
        self.filter_state = signal.lfilter_zi(self.bandpass_coeffs, 1.0)

        # UI Canvas Configurations
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.fig.canvas.manager.set_window_title("Autonomous AI Signal Monitoring Terminal")

        print("[*] Connecting to RTL-SDR hardware interface...")
        try:
            self.sdr = RtlSdr(device_index=0)
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = self.target_freq
            self.sdr.gain = 'auto'
        except Exception as e:
            print(f"[!] RTL-SDR Initialization failed: {e}")
            sys.exit(1)

        self.waterfall_rows = 100
        self.waterfall_data = np.ones((self.waterfall_rows, self.fft_size)) * -100 
        self.freq_axis_mhz = (np.fft.fftshift(np.fft.fftfreq(self.fft_size, d=1.0/self.sample_rate)) + self.target_freq) / 1e6

    def calculate_direction_of_arrival(self):
        """ Computes the true physical heading angle (bearing) from base to your location """
        lat1, lon1 = math.radians(self.base_lat), math.radians(self.base_lon)
        lat2, lon2 = math.radians(self.my_lat), math.radians(self.my_lon)
        dlon = lon2 - lon1
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return math.degrees(math.atan2(y, x)) % 360

    def start_audio_recording(self):
        local_timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self.current_filename = f"VAD_RECORDING_{local_timestamp}.wav"
        
        print(f"\n[SQUELCH EVENT] >>> Capturing Over-the-Air VAD Burst: {self.current_filename}")
        print(f"                Estimated Signal Arrival Direction: {self.doa_bearing:.2f}° Azimuth")
        self.wav_file = wave.open(self.current_filename, 'wb')
        self.wav_file.setnchannels(1)
        self.wav_file.setsampwidth(2) 
        self.wav_file.setframerate(self.audio_rate)
        self.is_recording = True

    def process_and_save_audio(self, iq_samples):
        if not self.is_recording or self.wav_file is None: return
        phase_demod = np.angle(iq_samples[1:] * np.conjugate(iq_samples[:-1]))
        audio_raw = phase_demod[::self.decimation_factor]
        
        if len(audio_raw) > 0:
            audio_filtered, self.filter_state = signal.lfilter(self.bandpass_coeffs, 1.0, audio_raw, zi=self.filter_state)
            audio_max = np.max(np.abs(audio_filtered))
            if audio_max > 0: audio_filtered = audio_filtered / audio_max
                
            for sample in audio_filtered:
                raw_int16 = int(max(-32768, min(32767, sample * 32767)))
                self.wav_file.writeframes(struct.pack('<h', raw_int16))

    def trigger_async_transcription(self, filepath):
        try:
            print(f"    [AI PARSING] Processing filtered audio array using Whisper 'base' model matrices...")
            result = self.whisper_model.transcribe(filepath)
            text_payload = result["text"].strip()
            
            print("\n=======================================================")
            print(f"[DECODED TRANSCRIPTION]: {text_payload if text_payload else '[UNINTELLIGIBLE STATIC CHIRP]'}")
            print("=======================================================\n")
        except Exception as e:
            print(f"[!] AI processing error: {e}")

    def stop_audio_recording(self):
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None
        self.is_recording = False
        print(f"[-] <<< GATED OFF: Signal below threshold. Re-engaging adaptive squelch.")
        
        saved_path = self.current_filename
        threading.Thread(target=self.trigger_async_transcription, args=(saved_path,), daemon=True).start()

    def capture_worker(self):
        while self.is_running:
            try:
                samples = self.sdr.read_samples(self.fft_size * 16)
                measured_variance = np.var(np.abs(samples)**2)
                current_time = time.time()
                
                if not self.is_recording:
                    self.noise_floor_variance = ((1.0 - self.alpha_adaptation) * self.noise_floor_variance) + (self.alpha_adaptation * measured_variance)
                
                if measured_variance > (self.noise_floor_variance * self.trigger_sensitivity):  
                    self.last_burst_time = current_time
                    if not self.is_recording: self.start_audio_recording()
                
                if self.is_recording:
                    self.process_and_save_audio(samples)
                    if current_time - self.last_burst_time > self.hold_time_seconds: self.stop_audio_recording()

                self.waterfall_data = np.roll(self.waterfall_data, -1, axis=0)
                self.waterfall_data[-1, :] = 10 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(samples[:self.fft_size])))**2 + 1e-10)
            except Exception as e:
                print(f"[!] SDR connection dropout: {e}"); break

    def init_plot(self):
        self.im = self.ax.imshow(self.waterfall_data, aspect='auto', cmap='viridis', extent=[self.freq_axis_mhz[0], self.freq_axis_mhz[-1], self.waterfall_rows, 0], vmin=-50, vmax=0)
        self.ax.set_title(f"Live Analytical Spectrogram: {self.target_freq/1e6:.1f} MHz")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_ylabel("Rolling Time Buffer Steps")
        self.fig.colorbar(self.im, ax=self.ax).set_label("Relative Signal Power Magnitude (dB)")
        return [self.im]

    def update_plot(self, frame):
        self.im.set_array(self.waterfall_data)
        return [self.im]

    def start(self):
        self.is_running = True
        threading.Thread(target=self.capture_worker, daemon=True).start()
        animation.FuncAnimation(self.fig, self.update_plot, init_func=self.init_plot, interval=50, blit=True)
        plt.show()

    def stop(self):
        self.is_running = False
        if self.is_recording: self.stop_audio_recording()
        self.sdr.close()

if __name__ == "__main__":
    station = AutonomousSignalStation()
    try:
        station.start()
    except KeyboardInterrupt:
        station.stop()
