import os
import time
import threading
import numpy as np
import pyaudio
import soundfile as sf
import torch
import torch.nn as nn
import librosa
from rtlsdr import RtlSdr
from panns_inference import models

# ==========================================
# HARDWARE PROFILE & PIPELINE CONFIGURATION
# ==========================================
BATCH_DURATION = 3.0    # Duration of each processing step (seconds)
OUTPUT_DIR = "/root/triangulation_batches/"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Audio Configuration
BUILTIN_IDX = 0        # Find via: pyaudio.PyAudio().get_device_info_by_index()
DODOTRONIC_IDX = 1     # Find via same command
BUILTIN_SR = 44100     # Audible beam path rate
DODOTRONIC_SR = 192000 # Dodotronic raw ultrasonic sample rate

# SDR Configuration
# RTL-SDR V4 uses built-in upconverter. To capture transducer EMI leakage (e.g. at 150 kHz),
# simply tune directly to 150,000 Hz. No direct_sampling configuration required.
RTL_FREQ = 150000      
RTL_SAMP_RATE = 2048000 

def record_audio_stream(device_idx, sample_rate, duration, filename):
    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=pyaudio.paFloat32, channels=1, rate=sample_rate,
                        input=True, input_device_index=device_idx, frames_per_buffer=1024)
        frames = []
        for _ in range(0, int(sample_rate / 1024 * duration)):
            frames.append(np.frombuffer(stream.read(1024, exception_on_overflow=False), dtype=np.float32))
        
        stream.stop_stream()
        stream.close()
        sf.write(filename, np.concatenate(frames), sample_rate)
    except Exception as e:
        print(f"[-] Audio Device {device_idx} error: {e}")
    finally:
        p.terminate()

def record_rtlsdr_emi(frequency, sample_rate, duration, filename):
    try:
        sdr = RtlSdr()
        sdr.sample_rate = sample_rate
        sdr.center_freq = frequency
        sdr.gain = 'auto'
        
        # Calculate samples needed
        num_samples = int(sample_rate * duration)
        iq_samples = sdr.read_samples(num_samples)
        sdr.close()
        
        # Save raw IQ data for processing
        np.save(filename, iq_samples)
    except Exception as e:
        print(f"[-] RTL-SDR error: {e}")

def record_hackrf_sync(duration, filename):
    """
    Leverages hackrf_transfer via os system call for maximum reliability 
    as root inside Kali, bypassing heavy python wrapper overheads.
    Captures the high-speed RF Layer Sync pulse (e.g., at 433 MHz).
    """
    cmd = f"hackrf_transfer -r {filename} -f 433920000 -s 10000000 -n {int(10000000 * duration)} > /dev/null 2>&1"
    os.system(cmd)

# ==========================================
# CUSTOM ULTRA-WIDE FMAX PANNS DETECTOR
# ==========================================
class MultiBandPANNsDetector(nn.Module):
    def __init__(self, num_classes=2):
        super(MultiBandPANNsDetector, self).__init__()
        # Initialize Cnn14 native backbone
        self.base_model = models.Cnn14(sample_rate=48000, window_size=2048, 
                                        hop_size=512, mel_bins=64, fmin=50, 
                                        fmax=24000, classes_num=527)
        # Point the final layer to our 2 states: [0: Quiet/Passive, 1: Triangulating Audio Beam]
        in_features = self.base_model.fc_audioset.in_features
        self.base_model.fc_audioset = nn.Linear(in_features, num_classes)

    def forward(self, x):
        return self.base_model(x)['clipwise_output']

# ==========================================
# MAIN EXECUTION ROUTINE (LIVE EXPERIMENT LOOP)
# ==========================================
if __name__ == "__main__":
    print("[*] Initializing Multi-Band Detection Pipeline (Kali Root Mode)...")
    
    # Instantiate Model and wrap in evaluation state
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    detector = MultiBandPANNsDetector(num_classes=2).to(device)
    detector.eval() # Processing batches
    
    batch_counter = 0
    try:
        while True:
            batch_counter += 1
            print(f"\n--- [Processing Batch Execution #{batch_counter}] ---")
            
            # Setup dynamic string file targets
            file_builtin = os.path.join(OUTPUT_DIR, f"b{batch_counter}_audible.wav")
            file_dodotronic = os.path.join(OUTPUT_DIR, f"b{batch_counter}_ultrasound.wav")
            file_rtl = os.path.join(OUTPUT_DIR, f"b{batch_counter}_rtl.npy")
            file_hackrf = os.path.join(OUTPUT_DIR, f"b{batch_counter}_hackrf.iq")
            
            # Spawn asynchronous execution threads across all hardware domains
            t_audio1 = threading.Thread(target=record_audio_stream, args=(BUILTIN_IDX, BUILTIN_SR, BATCH_DURATION, file_builtin))
            t_audio2 = threading.Thread(target=record_audio_stream, args=(DODOTRONIC_IDX, DODOTRONIC_SR, BATCH_DURATION, file_dodotronic))
            t_sdr1   = threading.Thread(target=record_rtlsdr_emi, args=(RTL_FREQ, RTL_SAMP_RATE, BATCH_DURATION, file_rtl))
            t_sdr2   = threading.Thread(target=record_hackrf_sync, args=(BATCH_DURATION, file_hackrf))
            
            # Start parallel capture execution
            t_audio1.start(); t_audio2.start(); t_sdr1.start(); t_sdr2.start()
            
            # Wait for all sensors to complete their window duration
            t_audio1.join(); t_audio2.join(); t_sdr1.join(); t_sdr2.join()
            print("[+] Capture window complete. Processing files...")

            # ----------------------------------------------------
            # DATA PREPARATION & PANNs ML PREDICTION STAGE
            # ----------------------------------------------------
            if os.path.exists(file_dodotronic):
                # Load the high frequency file
                y, sr = librosa.load(file_dodotronic, sr=None)
                # Downsample to 48kHz using an anti-aliasing filter to keep the subharmonics intact
                y_panns = librosa.resample(y, orig_sr=sr, target_sr=48000)
                
                # Check for amplitude anomalies from parametric audio beams
                if np.max(np.abs(y_panns)) > 0:
                    y_panns = y_panns / np.max(np.abs(y_panns))
                
                # Format to Tensor shape: (Batch Size, Audio Samples)
                input_tensor = torch.tensor(y_panns, dtype=torch.float32).unsqueeze(0).to(device)
                
                with torch.no_grad():
                    predictions = detector(input_tensor)
                    predicted_class = torch.argmax(predictions, dim=1).item()
                
                # ----------------------------------------------------
                # EXTRACTION METRICS FOR HARDWARE LOGGING
                # ----------------------------------------------------
                # Look at the RTL-SDR tracking data for high-energy EMI spikes (T0 Transducer firings)
                if os.path.exists(file_rtl):
                    iq_data = np.load(file_rtl)
                    signal_power = np.mean(np.abs(iq_data)**2)
                    print(f"[!] Transducer EMI Signal Power (RTL-SDR V4): {signal_power:.6f}")

                status_map = {0: "Passive / Quiet Environment", 1: "ACTIVE TRIANGULATION / AUDIO BEAM PATH ENGAGED"}
                print(f"[>>>] TARGET SYSTEM STATE: {status_map[predicted_class]}")
            else:
                print("[-] Error: Dodotronic wave batch missing. Skipping classification iteration.")

            time.sleep(0.5) # Gentle cooldown loop to preserve CPU stability

    except KeyboardInterrupt:
        print("\n[*] Integration script halted safely by operator command.")
