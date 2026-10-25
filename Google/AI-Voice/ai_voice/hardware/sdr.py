"""
AI-Voice Software-Defined Radio (SDR) Abstraction
=================================================
Manages:
1. RTL-SDR V4: Low-frequency transducer EMI leakage capture (e.g. 150 kHz).
2. HackRF One: High-speed RF layer synchronization pulse detector (T0 clock at 433.92 MHz).
3. Fallback mock generator for testing in hardware-constrained environments.
"""

import os
import time
import subprocess
import threading
import numpy as np
from typing import Optional, Tuple, Dict, Any

try:
    from rtlsdr import RtlSdr
    HAS_RTLSDR = True
except ImportError:
    HAS_RTLSDR = False

class RtlsdrManager:
    """Captures RF/EMI emissions from parametric acoustic transducers."""

    def __init__(self, frequency_hz: int = 150000, sample_rate: int = 2048000, mock_fallback: bool = True):
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.mock_fallback = mock_fallback

    def record_samples(self, duration_sec: float) -> Tuple[np.ndarray, float]:
        """
        Reads IQ samples over a duration window.
        Returns: (iq_samples, signal_power)
        """
        num_samples = int(self.sample_rate * duration_sec)
        
        if HAS_RTLSDR:
            try:
                sdr = RtlSdr()
                sdr.sample_rate = self.sample_rate
                sdr.center_freq = self.frequency_hz
                sdr.gain = 'auto'
                samples = sdr.read_samples(num_samples)
                sdr.close()
                iq = np.array(samples, dtype=np.complex64)
                power = float(np.mean(np.abs(iq)**2))
                return iq, power
            except Exception:
                if not self.mock_fallback:
                    raise

        # Mock fallback: Generate realistic RF noise floor with intermittent EMI burst
        t = np.linspace(0, duration_sec, num_samples, endpoint=False)
        noise = (np.random.normal(0, 0.02, num_samples) + 1j * np.random.normal(0, 0.02, num_samples)).astype(np.complex64)
        # Add intermittent EMI spike
        spike_mod = 0.1 * np.sin(2 * np.pi * 5.0 * t)**4
        iq = (noise + spike_mod).astype(np.complex64)
        power = float(np.mean(np.abs(iq)**2))
        return iq, power


class HackRfSyncSniffer:
    """
    Sniffs high-speed RF sync pulses (T0 anchor triggers, e.g. at 433.92 MHz)
    using hackrf_transfer streaming pipe or synthetic triggers.
    """

    def __init__(self, frequency_hz: int = 433920000, sample_rate: int = 2000000, threshold: float = 45.0, mock_fallback: bool = True):
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.mock_fallback = mock_fallback
        self.is_running = False
        self.last_t0: Optional[float] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, callback_on_t0=None):
        self.is_running = True
        self._thread = threading.Thread(target=self._sniffer_loop, args=(callback_on_t0,), daemon=True)
        self._thread.start()

    def stop(self):
        self.is_running = False

    def _sniffer_loop(self, callback_on_t0):
        # Attempt physical hackrf_transfer command
        cmd = f"hackrf_transfer -f {self.frequency_hz} -s {self.sample_rate} -r - 2>/dev/null"
        pipe = None
        try:
            pipe = os.popen(cmd, "rb")
        except Exception:
            pipe = None

        if pipe is None or not self._is_pipe_responsive(pipe):
            if pipe:
                pipe.close()
            self._mock_loop(callback_on_t0)
            return

        try:
            while self.is_running:
                raw_iq = pipe.read(4096)
                if not raw_iq:
                    break
                iq_data = np.frombuffer(raw_iq, dtype=np.int8).astype(np.float32)
                if len(iq_data) < 2:
                    continue
                amplitude = np.abs(iq_data[0::2] + 1j * iq_data[1::2])
                if np.max(amplitude) > self.threshold:
                    t0 = time.time()
                    self.last_t0 = t0
                    if callback_on_t0:
                        callback_on_t0(t0)
        except Exception:
            pass
        finally:
            if pipe:
                try:
                    pipe.close()
                except Exception:
                    pass

    def _is_pipe_responsive(self, pipe) -> bool:
        # Check if hackrf_transfer is actually returning data
        try:
            raw = pipe.read(256)
            return len(raw) > 0
        except Exception:
            return False

    def _mock_loop(self, callback_on_t0):
        """Simulates periodic RF T0 pulses every ~1.5 - 3.0 seconds."""
        while self.is_running:
            time.sleep(2.0 + np.random.uniform(-0.5, 0.5))
            if not self.is_running:
                break
            t0 = time.time()
            self.last_t0 = t0
            if callback_on_t0:
                callback_on_t0(t0)

    def record_sync_burst(self, duration_sec: float, output_path: str):
        """Captures a sync burst file using hackrf_transfer."""
        samples_count = int(self.sample_rate * duration_sec)
        cmd = f"hackrf_transfer -r {output_path} -f {self.frequency_hz} -s {self.sample_rate} -n {samples_count} > /dev/null 2>&1"
        try:
            subprocess.run(cmd, shell=True, timeout=duration_sec + 2.0)
        except Exception:
            # Fallback to dummy file
            with open(output_path, "wb") as f:
                f.write(np.random.bytes(samples_count * 2))
