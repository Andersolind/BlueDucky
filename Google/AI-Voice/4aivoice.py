import os
import csv
import time
import uuid
import numpy as np
import pyaudio
import scipy.signal as signal
import soundfile as sf
import matplotlib.pyplot as plt

# ==========================================
# SYSTEM PARAMETERS & STORAGE PATHS
# ==========================================
CHUNK = 4096
RATE = 48000  # Optimized sampling for human speech parsing
DEVICE_IDX = 1  # Dodotronic or specialized contact pickup device

DATASET_DIR = "/root/hubert_training_set/"
AUDIO_DIR = os.path.join(DATASET_DIR, "wavs/")
os.makedirs(AUDIO_DIR, exist_ok=True)
MANIFEST_PATH = os.path.join(DATASET_DIR, "metadata.csv")

# Initialize persistent tracking arrays
if not os.path.exists(MANIFEST_PATH):
    with open(MANIFEST_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["audio_file", "timestamp", "duration_sec"])

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paFloat32, channels=1, rate=RATE,
                input=True, input_device_index=DEVICE_IDX, frames_per_buffer=CHUNK)

# ==========================================
# ADVANCED SIGNAL SUPPRESSION FILTERS
# ==========================================
nyquist = 0.5 * RATE

# 1. Base Vocal Passband (80Hz - 8000Hz)
b_band, a_band = signal.butter(4, [80 / nyquist, 8000 / nyquist], btype='band')

# 2. Automated Multi-Notch Array for Electronic Coil Whine Suppressions
# Targets typical server rack/power brick frequencies in the room
notch_frequencies = [4000.0, 8000.0, 12000.0, 16000.0] 
notches = []
for f_center in notch_frequencies:
    b, a = signal.iirnotch(f_center, Q=30.0, fs=RATE)
    notches.append((b, a))

# Live sliding visualization arrays
plt.ion()
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))
spectrogram_buffer = np.zeros((513, 100))

print("[*] Unified Structural Extraction Engine Engaged.")
print("[*] Automated dataset collection active... Speak into the contact array.")

recording_buffer = []
is_speaking = False
speech_timeout = 0.0

try:
    while True:
        raw_data = stream.read(CHUNK, exception_on_overflow=False)
        frame = np.frombuffer(raw_data, dtype=np.float32)
        
        # --- SIGINT STAGE 1: SIGNAL PROCESSING ENGINE ---
        # Apply broad voice bandpass
        processed = signal.filtfilt(b_band, a_band, frame)
        # Apply sequential sharp notch filters to eradicate electronic coil whine
        for b, a in notches:
            processed = signal.filtfilt(b, a, processed)
            
        # --- SIGINT STAGE 2: MATHEMATICAL LIVE SPECTRUM MIRROR ---
        frequencies, times, stft_matrix = signal.spectrogram(processed, fs=RATE, nperseg=1024)
        mag = np.log10(np.abs(stft_matrix) + 1e-6)
        
        spectrogram_buffer = np.roll(spectrogram_buffer, -1, axis=1)
        spectrogram_buffer[:, -1] = np.mean(mag, axis=1)[:513]
        
        ax1.clear()
        ax1.imshow(spectrogram_buffer[:150, :], cmap='viridis', aspect='auto', origin='lower')
        ax1.set_title("Vocal Formant Trajectory Tracker (Electronic Coil Hum Erased)")
        
        ax2.clear()
        ax2.imshow(np.flipud(spectrogram_buffer[:150, :]), cmap='magma', aspect='auto', origin='lower')
        ax2.set_title("Phase-Inverted Structural Mirror Grid")
        plt.draw(); plt.pause(0.001)
        
        # --- SIGINT STAGE 3: AUTOMATED SPEECH SLICER & LOGGER ---
        energy = np.sqrt(np.mean(processed**2))
        
        if energy > 0.02:  # Threshold identifying structural speech vibrations
            if not is_speaking:
                print("\x1b[32m[+] Structural Speech Detected. Slicing track...\x1b[0m")
                is_speaking = True
            speech_timeout = time.time()
            recording_buffer.append(processed)
        else:
            if is_speaking and (time.time() - speech_timeout > 1.2):
                # Target finished speaking (1.2 seconds of silence gap encountered)
                print("[-] Target Silent. Packing audio segment to Dataset Repository.")
                is_speaking = False
                
                # Consolidate and finalize the audio track file
                complete_clip = np.concatenate(recording_buffer)
                recording_buffer = []
                
                # Protect against tiny accidental spikes (e.g. table bumps)
                if len(complete_clip) > RATE * 1.5: 
                    # Normalize amplitude perfectly to balance contact pressure shifts
                    complete_clip = complete_clip / np.max(np.abs(complete_clip))
                    
                    clip_uuid = str(uuid.uuid4())[:8]
                    filename = f"clip_{clip_uuid}.wav"
                    full_save_path = os.path.join(AUDIO_DIR, filename)
                    
                    # Write clean file to disk
                    sf.write(full_save_path, complete_clip, RATE)
                    
                    # Update training index csv manifest
                    with open(MANIFEST_PATH, "a", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow([filename, time.time(), len(complete_clip)/RATE])
                    print(f"[✔] Training Clip Recorded: {filename} ({len(complete_clip)/RATE:.2f}s)")

except KeyboardInterrupt:
    print("\n[*] Hardware collection loop halted.")
finally:
    stream.stop_stream(); stream.close(); p.terminate(); plt.close()
