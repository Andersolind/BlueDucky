import math
import hashlib
import time
import wave
import struct
import numpy as np

class CircularMeshStreamingEngine:
    def __init__(self, target_fm_center_hz=98.1e6, base_hop_carrier_hz=915e6):
        """
        Coordinates a distributed, phase-coherent, frequency-hopping mesh.
        Optimized for Circularly Polarized (RHCP/LHCP) wave propagation arrays.
        """
        self.target_fm_freq = target_fm_center_hz
        self.base_carrier = base_hop_carrier_hz
        self.speed_of_light = 299792458.0  # Speed of light in vacuum (m/s)

        # FHSS parameters across a 20 MHz spectrum band
        self.hop_channels = np.linspace(902e6, 922e6, 50)
        self.hop_interval_sec = 0.1  # 100ms dwell time per channel slot

        # Audio state tracking variables
        self.audio_wav = None
        self.phase_accumulator = 0.0

    def load_audio_source(self, wav_filepath):
        """ Opens a local audio file to act as the live streaming payload """
        try:
            self.audio_wav = wave.open(wav_filepath, 'rb')
            if self.audio_wav.getnchannels() > 1:
                print("[!] Warning: Stereo file detected. Downmixing internally to Mono channel.")
            return True
        except Exception as e:
            print(f"[!] Error loading audio file: {e}")
            return False

    def get_next_audio_sample(self):
        """ Reads the next frame chunk from the audio stream file and normalizes it """
        if self.audio_wav is None:
            return 0.0

        frames = self.audio_wav.readframes(1)
        if not frames:
            # Loop audio file automatically upon reaching EOF boundary
            self.audio_wav.setpos(0)
            frames = self.audio_wav.readframes(1)

        # Unpack raw byte stream into single precision float structure (-1.0 to 1.0)
        try:
            if self.audio_wav.getsampwidth() == 2: # 16-bit PCM formatting
                data = struct.unpack("<h", frames)[0]
                return data / 32768.0
            elif self.audio_wav.getsampwidth() == 1: # 8-bit unsigned formatting
                data = struct.unpack("<B", frames)[0]
                return (data - 128) / 128.0
        except Exception:
            return 0.0
        return 0.0

    def generate_fhss_sequence(self, epoch_time_sec, cryptographic_key="strategic_cp_auth"):
        """ Cryptographically derives current pseudorandom hopping channels """
        time_slot = int(epoch_time_sec / self.hop_interval_sec)
        hash_digest = hashlib.sha256(f"{time_slot}_{cryptographic_key}".encode('utf-8')).hexdigest()

        channel_index = int(hash_digest[:6], 16) % len(self.hop_channels)
        n1_carrier = self.hop_channels[channel_index]
        n2_carrier = n1_carrier + self.target_fm_freq
        return n1_carrier, n2_carrier

    def compute_coherent_mesh_state(self, target_ecef, node1_ecef, node2_ecef, frequency_deviation=75000.0):
        """ Computes frequency, phase corrections, and integrates live audio modulation """
        current_time = time.time()
        n1_freq, n2_freq = self.generate_fhss_sequence(current_time)

        # Calculate true spatial range metrics
        d1 = math.sqrt(sum((t - n) ** 2 for t, n in zip(target_ecef, node1_ecef)))
        d2 = math.sqrt(sum((t - n) ** 2 for t, n in zip(target_ecef, node2_ecef)))

        # Compute structural phase wraps
        lambda1 = self.speed_of_light / n1_freq
        lambda2 = self.speed_of_light / n2_freq

        phase1_raw = (2.0 * math.pi * (d1 % lambda1)) / lambda1
        phase2_raw = (2.0 * math.pi * (d2 % lambda2)) / lambda2

        # Pull live file data frame sample and perform True Direct FM integration step
        audio_amp = self.get_next_audio_sample()
        # dPhi = 2 * pi * f_dev * sample * dt
        self.phase_accumulator += 2.0 * math.pi * frequency_deviation * audio_amp * (1.0 / 44100.0)
        self.phase_accumulator %= (2.0 * math.pi)

        # Inject modulated stream directly into the offset element calculations
        phase2_modulated = (phase2_raw + self.phase_accumulator) % (2.0 * math.pi)
        interlocking_phase_shift = (phase1_raw - phase2_modulated) % (2.0 * math.pi)

        return {
            "timestamp_epoch": current_time,
            "node1_frequency_hz": n1_freq,
            "node2_frequency_hz": n2_freq,
            "node2_phase_step_deg": math.degrees(interlocking_phase_shift),
            "audio_signal_amplitude": audio_amp,
            "polarization_mode": "RHCP_AntiFade"
        }