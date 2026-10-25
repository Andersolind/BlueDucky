"""
AI-Voice Audio Hardware Abstraction
===================================
Manages multi-channel audio capture (Audible Microphones, Dodotronic 192kHz Ultrasound,
Contact/Bone-Conduction Microphones) and system playback interfaces.
Provides transparent synthetic stream emulation if physical hardware is absent.
"""

import time
import numpy as np
from typing import List, Dict, Any, Optional, Tuple

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

class AudioHardwareManager:
    """Manages audio device enumeration and PyAudio input/output streams."""

    def __init__(self, mock_fallback: bool = True):
        self.mock_fallback = mock_fallback
        self.p: Optional[Any] = None
        if HAS_PYAUDIO:
            try:
                self.p = pyaudio.PyAudio()
            except Exception:
                self.p = None

    def list_devices(self) -> List[Dict[str, Any]]:
        """Returns a list of all audio devices available on the host."""
        devices = []
        if self.p is None:
            return [{"index": 0, "name": "Simulated Virtual Microphone (Loopback)", "inputs": 2, "outputs": 2, "rate": 48000}]

        try:
            for i in range(self.p.get_device_count()):
                try:
                    info = self.p.get_device_info_by_index(i)
                    devices.append({
                        "index": i,
                        "name": info.get("name", f"Device {i}"),
                        "inputs": info.get("maxInputChannels", 0),
                        "outputs": info.get("maxOutputChannels", 0),
                        "rate": int(info.get("defaultSampleRate", 44100))
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return devices

    def find_dodotronic_index(self) -> Optional[int]:
        """Scans device list for Dodotronic / UltraMic keywords."""
        for dev in self.list_devices():
            name = dev["name"].lower()
            if any(k in name for k in ["dodotronic", "ultramic", "ultrasonic", "contact"]):
                return dev["index"]
        return None

    def open_input_stream(self, device_index: int, sample_rate: int, chunk_size: int = 2048, channels: int = 1):
        """Opens a PyAudio input stream or returns a MockAudioStream."""
        if self.p is not None:
            try:
                stream = self.p.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=chunk_size
                )
                return LiveAudioStream(stream, sample_rate, chunk_size)
            except Exception as e:
                if not self.mock_fallback:
                    raise RuntimeError(f"Failed to open audio device {device_index}: {e}")

        # Fallback to Mock Stream
        return MockAudioStream(sample_rate=sample_rate, chunk_size=chunk_size, is_ultrasound=(sample_rate > 96000))

    def open_output_stream(self, device_index: int, sample_rate: int, chunk_size: int = 2048, channels: int = 1):
        """Opens a PyAudio output stream or returns a MockAudioOutputStream."""
        if self.p is not None:
            try:
                stream = self.p.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    output=True,
                    output_device_index=device_index,
                    frames_per_buffer=chunk_size
                )
                return LiveAudioOutputStream(stream)
            except Exception as e:
                if not self.mock_fallback:
                    raise RuntimeError(f"Failed to open audio playback device {device_index}: {e}")

        return MockAudioOutputStream()

    def close(self):
        if self.p is not None:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None


class LiveAudioStream:
    """Wrapper around live PyAudio input stream."""

    def __init__(self, stream: Any, sample_rate: int, chunk_size: int):
        self.stream = stream
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.is_active = True

    def read(self) -> np.ndarray:
        if not self.is_active:
            return np.zeros(self.chunk_size, dtype=np.float32)
        try:
            raw = self.stream.read(self.chunk_size, exception_on_overflow=False)
            return np.frombuffer(raw, dtype=np.float32)
        except Exception:
            return np.zeros(self.chunk_size, dtype=np.float32)

    def close(self):
        if self.is_active:
            self.is_active = False
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass


class LiveAudioOutputStream:
    """Wrapper around live PyAudio output stream."""

    def __init__(self, stream: Any):
        self.stream = stream
        self.is_active = True

    def write(self, audio_data: np.ndarray):
        if not self.is_active:
            return
        try:
            self.stream.write(audio_data.astype(np.float32).tobytes())
        except Exception:
            pass

    def close(self):
        if self.is_active:
            self.is_active = False
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass


class MockAudioStream:
    """Generates realistic synthetic audio / ultrasound signals for testing."""

    def __init__(self, sample_rate: int, chunk_size: int, is_ultrasound: bool = False):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.is_ultrasound = is_ultrasound
        self.t = 0.0
        self.dt = chunk_size / sample_rate
        self.is_active = True

    def read(self) -> np.ndarray:
        if not self.is_active:
            return np.zeros(self.chunk_size, dtype=np.float32)
        
        # Sleep for chunk duration to simulate real-time audio clock
        time.sleep(self.dt * 0.95)
        self.t += self.dt

        t_vec = np.linspace(self.t, self.t + self.dt, self.chunk_size, endpoint=False)
        noise = np.random.normal(0, 0.005, self.chunk_size).astype(np.float32)

        if self.is_ultrasound:
            # Generate simulated ultrasonic carrier (e.g. 25 kHz - 40 kHz acoustic beam pulse)
            carrier = 0.15 * np.sin(2 * np.pi * 32000 * t_vec)
            # Add intermittent modulation pulse
            pulse_mod = 0.5 * (1.0 + np.sin(2 * np.pi * 2.5 * t_vec))
            signal_out = (carrier * pulse_mod + noise).astype(np.float32)
        else:
            # Generate simulated voice formant tone + 60Hz hum + coil whine
            vocal = 0.08 * np.sin(2 * np.pi * 220 * t_vec) + 0.04 * np.sin(2 * np.pi * 440 * t_vec)
            hum = 0.02 * np.sin(2 * np.pi * 60 * t_vec)
            whine = 0.01 * np.sin(2 * np.pi * 4000 * t_vec)
            signal_out = (vocal + hum + whine + noise).astype(np.float32)

        return signal_out

    def close(self):
        self.is_active = False


class MockAudioOutputStream:
    """Mock audio playback sink."""

    def write(self, audio_data: np.ndarray):
        pass

    def close(self):
        pass
