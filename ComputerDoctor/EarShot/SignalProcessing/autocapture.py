#!/usr/bin/env python3
import sys
import time
import numpy as np
import osmosdr
from gnuradio import gr
from gnuradio import blocks  # <-- Fix 1: Explicitly import the blocks module

def auto_capture_center_freq(search_center_mhz=27.12, search_bandwidth_mhz=2.0):
    """
    Scans the local airwaves around a target band, performs an FFT analysis,
    and automatically finds the exact frequency of the strongest live carrier.
    """
    samp_rate = int(search_bandwidth_mhz * 1e6)
    center_hz = int(search_center_mhz * 1e6)
    
    print(f"[*] Initializing Wideband Scan around {search_center_mhz} MHz...")
    
    # Initialize hardware source safely
    src = osmosdr.source(args="numchan=1 hackrf=0")
    src.set_sample_rate(samp_rate)
    src.set_center_freq(center_hz, 0)
    src.set_gain(10, 0)
    src.set_if_gain(24, 0)
    
    # Fix 2: Call the module directly without the 'gr.' prefix
    num_samples = 4096
    snk = blocks.vector_sink_c()
    
    # Flowgraph execution setup
    tb = gr.top_block()
    tb.connect(src, snk)
    
    # Run briefly to collect samples, then immediately halt hardware
    tb.start()
    time.sleep(0.5) 
    tb.stop()
    tb.wait()
    
    # Extract data from the buffer matrix
    raw_data = np.array(snk.data())
    if len(raw_data) < num_samples:
        print("[-] Error: Insufficient RF samples captured.")
        return None
        
    # Perform Fast Fourier Transform (FFT)
    fft_data = np.fft.fftshift(np.fft.fft(raw_data[:num_samples]))
    power_spectrum = 10 * np.log10(np.abs(fft_data)**2 + 1e-12)
    
    # Map array indices to absolute physical frequencies
    frequencies = np.fft.fftshift(np.fft.fftfreq(num_samples, d=1.0/samp_rate)) + center_hz
    
    # Find the maximum power index
    peak_index = np.argmax(power_spectrum)
    detected_freq_hz = frequencies[peak_index]
    peak_power = power_spectrum[peak_index]
    
    print("\n" + "="*50)
    print("=== AUTO-CAPTURE ANALYSIS COMPLETE ===")
    print("="*50)
    print(f"Detected Live Center Frequency: {detected_freq_hz / 1e6:.4f} MHz")
    print(f"Peak Carrier Signal Amplitude:  {peak_power:.2f} dB")
    print("="*50)
    
    return detected_freq_hz

if __name__ == '__main__':
    # Run the auto-scan function
    detected_center = auto_capture_center_freq(search_center_mhz=27.12, search_bandwidth_mhz=2.0)
