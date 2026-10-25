#!/usr/bin/env python3
import subprocess
import time
import os
import sys

def check_root():
    """Ensure the script runs with privileges if modifying audio modules."""
    if os.geteuid() != 0:
        print("[!] Please run this script with sudo to ensure hardware/audio access.")
        sys.exit(1)

def setup_audio_loopback():
    print("[*] Configuring PipeWire/PulseAudio Loopback...")
    try:
        # Load the loopback module to route SDR output to a virtual microphone source
        subprocess.run(["pactl", "load-module", "module-loopback", "latency_msec=10"], check=True)
        print("[+] Audio loopback module successfully loaded.")
    except subprocess.CalledProcessError:
        print("[-] Warning: Failed to load loopback module. It might already be active.")

def launch_visualizers():
    print("[*] Launching Baudline Spectrogram...")
    # Launch Baudline in the background listening to the standard pulse device
    baudline_cmd = "baudline -channels 1 -samplerate 48000"
    subprocess.Popen(baudline_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Small pause to allow the audio system to settle before opening the RF side
    time.sleep(2)
    
    print("[*] Launching SDR++ (Spectrum Hunter)...")
    # Launch SDR++ in the background. It will automatically detect your HackRF / RTL-SDR
    sdr_cmd = "sdrpp"
    subprocess.Popen(sdr_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    print("====================================================")
    print("      AUTOMATED SDR VISUALIZATION WORKSPACE         ")
    print("====================================================")
    
    # 1. Setup Audio Engine
    setup_audio_loopback()
    
    # 2. Launch Graphical Applications
    launch_visualizers()
    
    print("\n[+] Both applications have been initialized.")
    print("[i] Adjust SDR++ audio output to feed your System Loopback.")
    print("[i] Watch Baudline for the VAD edges and multipath ghost echoes.")
    print("====================================================")

if __name__ == "__main__":
    # Check for display environment (ensures user is running inside an active desktop session)
    if "DISPLAY" not in os.environ:
        print("[!] Error: This script must be run inside a graphical X11/Wayland environment.")
        sys.exit(1)
        
    main()
