import numpy as np
import pyaudio
import scipy.signal as signal

# ==========================================
# STREAMING & HARDWARE PARAMETERS
# ==========================================
CHUNK = 2048
CHANNELS = 1
DODOTRONIC_SR = 192000  # Raw ultrasonic sample rate
BUILTIN_OUT_SR = 44100  # Standard output rate for headphones

DODOTRONIC_IDX = 1     # Update based on 'aplay -l'
OUTPUT_IDX = 0          # Audio output jack index

# ==========================================
# INITIALIZE HARDWARE INTERFACES
# ==========================================
p = pyaudio.PyAudio()

# Open Dodotronic Ultra-Wide Stream
stream_in = p.open(
    format=pyaudio.paFloat32,
    channels=CHANNELS,
    rate=DODOTRONIC_SR,
    input=True,
    input_device_index=DODOTRONIC_IDX,
    frames_per_buffer=CHUNK
)

# Open Real-Time Monitoring Output Stream (Headphones)
stream_out = p.open(
    format=pyaudio.paFloat32,
    channels=CHANNELS,
    rate=BUILTIN_OUT_SR,
    output=True,
    output_device_index=OUTPUT_IDX,
    frames_per_buffer=int(CHUNK * (BUILTIN_OUT_SR / DODOTRONIC_SR))
)

# ==========================================
# PRE-COMPUTE FIXED SIGINT FILTER MASKS
# ==========================================
# 1. Anti-hum filter: Rejects server noise below 3.5 kHz
nyquist_in = 0.5 * DODOTRONIC_SR
b_hp, a_hp = signal.butter(6, 3500 / nyquist_in, btype='high')

# 2. Rejection ceiling: Cuts off everything above 45 kHz before down-conversion
b_lp, a_lp = signal.butter(6, 45000 / nyquist_in, btype='low')

# Initialize moving average for Repeated Masking
noise_floor_estimate = None
alpha = 0.95  # Memory factor for dynamic environmental tracking

print("[*] SIGINT Sweeper Active. Put on headphones to listen to the converted hidden track...")

try:
    while True:
        # 1. Read raw ultrasonic frame from Dodotronic
        raw_data = stream_in.read(CHUNK, exception_on_overflow=False)
        audio_frame = np.frombuffer(raw_data, dtype=np.float32)
        
        # 2. Repeated Mask Stage 1: Frequency Windowing
        filtered = signal.filtfilt(b_hp, a_hp, audio_frame)
        filtered = signal.filtfilt(b_lp, a_lp, filtered)
        
        # 3. Repeated Mask Stage 2: Dynamic Spectral Gating
        fft_frame = np.fft.rfft(filtered)
        magnitude = np.abs(fft_frame)
        phase = np.angle(fft_frame)
        
        if noise_floor_estimate is None:
            noise_floor_estimate = magnitude
        else:
            # Continuously adapt the mask to persistent room noise (AC/Fans)
            noise_floor_estimate = (alpha * noise_floor_estimate) + ((1 - alpha) * magnitude)
            
        # Subtract the updated noise mask (SIGINT Noise Power Subtraction)
        cleaned_magnitude = np.maximum(magnitude - (noise_floor_estimate * 1.5), 0.0)
        cleaned_fft = cleaned_magnitude * np.exp(1j * phase)
        unmasked_audio = np.fft.irfft(cleaned_fft)
        
        # 4. SIGINT Frequency Down-Conversion (Envelope Demodulation)
        # Squaring the signal extracts the absolute envelope of the ultrasonic chirps,
        # naturally shifting the high-frequency energy down into the audible domain.
        demodulated_beam = np.abs(signal.hilbert(unmasked_audio))
        
        # 5. Resample down to 44.1 kHz for real-time human listening
        audible_track = signal.resample(demodulated_beam, int(len(demodulated_beam) * (BUILTIN_OUT_SR / DODOTRONIC_SR)))
        
        # Normalize and remove DC offset
        audible_track = audible_track - np.mean(audible_track)
        if np.max(np.abs(audible_track)) > 0:
            audible_track = audible_track / np.max(np.abs(audible_track))
            
        # 6. Stream directly to your headphones
        stream_out.write(audible_track.astype(np.float32).tobytes())

except KeyboardInterrupt:
    print("\n[*] Sweeper pipeline safely terminated.")
finally:
    stream_in.stop_stream(); stream_in.close()
    stream_out.stop_stream(); stream_out.close()
    p.terminate()
