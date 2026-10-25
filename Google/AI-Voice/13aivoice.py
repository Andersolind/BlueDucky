import librosa
import torch
import numpy as np

def prepare_dodotronic_for_panns(file_path, target_sr=48000):
    """
    Downsamples the 192kHz Dodotronic data to 48kHz.
    Using an anti-aliasing filter preserves the 20kHz - 24kHz subharmonics
    while matching PANNs Cnn14 native sample expectations.
    """
    # Load and explicitly handle high sample rate
    y, sr = librosa.load(file_path, sr=None) 
    
    # Downsample cleanly to target PANNs rate
    y_resampled = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
    
    # Normalize amplitude to counter beam directionality spikes
    if np.max(np.abs(y_resampled)) > 0:
        y_resampled = y_resampled / np.max(np.abs(y_resampled))
        
    return torch.tensor(y_resampled, dtype=torch.float32).unsqueeze(0) # Add batch dimension
