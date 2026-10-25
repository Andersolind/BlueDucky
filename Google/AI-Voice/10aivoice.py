import os
import time
import threading
import queue
import numpy as np
import pyaudio
import scipy.signal as signal

# ==========================================
# SYSTEM PARAMETERS & DEVICE HARDWARE MAP
# ==========================================
CHUNK = 2048
CHANNELS = 1
DODOTRONIC_SR = 192000  # Raw ultrasound capture rate
BUILTIN_OUT_SR = 44100  # Headphone playback rate

DODOTRONIC_IDX = 1      # Update based on 'aplay -l'
OUTPUT_IDX = 0          # Headphone jack index

# Shared thread queues for concurrent SIGINT logging
rf_sync_queue = queue.Queue()
audio_processing_queue = queue.Queue()

# ==========================================
# 1. HACKRF HIGH-SPEED RF SYNC DETECTOR (T0)
# ==========================================
def hackrf_rf_layer_sniffer():
    """
    Leverages HackRF One via raw terminal pipes to detect the 
    high-speed RF layer sync pulses (e.g., at 433.92 MHz).
    """
    print("[+] HackRF One RF Sync Engine Engaged...")
    
    # Run hackrf_transfer streaming raw IQ data directly into a stdout pipeline
    # -f 433920000: Center frequency
    # -s 2000000: 2 MSPS sample rate to capture short transient pulses
    # -r -: Output directly to standard out pipe
    cmd = "hackrf_transfer -f 433920000 -s 2000000 -r - 2>/dev/null"
    pipe = os.popen(cmd, "rb")
    
    try:
        while True:
            # Read block of IQ data (8-bit signed IQ bytes)
            raw_iq = pipe.read(4096)
            if not raw_iq:
                break
                
            iq_data = np.frombuffer(raw_iq, dtype=np.int8).astype(np.float32)
            # Calculate instantaneous RF amplitude envelope
            rf_amplitude = np.abs(iq_data[0::2] + 1j * iq_data[1::2])
            
            # If RF energy breaks past background threshold, flag the event
            if np.max(rf_amplitude) > 45.0:  # Adjust threshold based on your local environment noise
                t0_timestamp = time.time()
                rf_sync_queue.put(t0_timestamp)
                
    except Exception as e:
        print(f"[-] HackRF Pipe Error: {e}")
    finally:
        pipe.close()

# ==========================================
# 2. AUDIO STREAMING & REPEATED MASK PIPELINE
# ==========================================
def audio_dsp_demodulator_engine():
    p = pyaudio.PyAudio()
    
    # Open Dodotronic Wideband Ultrasonic Input
    stream_in = p.open(
        format=pyaudio.paFloat32, channels=CHANNELS, rate=DODOTRONIC_SR,
        input=True, input_device_index=DODOTRONIC_IDX, frames_per_buffer=CHUNK
    )
    
    # Open Live Audible Monitoring (Headphones)
    stream_out = p.open(
        format=pyaudio.paFloat32, channels=CHANNELS, rate=BUILTIN_OUT_SR,
        output=True, output_device_index=OUTPUT_IDX, frames_per_buffer=int(CHUNK * (BUILTIN_OUT_SR / DODOTRONIC_SR))
    )
    
    # Pre-compute SIGINT Filter Profiles
    nyquist_in = 0.5 * DODOTRONIC_SR
    b_hp, a_hp = signal.butter(6, 3500 / nyquist_in, btype='high')   # Block AC/Server noise
    b_lp, a_lp = signal.butter(6, 45000 / nyquist_in, btype='low')   # Cut raw carrier floor
    
    noise_floor_estimate = None
    alpha = 0.95  # Adaptive memory tracker for shifting environment noises
    
    print("[+] Audio Extraction Engine Active. Repeated Mask Calibrated.")
    
    try:
        while True:
            # Read ultrasonic chunk
            raw_data = stream_in.read(CHUNK, exception_on_overflow=False)
            audio_frame = np.frombuffer(raw_data, dtype=np.float32)
            
            # Apply Repeated Spectral Mask Steps
            filtered = signal.filtfilt(b_hp, a_hp, audio_frame)
            filtered = signal.filtfilt(b_lp, a_lp, filtered)
            
            fft_frame = np.fft.rfft(filtered)
            magnitude = np.abs(fft_frame)
            phase = np.angle(fft_frame)
            
            if noise_floor_estimate is None:
                noise_floor_estimate = magnitude
            else:
                noise_floor_estimate = (alpha * noise_floor_estimate) + ((1 - alpha) * magnitude)
                
            # Dynamic Spectral Gating Subtraction
            cleaned_magnitude = np.maximum(magnitude - (noise_floor_estimate * 1.5), 0.0)
            cleaned_fft = cleaned_magnitude * np.exp(1j * phase)
            unmasked_audio = np.fft.irfft(cleaned_fft)
            
            # Envelope Down-Conversion to shift ultrasound to human hearing range
            demodulated_beam = np.abs(signal.hilbert(unmasked_audio))
            
            # Check for acoustic peak occurrences
            acoustic_peak = np.max(demodulated_beam)
            if acoustic_peak > 0.15:  # Absolute normalized sound threshold
                arrival_time = time.time()
                audio_processing_queue.put((arrival_time, acoustic_peak))
            
            # Downsample signal to 44.1 kHz for monitoring output
            audible_track = signal.resample(demodulated_beam, int(len(demodulated_beam) * (BUILTIN_OUT_SR / DODOTRONIC_SR)))
            audible_track = audible_track - np.mean(audible_track)
            
            if np.max(np.abs(audible_track)) > 0:
                audible_track = audible_track / np.max(np.abs(audible_track))
                
            # Write out to headphones
            stream_out.write(audible_track.astype(np.float32).tobytes())
            
    except Exception as e:
        print(f"[-] Audio Engine Error: {e}")
    finally:
        stream_in.stop_stream(); stream_in.close()
        stream_out.stop_stream(); stream_out.close()
        p.terminate()

# ==========================================
# 3. CENTRAL INTELLIGENCE CORRELATION LOGGER
# ==========================================
def sigint_event_correlation_logger():
    """
    Correlates HackRF T0 triggers with Dodotronic audio arrivals,
    printing timestamps and calculating time-of-flight windows.
    """
    print("[*] Multi-Band Correlation Engine Online. Awaiting system firings...\n")
    last_t0 = None
    
    while True:
        # Check if HackRF intercepted an RF sync trigger
        try:
            last_t0 = rf_sync_queue.get_nowait()
            print(f"\x1b[35m[FLAG - RF SYNC]\x1b[0m Trigger T0 captured at: {time.strftime('%H:%M:%S', time.localtime(last_t0))}.{int(last_t0*1000)%1000:03d}ms")
        except queue.Empty:
            pass
            
        # Check if Dodotronic intercepted a masked acoustic wave occurrence
        try:
            t_arrival, amplitude = audio_processing_queue.get_nowait()
            readable_time = f"{time.strftime('%H:%M:%S', time.localtime(t_arrival))}.{int(t_arrival*1000)%1000:03d}ms"
            
            if last_t0 is not None:
                # Calculate time delay between RF sync layer and ultrasound arrival
                tof_ms = (t_arrival - last_t0) * 1000.0
                # Approximate distance calculation based on speed of sound (~343 m/s)
                est_distance = tof_ms * 0.343
                
                print(f"\x1b[32m[FLAG - ACOUSTIC CHIRP]\x1b[0m Detected at: {readable_time} | ToF: {tof_ms:.2f} ms | Est. Target Distance: {est_distance:.2f} meters")
            else:
                print(f"\x1b[33m[FLAG - ACOUSTIC CHIRP (UNSYNCED)]\x1b[0m Detected at: {readable_time} | Peak Amp: {amplitude:.4f}")
        except queue.Empty:
            pass
            
        time.sleep(0.001) # Keep processor usage down

# ==========================================
# MAIN LIFECYCLE CONTROLLER
# ==========================================
if __name__ == "__main__":
    # Initialize background operational threads
    thread_rf = threading.Thread(target=hackrf_rf_layer_sniffer, daemon=True)
    thread_audio = threading.Thread(target=audio_dsp_demodulator_engine, daemon=True)
    thread_logger = threading.Thread(target=sigint_event_correlation_logger, daemon=True)
    
    thread_rf.start()
    thread_audio.start()
    thread_logger.start()
    
    try:
        # Keep main execution frame alive until keyboard interrupt
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Shutting down tracking system cleanly.")
