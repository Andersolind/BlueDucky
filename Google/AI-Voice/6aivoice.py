import numpy as np
import pyaudio
import scipy.signal as signal
import matplotlib.pyplot as plt

# Pipeline Profiles
CHUNK = 2048
RATE = 48000  # Target audio rate for human vocal parsing
DEVICE_IDX = 1  # Dodotronic or specialized contact input array

p = pyaudio.PyAudio()
stream = p.open(
    format=pyaudio.paFloat32, channels=1, rate=RATE,
    input=True, input_device_index=DEVICE_IDX, frames_per_buffer=CHUNK
)

# Setup Live Interactive Plotting Configuration
plt.ion()
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

# Initialize Spectrogram Array Buffers
spectrogram_data = np.zeros((1025, 100))

# Pre-compute Vocal Enhancement Window Filters (Focusing strictly on human speech: 80Hz - 8kHz)
nyquist = 0.5 * RATE
b_vocal, a_vocal = signal.butter(4, [80 / nyquist, 8000 / nyquist], btype='band')

print("[*] Spectral Mirror Engine Online. Processing bone-conduction and micro-murmur tracks...")

try:
    while True:
        # 1. Capture stream frame
        raw_data = stream.read(CHUNK, exception_on_overflow=False)
        audio_frame = np.frombuffer(raw_data, dtype=np.float32)
        
        # 2. Extract Speech Vector / Apply Processing Filter
        enhanced_speech = signal.filtfilt(b_vocal, a_vocal, audio_frame)
        
        # 3. Calculate Short-Time Fourier Transform (STFT) for Visualizing Formants
        frequencies, times, stft_matrix = signal.spectrogram(enhanced_speech, fs=RATE, nperseg=2048)
        magnitude = np.log10(np.abs(stft_matrix) + 1e-6)
        
        # Shift data across window matrix to simulate a scrolling waterfall mirror
        spectrogram_data = np.roll(spectrogram_data, -1, axis=1)
        spectrogram_data[:, -1] = np.mean(magnitude, axis=1)[:1025]
        
        # 4. Update Spectral Presentation Frames
        ax1.clear()
        # Top Panel: Standard Formant Visualization Track
        ax1.imshow(spectrogram_data[:200, :], cmap='viridis', aspect='auto', origin='lower')
        ax1.set_title("Vocal Formant Trajectory Track (Low-Freq Murmurs)")
        ax1.set_ylabel("Frequency Matrix Bin")
        
        ax2.clear()
        # Bottom Panel: The "Mirror Track" (Inverted phase matching to check for matching harmonics)
        mirrored_data = np.flipud(spectrogram_data[:200, :])
        ax2.imshow(mirrored_data, cmap='magma', aspect='auto', origin='lower')
        ax2.set_title("Phase-Mirrored Structural Feedback Array")
        ax2.set_xlabel("Time Frame History Buffer")
        
        plt.draw()
        plt.pause(0.01)

except KeyboardInterrupt:
    print("\n[*] Spectral Mirror pipeline safely closed.")
finally:
    stream.stop_stream(); stream.close(); p.terminate()
