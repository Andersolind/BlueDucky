# How to catch VAD bursts mathematically in Python
import numpy as np

def detect_vad_burst(iq_samples, threshold_db=12.0):
    # 1. Compute the immediate power envelope of this sample block
    power_block = np.abs(iq_samples)**2
    
    # 2. Calculate the peak-to-average power ratio (PAPR) or Variance
    variance = np.var(power_block)
    mean_power = np.mean(power_block)
    
    # 3. Evaluate if the sudden power jump indicates an 'ON' state burst
    if mean_power > 0:
        metric = variance / (mean_power**2)
        if metric > threshold_db:
            return True, "BURST DETECTED (Transmitter Active)"
            
    return False, "SILENCE (Transmitter Gated Off)"
