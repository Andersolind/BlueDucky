import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from rtlsdr import RtlSdr
import threading
import sys
import time
import wave
import struct
import scipy.signal as signal

class LiveVADVisualizer:
    def __init__(self, target_freq=98.1e6, sample_rate=2.4e6, fft_size=1024):
        self.target_freq = target_freq
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.is_running = False
        
        # Audio Rate Mapping Parameters
        self.audio_rate = 44100
        self.decimation_factor = int(self.sample_rate / self.audio_rate)
        self.is_recording = False
        self.wav_file = None
        self.last_burst_time = 0
        self.hold_time_seconds = 1.5 
        
        # --- NEW: VOICE-OPTIMIZED BANDPASS FILTER CONFIGURATION ---
        # Isolates standard human vocal frequencies (300 Hz - 3400 Hz)
        self.low_cutoff = 300.0
        self.high_cutoff = 3400.0
        self.nyq_audio = self.audio_rate / 2.0
        
        # Calculate filter coefficients using a 101-tap FIR window method
        self.bandpass_coeffs = signal.firwin(
            101, 
            [self.low_cutoff / self.nyq_audio, self.high_cutoff / self.nyq_audio], 
            pass_zero='bandpass'
        )
        self.filter_state = signal.lfilter_zi(self.bandpass_coeffs, 1.0)

        # Pre-configure primary graphics canvas on the main execution pipeline
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.fig.canvas.manager.set_window_title("Live Voice-Isolating VAD Recorder")

        print("[*] Connecting to RTL-SDR hardware...")
        try:
            self.sdr = RtlSdr()
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = self.target_freq
            self.sdr.gain = 'auto'
        except Exception as e:
            print(f"[!] Critical Error: Device initialization failed. \nDetail: {e}")
            sys.exit(1)

        self.waterfall_rows = 100
        self.waterfall_data = np.ones((self.waterfall_rows, self.fft_size)) * -100 

        self.freq_axis = np.fft.fftshift(np.fft.fftfreq(self.fft_size, d=1.0/self.sample_rate)) + self.target_freq
        self.freq_axis_mhz = self.freq_axis / 1e6

    def start_audio_recording(self):
        """ Generates a local file payload stamped with structural ISO timestamps """
        # --- NEW: LOCALIZED TIMESTAMP NAMING ---
        # Outputs clean local time file strings: e.g., VAD_RECORDING_20260720_174215.wav
        local_timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        filename = f"VAD_RECORDING_{local_timestamp}.wav"
        
        print(f"\n[+] >>> VOICE BURST ENVELOPE OPEN: Saving to {filename}")
        self.wav_file = wave.open(filename, 'wb')
        self.wav_file.setnchannels(1)
        self.wav_file.setsampwidth(2) # 16-bit binary linear PCM formatting
        self.wav_file.setframerate(self.audio_rate)
        self.is_recording = True

    def process_and_save_audio(self, iq_samples):
        """ Extracts baseband FM, applies bandpass speech filters, and saves to file """
        if not self.is_recording or self.wav_file is None:
            return
            
        # 1. Baseband Phase Differentiation (FM Demodulation Math)
        phase_demod = np.angle(iq_samples[1:] * np.conjugate(iq_samples[:-1]))
        
        # 2. Down-sample the signal to fit our audio hardware rate
        audio_raw = phase_demod[::self.decimation_factor]
        
        if len(audio_raw) > 0:
            # 3. --- NEW: APPLY DIGITAL BANDPASS AUDIO FILTER ---
            # Stretches processing state across chunk boundaries to avoid clicking artifacts
            audio_filtered, self.filter_state = signal.lfilter(
                self.bandpass_coeffs, 1.0, audio_raw, zi=self.filter_state
            )
            
            # 4. Enforce amplitude clipping constraints and maximize dynamic range
            audio_max = np.max(np.abs(audio_filtered))
            if audio_max > 0:
                audio_filtered = audio_filtered / audio_max
                
            # 5. Serialize floating point data into raw 16-bit binary fragments
            for sample in audio_filtered:
                raw_int16 = int(max(-32768, min(32767, sample * 32767)))
                self.wav_file.writeframes(struct.pack('<h', raw_int16))

    def stop_audio_recording(self):
        """ Safely parks the uncompressed audio handler """
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None
        self.is_recording = False
        print("\n[-] <<< SILENCE DROPOUT WINDOW REACHED: Saving file data and returning to stand-by.")

    def capture_worker(self):
        print(f"[+] Active. Analyzing spectrum grid centered at {self.target_freq/1e6:.2f} MHz...")
        
        while self.is_running:
            try:
                # Read continuous byte fields off the physical USB endpoints
                samples = self.sdr.read_samples(self.fft_size * 16)
                chunk = samples[:self.fft_size]
                
                fft_output = np.fft.fftshift(np.fft.fft(chunk))
                power_db = 10 * np.log10(np.abs(fft_output)**2 + 1e-10)
                
                # Monitor absolute variance limits to trigger the voice gating mechanism
                variance = np.var(np.abs(samples)**2)
                current_time = time.time()
                
                if variance > 0.005:  # Over-the-air bright yellow signal power trigger
                    self.last_burst_time = current_time
                    if not self.is_recording:
                        self.start_audio_recording()
                
                if self.is_recording:
                    self.process_and_save_audio(samples)
                    if current_time - self.last_burst_time > self.hold_time_seconds:
                        self.stop_audio_recording()

                self.waterfall_data = np.roll(self.waterfall_data, -1, axis=0)
                self.waterfall_data[-1, :] = power_db
                
            except Exception as e:
                print(f"\n[!] Data bus dropout: {e}")
                break

    def init_plot(self):
        self.im = self.ax.imshow(
            self.waterfall_data, 
            aspect='auto', 
            cmap='viridis', 
            extent=[self.freq_axis_mhz[0], self.freq_axis_mhz[-1], self.waterfall_rows, 0],
            vmin=-50, vmax=0 
        )
        
        self.ax.set_title(f"Live Spectrum Waterfall: {self.target_freq/1e6:.1f} MHz")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_ylabel("Time Matrix Steps (Rolling)")
        
        cbar = self.fig.colorbar(self.im, ax=self.ax)
        cbar.set_label("Relative Signal Power Magnitude (dB)")
        
        return [self.im]

    def update_plot(self, frame):
        self.im.set_array(self.waterfall_data)
        return [self.im]

    def start(self):
        self.is_running = True
        
        self.thread = threading.Thread(target=self.capture_worker, daemon=True)
        self.thread.start()
        
        ani = animation.FuncAnimation(
            self.fig, self.update_plot, init_func=self.init_plot, interval=50, blit=True
        )
        plt.show()

    def stop(self):
        self.is_running = False
        if self.is_recording:
            self.stop_audio_recording()
        print("\n[*] Detaching from SDR USB hardware layer cleanly...")
        self.sdr.close()

if __name__ == "__main__":
    MONITOR_FREQ = 98.1e6
    
    visualizer = LiveVADVisualizer(target_freq=MONITOR_FREQ)
    try:
        visualizer.start()
    except KeyboardInterrupt:
        pass
    finally:
        visualizer.stop()
        print("[+] Hardware safe-state restored.")
