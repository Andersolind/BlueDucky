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
        
        # Audio Configuration Parameters
        self.audio_rate = 44100
        self.decimation_factor = int(self.sample_rate / self.audio_rate)
        self.is_recording = False
        self.wav_file = None
        self.last_burst_time = 0
        self.hold_time_seconds = 1.5 # Keep recording for 1.5s after speech ends
        
        # Fix: Pre-configure UI canvas explicitly on the initiation main thread
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.fig.canvas.manager.set_window_title("Live VAD Burst Tracker & Recorder")

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
        """ Dynamically opens a local uncompressed WAV file payload """
        filename = f"VAD_BURST_{int(time.time())}.wav"
        print(f"\n[+] >>> ACTIVE BURST TRIGGER: Opening Recording: {filename}")
        self.wav_file = wave.open(filename, 'wb')
        self.wav_file.setnchannels(1)
        self.wav_file.setsampwidth(2) # 16-bit PCM formatting
        self.wav_file.setframerate(self.audio_rate)
        self.is_recording = True

    def process_and_save_audio(self, iq_samples):
        """ Demodulates instantaneous FM changes and writes raw bytes to disk """
        if not self.is_recording or self.wav_file is None:
            return
            
        # Standard FM phase angle delta extraction math
        phase_demod = np.angle(iq_samples[1:] * np.conjugate(iq_samples[:-1]))
        
        # Down-sample to safe soundcard ranges
        audio_payload = phase_demod[::self.decimation_factor]
        
        # Normalize and pack audio arrays into 16-bit binary integer streams
        if len(audio_payload) > 0:
            audio_payload = audio_payload / max(np.max(np.abs(audio_payload)), 1e-6)
            for sample in audio_payload:
                raw_int16 = int(max(-32768, min(32767, sample * 32767)))
                self.wav_file.writeframes(struct.pack('<h', raw_int16))

    def stop_audio_recording(self):
        """ Closes the wave file cleanly """
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None
        self.is_recording = False
        print("\n[-] <<< SILENCE TIMEOUT: Closing Recording Block Safely.")

    def capture_worker(self):
        print(f"[+] Active. Monitoring spectrum centered at {self.target_freq/1e6:.2f} MHz...")
        
        while self.is_running:
            try:
                # Read large block chunks to capture a complete window profile
                samples = self.sdr.read_samples(self.fft_size * 16)
                chunk = samples[:self.fft_size]
                
                fft_output = np.fft.fftshift(np.fft.fft(chunk))
                power_db = 10 * np.log10(np.abs(fft_output)**2 + 1e-10)
                
                # Check variance to identify active voice transmission power
                variance = np.var(np.abs(samples)**2)
                current_time = time.time()
                
                if variance > 0.005:  # Over-the-air yellow/green burst threshold
                    self.last_burst_time = current_time
                    if not self.is_recording:
                        self.start_audio_recording()
                
                # If recording, write live demodulated data blocks
                if self.is_recording:
                    self.process_and_save_audio(samples)
                    # Automatically drop out of capture if silence persists past limit
                    if current_time - self.last_burst_time > self.hold_time_seconds:
                        self.stop_audio_recording()

                self.waterfall_data = np.roll(self.waterfall_data, -1, axis=0)
                self.waterfall_data[-1, :] = power_db
                
            except Exception as e:
                print(f"\n[!] Data acquisition dropout: {e}")
                break

    def init_plot(self):
        # Fix: Do not instantiate subplots here. Instead, configure the pre-existing objects
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
        cbar.set_label("Relative Signal Magnitude Power (dB)")
        
        return [self.im]

    def update_plot(self, frame):
        self.im.set_array(self.waterfall_data)
        return [self.im]

    def start(self):
        self.is_running = True
        
        self.thread = threading.Thread(target=self.capture_worker, daemon=True)
        self.thread.start()
        
        # Fire up the GUI layout safely on the primary calling pipeline
        ani = animation.FuncAnimation(
            self.fig, self.update_plot, init_func=self.init_plot, interval=50, blit=True
        )
        plt.show()

    def stop(self):
        self.is_running = False
        if self.is_recording:
            self.stop_audio_recording()
        print("\n[*] Unmounting SDR receiver hardware interface...")
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
        print("[+] Hardware safely disengaged.")
