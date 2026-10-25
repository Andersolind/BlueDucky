import os
import csv
import time
import uuid
import numpy as np
import pyaudio
import scipy.signal as signal
import soundfile as sf

# ==========================================
# SYSTEM PARAMETERS & STORAGE PATHS
# ==========================================
CHUNK = 2048
RATE = 48000  
DEVICE_IDX = 1  

DATASET_DIR = "/root/styletts2_training_set/"
AUDIO_DIR = os.path.join(DATASET_DIR, "wavs/")
os.makedirs(AUDIO_DIR, exist_ok=True)
MANIFEST_PATH = os.path.join(DATASET_DIR, "train_list.txt") # Formatted for StyleTTS2 line-by-line filelists

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paFloat32, channels=1, rate=RATE,
                input=True, input_device_index=DEVICE_IDX, frames_per_buffer=CHUNK)

# Pre-compute DSP Array
nyquist = 0.5 * RATE
b_band, a_band = signal.butter(4, [80 / nyquist, 8000 / nyquist], btype='band')

# Hardware Electronic Whine Nullifiers
notch_frequencies = [4000.0, 8000.0, 12000.0, 16000.0, 19200.0]
notches = []
for f_center in notch_frequencies:
    b, a = signal.iirnotch(f_center, Q=40.0, fs=RATE)
    notches.append((b, a))

print("[*] Unified Live Extraction & StyleTTS2 Dataset Core Active.")

recording_buffer = []
is_speaking = False
speech_timeout = 0.0
last_frame_energy = 0.0

try:
    while True:
        raw_data = stream.read(CHUNK, exception_on_overflow=False)
        frame = np.frombuffer(raw_data, dtype=np.float32)
        
        # 1. ERADICATE ELECTRONIC COIL WHINE
        processed = signal.filtfilt(b_band, a_band, frame)
        for b, a in notches:
            processed = signal.filtfilt(b, a, processed)
            
        # 2. DYNAMIC PRESSURE EXPULSION GATE
        # Looks for sharp, low-frequency cable movement pops or handling thuds
        current_energy = np.sqrt(np.mean(processed**2))
        energy_derivative = np.abs(current_energy - last_frame_energy)
        last_frame_energy = current_energy
        
        if energy_derivative > 0.45:  # Detects sudden mechanical friction or pressure spikes
            print("\x1b[31m[!] MECHANICAL BASELINE SPIKE REJECTED (Cable Tug/Friction Gate Triggered)\x1b[0m")
            recording_buffer = []  # Discard corrupt segment window
            is_speaking = False
            continue
            
        # 3. SPEECH DETECTION SLICER
        if current_energy > 0.015:
            if not is_speaking:
                is_speaking = True
            speech_timeout = time.time()
            recording_buffer.append(processed)
        else:
            if is_speaking and (time.time() - speech_timeout > 1.0):
                is_speaking = False
                complete_clip = np.concatenate(recording_buffer)
                recording_buffer = []
                
                if len(complete_clip) > RATE * 1.0: # Minimum 1 second clip
                    complete_clip = complete_clip / np.max(np.abs(complete_clip))
                    clip_uuid = str(uuid.uuid4())[:8]
                    filename = f"clip_{clip_uuid}.wav"
                    full_save_path = os.path.join(AUDIO_DIR, filename)
                    
                    sf.write(full_save_path, complete_clip, RATE)
                    
                    # Append straight to StyleTTS2 formatting standard: file_path|transcript_placeholder|speaker_id
                    with open(MANIFEST_PATH, "a") as f:
                        f.write(f"wavs/{filename}|PROCESSED_VIBRATION_STREAM|0\n")
                    print(f"[✔] StyleTTS2 Audio Record Saved: {filename}")

except KeyboardInterrupt:
    print("\n[*] Logging loop terminated.")
finally:
    stream.stop_stream(); stream.close(); p.terminate()
