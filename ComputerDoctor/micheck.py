# Quick test
import pyaudio
import numpy as np

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paFloat32, channels=1, rate=48000,
                input=True, frames_per_buffer=1024)

print('Recording... speak into the mic')
frames = [stream.read(1024) for _ in range(48)]
stream.close()
p.terminate()

audio = np.frombuffer(b''.join(frames), dtype=np.float32)
print(f'RMS: {np.sqrt(np.mean(audio**2)):.6f}')
print(f'Peak: {np.max(np.abs(audio)):.6f}')
print('✓ Working!' if np.max(np.abs(audio)) > 0.001 else '✗ Still silent')
