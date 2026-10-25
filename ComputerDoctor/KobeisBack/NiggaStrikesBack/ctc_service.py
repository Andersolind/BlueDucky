#!/usr/bin/env python3
import numpy as np

class AcousticCTCDemixService:
    """
    Decoupled service to reverse Acoustic Crosstalk Cancellation matrices.
    Isolates target left/right audio channels from phase-inverted acoustic meshes.
    """
    def __init__(self, delay_samples=12, crosstalk_attenuation=0.7):
        # Default delay paths approximate closely spaced stereo arrays (e.g., 10-15cm spacing)
        self.delay_samples = delay_samples
        self.alpha = crosstalk_attenuation
        
        # Buffer to keep track of previous frames for delay alignment
        self.history_buffer = np.zeros(16000, dtype=np.float32)

    def process_demix_matrix(self, blended_audio):
        """
        Reverses the recursive CTC equation.
        If Speaker_L = Target_L - (Delay * Alpha * Target_R), 
        we unmix the combined wave to recover the true sub-vocal payload.
        """
        data_len = len(blended_audio)
        if data_len == 0:
            return blended_audio, blended_audio

        # Standardize input format
        audio_np = np.array(blended_audio, dtype=np.float32)
        
        # Construct padded timeline using the history buffer
        full_signal = np.concatenate((self.history_buffer[-self.delay_samples:], audio_np))
        
        # Update the rolling history memory buffer for the next pass
        self.history_buffer = audio_np.copy()

        # Allocate empty memory paths for the extracted stereo channels
        channel_isolated_left = np.zeros(data_len, dtype=np.float32)
        channel_isolated_right = np.zeros(data_len, dtype=np.float32)

        # Loop through the block arrays to execute the cancellation matrix subtraction
        for i in range(data_len):
            # Fetch the time-aligned historical index reference point
            delayed_idx = i + self.delay_samples
            
            # Reconstruct the original non-inverted phase vectors
            # Subtracting the scaled, delayed inverse wave cancels the crosstalk layer
            channel_isolated_left[i] = full_signal[delayed_idx] + (self.alpha * full_signal[i])
            channel_isolated_right[i] = full_signal[delayed_idx] - (self.alpha * full_signal[i])

        # Normalize the outputs to avoid digital clipping blocks inside the ML vector sink
        max_val_l = np.max(np.abs(channel_isolated_left))
        max_val_r = np.max(np.abs(channel_isolated_right))
        
        if max_val_l > 0: channel_isolated_left /= max_val_l
        if max_val_r > 0: channel_isolated_right /= max_val_r

        return channel_isolated_left, channel_isolated_right
