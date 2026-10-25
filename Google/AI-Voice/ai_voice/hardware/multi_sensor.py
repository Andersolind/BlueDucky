"""
AI-Voice Multi-Sensor Capture Orchestrator
==========================================
Synchronizes asynchronous parallel captures across:
- Audible Microphones (44.1 kHz / 48 kHz)
- Dodotronic Ultrasonic Sensor (192 kHz)
- RTL-SDR EMI Receiver (150 kHz)
- HackRF One RF Sync Sniffer (433.92 MHz)
"""

import os
import time
import queue
import threading
import numpy as np
import soundfile as sf
from typing import Dict, Any, Optional, Tuple, Callable
from ai_voice.config import HardwareConfig
from ai_voice.hardware.audio import AudioHardwareManager
from ai_voice.hardware.sdr import RtlsdrManager, HackRfSyncSniffer

class MultiSensorCaptureEngine:
    """Orchestrates synchronized multi-sensor batch and streaming captures."""

    def __init__(self, config: Optional[HardwareConfig] = None):
        self.config = config or HardwareConfig()
        self.audio_mgr = AudioHardwareManager(mock_fallback=self.config.mock_hardware_if_missing)
        self.rtl_mgr = RtlsdrManager(
            frequency_hz=self.config.rtl_sdr_frequency,
            sample_rate=self.config.rtl_sdr_sample_rate,
            mock_fallback=self.config.mock_hardware_if_missing
        )
        self.hackrf_sniffer = HackRfSyncSniffer(
            frequency_hz=self.config.hackrf_sync_frequency,
            sample_rate=self.config.hackrf_sample_rate,
            mock_fallback=self.config.mock_hardware_if_missing
        )
        
        self.t0_queue: queue.Queue = queue.Queue(maxsize=100)
        self.event_callbacks: list = []

    def start_rf_sync_sniffer(self):
        def _on_t0(t0):
            try:
                self.t0_queue.put_nowait(t0)
            except queue.Full:
                pass
            for cb in self.event_callbacks:
                try:
                    cb("rf_sync", {"t0": t0, "freq": self.config.hackrf_sync_frequency})
                except Exception:
                    pass

        self.hackrf_sniffer.start(callback_on_t0=_on_t0)

    def stop_rf_sync_sniffer(self):
        self.hackrf_sniffer.stop()

    def register_callback(self, callback: Callable):
        self.event_callbacks.append(callback)

    def capture_batch_window(self, duration_sec: float, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes parallel multi-domain capture across all sensor paths for duration_sec.
        Returns dictionary containing audio waveforms, sample rates, EMI power, and timing.
        """
        results: Dict[str, Any] = {
            "timestamp": time.time(),
            "duration_sec": duration_sec,
            "audible": None,
            "ultrasound": None,
            "rtl_emi_power": 0.0,
            "rf_t0_count": 0,
            "files": {}
        }

        # 1. Parallel Capture Threads
        audible_frames = []
        ultrasound_frames = []
        rtl_holder = {}

        def record_audible():
            stream = self.audio_mgr.open_input_stream(
                device_index=self.config.builtin_mic_index,
                sample_rate=self.config.builtin_sample_rate,
                chunk_size=self.config.chunk_size
            )
            total_chunks = max(1, int(duration_sec * self.config.builtin_sample_rate / self.config.chunk_size))
            for _ in range(total_chunks):
                audible_frames.append(stream.read())
            stream.close()

        def record_ultrasound():
            stream = self.audio_mgr.open_input_stream(
                device_index=self.config.dodotronic_index,
                sample_rate=self.config.dodotronic_sample_rate,
                chunk_size=self.config.chunk_size
            )
            total_chunks = max(1, int(duration_sec * self.config.dodotronic_sample_rate / self.config.chunk_size))
            for _ in range(total_chunks):
                ultrasound_frames.append(stream.read())
            stream.close()

        def record_rtl():
            iq, power = self.rtl_mgr.record_samples(duration_sec)
            rtl_holder["iq"] = iq
            rtl_holder["power"] = power

        t_aud = threading.Thread(target=record_audible)
        t_ult = threading.Thread(target=record_ultrasound)
        t_rtl = threading.Thread(target=record_rtl)

        t_aud.start()
        t_ult.start()
        t_rtl.start()

        t_aud.join()
        t_ult.join()
        t_rtl.join()

        # Combine arrays
        if audible_frames:
            audible_data = np.concatenate(audible_frames)
            results["audible"] = audible_data
            results["audible_sr"] = self.config.builtin_sample_rate
        if ultrasound_frames:
            ultrasound_data = np.concatenate(ultrasound_frames)
            results["ultrasound"] = ultrasound_data
            results["ultrasound_sr"] = self.config.dodotronic_sample_rate
        
        results["rtl_emi_power"] = float(rtl_holder.get("power", 0.0))

        # Check for RF Sync events during window
        t0_events = []
        while not self.t0_queue.empty():
            try:
                t0_events.append(self.t0_queue.get_nowait())
            except queue.Empty:
                break
        results["rf_t0_count"] = len(t0_events)
        results["rf_t0_events"] = t0_events

        # Save files if directory specified
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            batch_id = int(time.time() * 1000)
            if results["audible"] is not None:
                aud_file = os.path.join(output_dir, f"batch_{batch_id}_audible.wav")
                sf.write(aud_file, results["audible"], self.config.builtin_sample_rate)
                results["files"]["audible"] = aud_file
            if results["ultrasound"] is not None:
                ult_file = os.path.join(output_dir, f"batch_{batch_id}_ultrasound.wav")
                sf.write(ult_file, results["ultrasound"], self.config.dodotronic_sample_rate)
                results["files"]["ultrasound"] = ult_file
            if "iq" in rtl_holder:
                rtl_file = os.path.join(output_dir, f"batch_{batch_id}_rtl.npy")
                np.save(rtl_file, rtl_holder["iq"])
                results["files"]["rtl"] = rtl_file

        return results

    def close(self):
        self.stop_rf_sync_sniffer()
        self.audio_mgr.close()
