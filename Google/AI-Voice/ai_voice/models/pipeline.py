"""
AI-Voice Unified Multi-Sensor & Neural Pipeline
===============================================
Orchestrates the continuous multi-sensor capture, DSP conditioning,
neural beam detection, HuBERT voice conversion, and spatial mapping loop.
"""

import time
import threading
import numpy as np
from typing import Dict, Any, Optional, Callable, List
from ai_voice.config import PipelineConfig
from ai_voice.hardware.audio import AudioHardwareManager
from ai_voice.hardware.sdr import RtlsdrManager, HackRfSyncSniffer
from ai_voice.hardware.multi_sensor import MultiSensorCaptureEngine
from ai_voice.dsp.filters import AudioFilterEngine, UltrasonicDemodulator
from ai_voice.dsp.spatial import TrajectoryInterceptor, SpatialDensityGrid
from ai_voice.dsp.resampler import AudioResampler
from ai_voice.models.panns_detector import MultiBandPANNsDetector
from ai_voice.models.hubert_converter import HubertEngine

class UnifiedAIVoicePipeline:
    """Central processing engine integrating all sensors, DSP, and neural models."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        
        # Hardware
        self.audio_mgr = AudioHardwareManager(mock_fallback=self.config.hardware.mock_hardware_if_missing)
        self.rtl_mgr = RtlsdrManager(
            frequency_hz=self.config.hardware.rtl_sdr_frequency,
            sample_rate=self.config.hardware.rtl_sdr_sample_rate,
            mock_fallback=self.config.hardware.mock_hardware_if_missing
        )
        self.hackrf_sniffer = HackRfSyncSniffer(
            frequency_hz=self.config.hardware.hackrf_sync_frequency,
            sample_rate=self.config.hardware.hackrf_sample_rate,
            mock_fallback=self.config.hardware.mock_hardware_if_missing
        )

        # DSP Engines
        self.filter_engine = AudioFilterEngine(
            sample_rate=self.config.hardware.sample_rate_in,
            config=self.config.dsp
        )
        self.ultrasound_demod = UltrasonicDemodulator(
            sample_rate=self.config.hardware.dodotronic_sample_rate,
            config=self.config.dsp
        )
        self.spatial_grid = SpatialDensityGrid(config=self.config.spatial)
        self.trajectory_interceptor = TrajectoryInterceptor(
            target_distance_init=5.0,
            velocity=-0.5,
            speed_of_sound=self.config.spatial.speed_of_sound
        )

        # Neural Models
        self.panns_detector = MultiBandPANNsDetector(num_classes=self.config.model.panns_num_classes)
        self.hubert_engine = HubertEngine(config=self.config.model)

        # State
        self.is_running = False
        self._stream_thread: Optional[threading.Thread] = None
        self.callbacks: List[Callable[[Dict[str, Any]], None]] = []
        
        # Live state cache for telemetry & UI
        self.last_state: Dict[str, Any] = {
            "timestamp": time.time(),
            "is_speaking": False,
            "vocal_energy": 0.0,
            "cable_spike_rejected": False,
            "ultrasound_peak": 0.0,
            "rtl_emi_power": 0.0,
            "panns_prediction": {"label": "Passive / Quiet Environment", "confidence": 0.99, "is_beam_active": False},
            "trajectory": {"real_distance_m": 5.0, "real_tof_ms": 14.58, "injection_delay_ms": 10.2, "state": "INJECTION_VECTOR_VALID"},
            "rf_sync_last_t0": None
        }

    def register_callback(self, cb: Callable[[Dict[str, Any]], None]):
        self.callbacks.append(cb)

    def start_streaming(self):
        if self.is_running:
            return
        self.is_running = True
        
        # Start HackRF T0 Sniffer
        def _on_t0(t0):
            self.last_state["rf_sync_last_t0"] = t0
        self.hackrf_sniffer.start(callback_on_t0=_on_t0)

        # Start Continuous Processing Thread
        self._stream_thread = threading.Thread(target=self._processing_loop, daemon=True)
        self._stream_thread.start()

    def stop_streaming(self):
        self.is_running = False
        self.hackrf_sniffer.stop()

    def _processing_loop(self):
        stream_in = self.audio_mgr.open_input_stream(
            device_index=self.config.hardware.dodotronic_index,
            sample_rate=self.config.hardware.dodotronic_sample_rate,
            chunk_size=self.config.hardware.chunk_size
        )
        stream_out = self.audio_mgr.open_output_stream(
            device_index=self.config.hardware.playback_index,
            sample_rate=self.config.hardware.sample_rate_out,
            chunk_size=int(self.config.hardware.chunk_size * (self.config.hardware.sample_rate_out / self.config.hardware.dodotronic_sample_rate))
        )

        panns_iteration = 0
        while self.is_running:
            try:
                # 1. Capture Raw Ultrasonic/Wideband Chunk
                raw_chunk = stream_in.read()
                arrival_time = time.time()

                # 2. Demodulate & Filter Ultrasound
                unmasked_audio, demod_envelope, peak_amp = self.ultrasound_demod.process_ultrasound_frame(raw_chunk)

                # 3. Check for mechanical cable spike
                is_spike, vocal_energy, _ = self.filter_engine.check_mechanical_cable_spike(demod_envelope)

                # 4. Neural PANNs Beam Detection (run every ~4 chunks to save compute)
                panns_iteration += 1
                if panns_iteration % 4 == 0:
                    panns_result = self.panns_detector.predict_audio(raw_chunk, sample_rate=self.config.hardware.dodotronic_sample_rate)
                    self.last_state["panns_prediction"] = panns_result

                # 5. Trajectory & ToF window update
                real_tof = self.trajectory_interceptor.track_and_predict_trajectory()
                traj_info = self.trajectory_interceptor.calculate_injection_window(
                    real_tof, spoof_distance=self.config.spatial.default_spoof_distance_m
                )
                self.last_state["trajectory"] = traj_info

                # 6. Spatial Multi-path Vector update
                if peak_amp > 0.05 and self.last_state["rf_sync_last_t0"] is not None:
                    tof_diff = arrival_time - self.last_state["rf_sync_last_t0"]
                    if 0 < tof_diff < 0.1:
                        dist = tof_diff * self.config.spatial.speed_of_sound
                        self.spatial_grid.update_vectors([(dist, peak_amp)])

                # 7. HuBERT Voice Conversion & Playback Stream
                if not is_spike:
                    playback_audio = self.hubert_engine.convert_voice_frame(
                        demod_envelope,
                        in_sample_rate=self.config.hardware.dodotronic_sample_rate,
                        out_sample_rate=self.config.hardware.sample_rate_out
                    )
                    stream_out.write(playback_audio)

                # 8. Update Live Telemetry State Cache
                self.last_state.update({
                    "timestamp": arrival_time,
                    "is_speaking": bool(vocal_energy > self.config.dsp.speech_energy_threshold),
                    "vocal_energy": float(vocal_energy),
                    "cable_spike_rejected": bool(is_spike),
                    "ultrasound_peak": float(peak_amp),
                })

                # Notify callbacks
                for cb in self.callbacks:
                    try:
                        cb(self.last_state)
                    except Exception:
                        pass

            except Exception as e:
                time.sleep(0.01)

        stream_in.close()
        stream_out.close()

    def run_single_batch_inference(self, duration_sec: float = 3.0) -> Dict[str, Any]:
        """Runs a synchronous multi-sensor batch and performs full neural inference."""
        capture_engine = MultiSensorCaptureEngine(self.config.hardware)
        batch = capture_engine.capture_batch_window(duration_sec)
        capture_engine.close()

        # Run PANNs inference on ultrasonic channel
        ult_data = batch["ultrasound"]
        if ult_data is not None and len(ult_data) > 0:
            panns_pred = self.panns_detector.predict_audio(ult_data, sample_rate=batch["ultrasound_sr"])
        else:
            panns_pred = {"label": "No Ultrasonic Signal", "confidence": 0.0, "is_beam_active": False}

        # Run HuBERT tokenization on audible channel
        aud_data = batch["audible"]
        if aud_data is not None and len(aud_data) > 0:
            aud_16k = AudioResampler.prepare_for_hubert(aud_data, batch["audible_sr"])
            hubert_tokens = self.hubert_engine.extract_semantic_tokens(aud_16k)
            token_shape = list(hubert_tokens.shape)
        else:
            token_shape = []

        return {
            "timestamp": batch["timestamp"],
            "duration_sec": duration_sec,
            "rtl_emi_power": batch["rtl_emi_power"],
            "rf_t0_count": batch["rf_t0_count"],
            "panns_prediction": panns_pred,
            "hubert_token_shape": token_shape,
            "files": batch["files"]
        }
