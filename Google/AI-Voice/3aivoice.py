import os
import pandas as pd
import torch
import torchaudio
from transformers import HubertModel, Wav2Vec2FeatureExtractor

# Initialize processing devices
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"[*] AI Features System Online. Running on: {device.type.upper()}")

# Load Facebook/HuBERT Base model designed for semantic speech decoding
MODEL_NAME = "facebook/hubert-base-ls960"
feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_NAME)
hubert_model = HubertModel.from_pretrained(MODEL_NAME).to(device)
hubert_model.eval()

# Directory definitions matching your logger setup
DATASET_DIR = "/root/hubert_training_set/"
AUDIO_DIR = os.path.join(DATASET_DIR, "wavs/")
MANIFEST_PATH = os.path.join(DATASET_DIR, "metadata.csv")

if os.path.exists(MANIFEST_PATH):
    df = pd.read_csv(MANIFEST_PATH)
    print(f"[+] Loaded manifest index. Found {len(df)} structural speech records.")
    
    for idx, row in df.iterrows():
        wav_path = os.path.join(AUDIO_DIR, row['audio_file'])
        
        if os.path.exists(wav_path):
            # Load your isolated vibration wav file
            waveform, sample_rate = torchaudio.load(wav_path)
            
            # HuBERT requires precisely 16kHz audio input to map its semantic matrices
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
                waveform = resampler(waveform)
                
            # Process waveform through the AI tokenizer layers
            inputs = feature_extractor(waveform.squeeze(0), return_tensors="pt", sampling_rate=16000)
            input_values = inputs.input_values.to(device)
            
            with torch.no_grad():
                # Extract the hidden states output layers
                outputs = hubert_model(input_values)
                # This matrix represents the true content vector, free from background room noise
                hidden_states = outputs.last_hidden_state
                
            print(f"    [Tokenized] {row['audio_file']} ──► Internal Semantic Shape Tensor: {list(hidden_states.shape)}")
            
            # Save tokenized array directly next to the audio for your generative training engine
            tensor_save_path = os.path.join(AUDIO_DIR, row['audio_file'].replace(".wav", ".pt"))
            torch.save(hidden_states.cpu(), tensor_save_path)
            
    print("\n[✔] Data Tokenization Complete. Vectors are prepared for AI voice cloning.")
else:
    print("[-] Error: Metadata index manifest not found. Run the recording stream logger first.")
