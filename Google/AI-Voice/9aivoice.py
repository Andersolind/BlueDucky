import os
import time
import threading
import queue
import numpy as np
import pyaudio
import scipy.signal as signal
import matplotlib.pyplot as plt

# ==========================================
# SYSTEM PARAMETERS & GEOMETRY CONSTANTS
# ==========================================
CHUNK = 4096
DODOTRONIC_SR = 192000
BUILTIN_OUT_SR = 44100
DODOTRONIC_IDX = 1  # Update via 'aplay -l'

SPEED_OF_SOUND = 343.0  # Meters per second in standard room temperature
MAX_ROOM_RADIUS = 15.0  # Maximum tracking radius in meters
GRID_RESOLUTION = 0.1   # Heat map pixel size in meters (10 cm resolution)

# Inter-thread queues
rf_trigger_queue = queue.Queue()
vector_map_queue = queue.Queue()

# ==========================================
# 1. LIVE MATPLOTLIB HEAT MAP DESIGNER
# ==========================================
def live_spatial_heat_map_renderer():
    """
    Consumes resolved multipath vectors and maps them into a 2D 
    Polar-to-Cartesian density grid to visualize physical boundaries.
    """
    plt.ion()  # Turn on interactive plotting mode
    fig, ax = plt.subplots(figsize=(8, 8))
    
    # Initialize a 2D coordinate grid representing the physical room
    grid_size = int((MAX_ROOM_RADIUS * 2) / GRID_RESOLUTION)
    spatial_grid = np.zeros((grid_size, grid_size))
    
    # Create spatial extent for visualization anchoring
    extent = [-MAX_ROOM_RADIUS, MAX_ROOM_RADIUS, -MAX_ROOM_RADIUS, MAX_ROOM_RADIUS]
    im = ax.imshow(spatial_grid, cmap='hot', origin='lower', extent=extent, vmin=0, vmax=1)
    
    ax.set_title("Live Multipath Vector Heat Map")
    ax.set_xlabel("Horizontal Distance (Meters)")
    ax.set_ylabel("Depth / Range (Meters)")
    ax.grid(color='white', linestyle='--', alpha=0.3)
    
    # Draw reference target tracking circles
    for r in:
        circle = plt.Circle((0, 0), r, color='cyan', fill=False, linestyle=':', alpha=0.5)
        ax.add_patch(circle)

    print("[+] Spatial Visualization Layer Online.")
    
    while True:
        try:
            # Pull vector bundle containing multiple resolved reflection distances
            vectors = vector_map_queue.get(timeout=1.0)
            
            # Decouple spatial tracking intensity
            new_intensities = np.zeros_like(spatial_grid)
            
            # Map distances directly into geometric grid zones (Polar projection style)
            for distance, amplitude in vectors:
                # Calculate pixel indices corresponding to this reflection range ring
                for angle in np.linspace(0, 2 * np.pi, 360):
                    x = distance * np.cos(angle)
                    y = distance * np.sin(angle)
                    
                    # Convert physical meters to pixel grid coordinates
                    grid_x = int((x + MAX_ROOM_RADIUS) / GRID_RESOLUTION)
                    grid_y = int((y + MAX_ROOM_RADIUS) / GRID_RESOLUTION)
                    
                    if 0 <= grid_x < grid_size and 0 <= grid_y < grid_size:
                        new_intensities[grid_y, grid_x] += amplitude
            
            # Apply memory persistence to the heat map (simulates phosphorescent radar display)
            spatial_grid = (spatial_grid * 0.7) + (new_intensities * 0.3)
            
            # Refresh presentation frame
            im.set_data(spatial_grid)
            im.set_clim(0, np.max(spatial_grid) * 0.8 + 0.01)
            plt.draw()
            plt.pause(0.01)
            
        except queue.Empty:
            pass

# ==========================================
# 2. HACKRF HIGH-SPEED CLOCK SNIFFER (T0)
# ==========================================
def hackrf_clock_sniffer():
    print("[+] HackRF Sync Tracker Scanning for RF Layer Triggers...")
    cmd = "hackrf_transfer -f 433920000 -s 2000000 -r - 2>/dev/null"
    pipe = os.popen(cmd, "rb")
    
    try:
        while True:
            raw_iq = pipe.read(4096)
            if not raw_iq: break
            iq = np.frombuffer(raw_iq, dtype=np.int8).astype(np.float32)
            amplitude = np.abs(iq[0::2] + 1j * iq[1::2])
            
            if np.max(amplitude) > 45.0:
                rf_trigger_queue.put(time.time())
    finally:
        pipe.close()

# ==========================================
# 3. DODOTRONIC MULTIPATH VECTOR DECODER
# ==========================================
def multipath_vector_processing_engine():
    p = pyaudio.PyAudio()
    stream_in = p.open(
        format=pyaudio.paFloat32, channels=1, rate=DODOTRONIC_SR,
        input=True, input_device_index=DODOTRONIC_IDX, frames_per_buffer=CHUNK
    )
    
    # Structural anti-noise filters
    nyquist = 0.5 * DODOTRONIC_SR
    b_hp, a_hp = signal.butter(6, 3500 / nyquist, btype='high')
    
    noise_floor_estimate = None
    alpha = 0.95
    last_t0 = None
    
    print("[+] Multipath Audio Resolution Processor Ready.")
    
    try:
        while True:
            # Check for fresh RF Sync anchor points
            try:
                last_t0 = rf_trigger_queue.get_nowait()
            except queue.Empty:
                pass

            raw_data = stream_in.read(CHUNK, exception_on_overflow=False)
            audio_frame = np.frombuffer(raw_data, dtype=np.float32)
            arrival_time = time.time()
            
            # Step 1: Apply filtering and noise subtraction
            filtered = signal.filtfilt(b_hp, a_hp, audio_frame)
            fft_frame = np.fft.rfft(filtered)
            mag = np.abs(fft_frame)
            
            if noise_floor_estimate is None:
                noise_floor_estimate = mag
            else:
                noise_floor_estimate = (alpha * noise_floor_estimate) + ((1 - alpha) * mag)
                
            cleaned_mag = np.maximum(mag - (noise_floor_estimate * 1.5), 0.0)
            cleaned_fft = cleaned_mag * np.exp(1j * np.angle(fft_frame))
            unmasked_audio = np.fft.irfft(cleaned_fft)
            
            # Step 2: Extract Envelope
            envelope = np.abs(signal.hilbert(unmasked_audio))
            
            # Step 3: Peak-Find the Multipath Echo Train
            # This isolates individual reflection boundaries within the signal stream
            peaks, properties = signal.find_peaks(envelope, height=0.10, distance=int(DODOTRONIC_SR * 0.001))
            
            if len(peaks) > 0 and last_t0 is not None:
                resolved_vectors = []
                
                for peak in peaks:
                    # Calculate sample index relative arrival timing offset
                    sample_offset_time = peak / DODOTRONIC_SR
                    exact_peak_time = (arrival_time - (CHUNK / DODOTRONIC_SR)) + sample_offset_time
                    
                    # Compute Time-of-Flight relative to the primary RF sync layer
                    tof = exact_peak_time - last_t0
                    
                    if 0 < tof < 0.1:  # Filter out unrealistic ranges (> 34 meters)
                        distance = tof * SPEED_OF_SOUND
                        amplitude = envelope[peak]
                        resolved_vectors.append((distance, amplitude))
                
                # Push verified multipath vector bundles to the display pipeline
                if len(resolved_vectors) > 0:
                    vector_map_queue.put(resolved_vectors)
                    
    finally:
        stream_in.stop_stream(); stream_in.close(); p.terminate()

# ==========================================
# LIFECYCLE MANAGEMENT ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    t_rf = threading.Thread(target=hackrf_clock_sniffer, daemon=True)
    t_audio = threading.Thread(target=multipath_vector_processing_engine, daemon=True)
    t_plot = threading.Thread(target=live_spatial_heat_map_renderer, daemon=True)
    
    t_rf.start(); t_audio.start(); t_plot.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Mapping system offline.")
