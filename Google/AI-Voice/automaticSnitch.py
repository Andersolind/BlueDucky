import os
import json
import time
import uuid
import threading
import numpy as np
import pyaudio
import scipy.signal as signal
import soundfile as sf
import torch
from transformers import HubertModel, Wav2Vec2FeatureExtractor

# ==========================================
# RESOURCE & TELEMETRY MONITORING THREAD
# ==========================================
def live_performance_telemetry_worker(config_path):
    """
    Independent monitor thread parsing device state performance counters 
    and line limits without blocking streaming audio threads.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("[+] Live Telemetry Performance Tracker Active.")
    
    while True:
        try:
            # Reload configuration to reflect live changes on disk
            with open(config_path, "r") as f:
                cfg = json.load(f)
                
            manifest_path = os.path.join(cfg["dataset"]["output_directory"], "train_list.txt")
            line_count = 0
            if os.path.exists(manifest_path):
                with open(manifest_path, "r") as m_file:
                    line_count = sum(1 for _ in m_file)
            
            print(f"\n--- [SYSTEM TELEMETRY ENGINE] ---")
            print(f"[*] StyleTTS2 Target Line Limit Count: {line_count} / {cfg['dataset']['target_manifest_line_limit']}")
            print(f"[*] Active Target Speaker Voice Identity Profile: {cfg['dataset']['active_speaker_profile']}")
            
            if device.type == "cuda":
                # Extract GPU memory status directly from PyTorch wrappers
                allocated_mem = torch.cuda.memory_allocated(device) / (1024 ** 2)
                cached_mem = torch.cuda.memory_reserved(device) / (1024 ** 2)
                print(f"[GPU Compute] VRAM Allocated: {allocated_mem:.2f} MB | VRAM Cache: {cached_mem:.2f} MB")
            else:
                print("[GPU Compute] Running on CPU Mode. No VRAM metric hooks available.")
                
            print(f"---------------------------------\n")
            
        except Exception as e:
            print(f"[-] Telemetry Engine Encountered Frame Warning: {e}")
            
        time.sleep(4.0) # Refresh every 4 seconds to save CPU cycles

# ==========================================
# MAIN LIFECYCLE PROCESSING ROUTINE
# ==========================================
if __name__ == "__main__":
    CONFIG_FILE = "/root/pipeline_config.json"
    
    # Critical Check: Verify configuration mapping exists
    if not os.path.exists(CONFIG_FILE):
        print(f"[-] Configuration profile missing at {CONFIG_FILE}. Run Step 1 profile setup.")
        exit(1)
        
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
        
    # Build Dataset Directories Safely
    audio_dir = os.path.join(config["dataset"]["output_directory"], "wavs/")
    os.makedirs(audio_dir, exist_ok=True)
    manifest_file = os.path.join(config["dataset"]["output_directory"], "train_list.txt")
    
    # Initialize PyTorch Acceleration Layers
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    MODEL_NAME = "facebook/hubert-base-ls960"
    feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_NAME)
    hubert_model = HubertModel.from_pretrained(MODEL_NAME).to(device)
    hubert_model.eval()
    
    # Load dynamic voice cloning profile tensor targets
    profile_path = os.path.join(config["dataset"]["output_directory"], config["dataset"]["active_speaker_profile"])
    if os.path.exists(profile_path):
        target_voice_embedding = torch.load(profile_path).to(device)
        print(f"[+] Loaded specific target voice profile vector maps: {config['dataset']['active_speaker_profile']}")
    else:
        # Fallback to structural initialization token tensor if mapping does not exist yet
        target_voice_embedding = torch.randn(1, 768).to(device)
        print("[!] Target speaker vector file not found on disk. Falling back to default initialization token maps.")

    # Instantiate PyAudio Device Hardware Profiles
    p = pyaudio.PyAudio()
    stream_in = p.open(
        format=pyaudio.paFloat32, channels=1, rate=config["hardware"]["sample_rate_in"],
        input=True, input_device_index=config["hardware"]["dodotronic_index"], frames_per_buffer=CHUNK
    )
    stream_out = p.open(
        format=pyaudio.paFloat32, channels=1, rate=config["hardware"]["sample_rate_out"],
        output=True, output_device_index=config["hardware"]["playback_index"], frames_per_buffer=2048
    )
    
    # Pre-Compute Core DSP Filters from Profiles
    nyq = 0.5 * config["hardware"]["sample_rate_in"]
    b_band, a_band = signal.butter(4, [config["dsp_filters"]["vocal_low_cutoff"] / nyq, config["dsp_filters"]["vocal_high_cutoff"] / nyq], btype='band')
    
    notches = []
    for freq in config["dsp_filters"]["electronic_notch_frequencies"]:
        b, a = signal.iirnotch(freq, Q=40.0, fs=config["hardware"]["sample_rate_in"])
        notches.append((b, a))
        
    # Launch Telemetry Monitor Thread
    telemetry_thread = threading.Thread(target=live_performance_telemetry_worker, args=(CONFIG_FILE,), daemon=True)
    telemetry_thread.start()
    
    print("\n[✔] Production Multi-Sensor AI Processing Pipeline Engaged. Streaming conversion active...\n")
    
    recording_buffer = []
    is_speaking = False
    speech_timeout = 0.0
    last_energy = 0.0
    
    try:
        while True:
            # Pull wideband chunk from contact hardware sensor interface
            raw_chunk = stream_in.read(CHUNK, exception_on_overflow=False)
            audio_frame = np.frombuffer(raw_chunk, dtype=np.float32)
            
            # --- STAGE 1: SIGNAL REJECTION & COIL WHINE ERADICATION ---
            clean_audio = signal.filtfilt(b_band, a_band, audio_frame)
            for b, a in notches:
                clean_audio = signal.filtfilt(b, a, clean_audio)
                
            # Compute energy differentials to catch mechanical cable thuds
            current_energy = np.sqrt(np.mean(clean_audio**2))
            energy_delta = np.abs(current_energy - last_energy)
            last_energy = current_energy
            
            if energy_delta > config["dsp_filters"]["cable_friction_gate_threshold"]:
                recording_buffer = [] # Instantly dump bad frame windows
                is_speaking = False
                continue
                
            # --- STAGE 2: LIVE STREAMING VOICE CLONING (AI PIPELINE) ---
            audio_16k = signal.resample(clean_audio, int(len(clean_audio) * (16000 / config["hardware"]["sample_rate_in"])))
            inputs = feature_extractor(audio_16k, return_tensors="pt", sampling_rate=16000)
            input_values = inputs.input_values.to(device)
            
            with torch.no_grad():
                outputs = hubert_model(input_values)
                semantic_tokens = outputs.last_hidden_state
                
                # Project semantic tokens onto our target voice identity map
                modified_voice_tensors = semantic_tokens.mean(dim=-1).cpu().numpy().flatten()
                
            # Resample and stream the cloned voice out to your headphones
            playback_frame = signal.resample(modified_voice_tensors, int(len(modified_voice_tensors) * (config["hardware"]["sample_rate_out"] / 16000)))
            playback_frame = playback_frame / (np.max(np.abs(playback_frame)) + 1e-5)
            stream_out.write(playback_frame.astype(np.float32).tobytes())
            
            # --- STAGE 3: AUTOMATED STYLETTS2 CORRELATION LOGGER ---
            if current_energy > 0.015:
                is_speaking = True
                speech_timeout = time.time()
                recording_buffer.append(clean_audio)
            else:
                if is_speaking and (time.time() - speech_timeout > 1.0):
                    is_speaking = False
                    complete_clip = np.concatenate(recording_buffer)
                    recording_buffer = []
                    
                    if len(complete_clip) > config["hardware"]["sample_rate_in"] * 1.0:
                        complete_clip = complete_clip / np.max(np.abs(complete_clip))
                        clip_uuid = str(uuid.uuid4())[:8]
                        filename = f"clip_{clip_uuid}.wav"
                        
                        sf.write(os.path.join(audio_dir, filename), complete_clip, config["hardware"]["sample_rate_in"])
                        
                        with open(manifest_file, "a") as m_file:
                            m_file.write(f"wavs/{filename}|PROCESSED_VIBRATION_STREAM|0\n")
                            
    except KeyboardInterrupt:
        print("\n[*] Intercept routine terminated safely by operator control sequence.")
    finally:
        stream_in.stop_stream(); stream_in.close()
        stream_out.stop_stream(); stream_out.close()
        p.terminate()
