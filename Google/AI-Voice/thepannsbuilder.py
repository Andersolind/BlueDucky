import os
import queue
import threading
import numpy as np
import pyaudio
import soundfile as sf

# Configuration
CHANNELS = 1
DURATION = 5  # Capture duration in seconds

# 1. Detect your audio device indices using your terminal:
# Use command: python3 -c "import pyaudio; p=pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
BUILTIN_IDX = 0       # Replace with your built-in mic index
DODOTRONIC_IDX = 1    # Replace with your Dodotronic mic index

# Sampling rates matching physical capabilities
BUILTIN_SR = 44100     # Standard audible rate
DODOTRONIC_SR = 192000 # Ultra-high rate to catch raw ultrasound up to 96kHz

def record_stream(device_idx, sample_rate, output_filename):
    p = pyaudio.PyAudio()
    
    try:
        stream = p.open(
            format=pyaudio.paFloat32,
            channels=CHANNELS,
            rate=sample_rate,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=1024
        )
    except Exception as e:
        print(f"[-] Error opening device {device_idx}: {e}")
        p.terminate()
        return

    print(f"[+] Recording started on device {device_idx}...")
    frames = []
    
    for _ in range(0, int(sample_rate / 1024 * DURATION)):
        try:
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(np.frombuffer(data, dtype=np.float32))
        except IOError:
            continue

    print(f"[+] Finished recording device {device_idx}.")
    
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    # Save file safely
    audio_data = np.concatenate(frames)
    sf.write(output_filename, audio_data, sample_rate)

# Run both microphones simultaneously using threading
t1 = threading.Thread(target=record_stream, args=(BUILTIN_IDX, BUILTIN_SR, "builtin_audible.wav"))
t2 = threading.Thread(target=record_stream, args=(DODOTRONIC_IDX, DODOTRONIC_SR, "dodotronic_ultrasonic.wav"))

t1.start()
t2.start()

t1.join()
t2.join()
print("[*] Acoustic capture complete.")
