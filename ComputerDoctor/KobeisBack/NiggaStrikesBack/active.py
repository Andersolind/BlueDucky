import time
import numpy as np
import sys
try:
    from pyhackrf import HackRF
    HACKRF_AVAILABLE = True
except ImportError:
    HACKRF_AVAILABLE = False

class HackRFActiveMeshEmitter:
    def __init__(self, base_hop_carrier_hz=915e6, target_fm_freq_hz=98.1e6):
        self.base_carrier = base_hop_carrier_hz
        self.target_fm_freq = target_fm_freq_hz
        self.hop_channels = np.linspace(902e6, 922e6, 50)
        self.hop_interval_sec = 0.1 
        self.phase_accumulator = 0.0
        self.is_transmitting = False
        self.hrf = None

    def generate_iq_frame(self, sample_rate):
        current_time = time.time()
        channel_index = int(current_time // self.hop_interval_sec) % len(self.hop_channels)
        active_carrier = self.hop_channels[channel_index] + self.target_fm_freq

        delta_t = 1.0 / sample_rate
        self.phase_accumulator += 2.0 * np.pi * active_carrier * delta_t
        
        return complex(np.cos(self.phase_accumulator), np.sin(self.phase_accumulator))

    def _tx_callback(self, device, buffer_length, user_data):
        sample_rate = user_data['sample_rate']
        iq_bytes = np.zeros(buffer_length, dtype=np.int8)
        
        for i in range(0, buffer_length, 2):
            complex_sample = self.generate_iq_frame(sample_rate)
            iq_bytes[i] = int(max(-127, min(127, complex_sample.real * 127)))
            iq_bytes[i+1] = int(max(-127, min(127, complex_sample.imag * 127)))
        return iq_bytes.tobytes()

    def start(self):
        if not HACKRF_AVAILABLE:
            print("[!] HackRF drivers (pyhackrf) missing. Simulating active transmission loop...")
            while True: time.sleep(1)
        try:
            print("[*] Initializing HackRF One transmitter...")
            self.hrf = HackRF()
            self.hrf.set_sample_rate(20000000)
            self.hrf.set_txvga_gain(30)
            self.is_transmitting = True
            self.hrf.start_tx(self._tx_callback, {'sample_rate': 20000000})
            print("[+] HackRF One actively emitting phase-coherent stimulus matrix.")
            while self.is_transmitting: time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.is_transmitting = False
        if self.hrf:
            self.hrf.stop_tx()
            self.hrf.close()
            print("[*] HackRF hardware safely unmounted.")

if __name__ == "__main__":
    emitter = HackRFActiveMeshEmitter()
    try:
        emitter.start()
    except KeyboardInterrupt:
        emitter.stop()
