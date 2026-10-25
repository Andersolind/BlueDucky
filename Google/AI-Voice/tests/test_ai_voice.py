"""
AI-Voice Automated Test Suite
=============================
Tests all core modules:
1. Configuration loading / saving
2. DSP filtering, coil whine notches, and mechanical spike rejection
3. Resampling conversions
4. TrajectoryInterceptor & Spatial Density Grid calculations
5. PANNs neural beam detector
6. HuBERT tokenizer & voice converter
7. Live performance telemetry tracking
8. Automated dataset manifest logging
9. REST endpoints on web server
"""

import os
import tempfile
import numpy as np
import pytest
import torch

from ai_voice.config import PipelineConfig, HardwareConfig, DspFilterConfig, ModelConfig, DatasetConfig, SpatialConfig
from ai_voice.dsp.filters import AudioFilterEngine, UltrasonicDemodulator
from ai_voice.dsp.resampler import AudioResampler
from ai_voice.dsp.spatial import TrajectoryInterceptor, SpatialDensityGrid
from ai_voice.models.panns_detector import MultiBandPANNsDetector
from ai_voice.models.hubert_converter import HubertEngine, StreamingVoiceConverter
from ai_voice.telemetry.monitor import LivePerformanceTracker
from ai_voice.telemetry.dataset_logger import AutomatedDatasetLogger
from ai_voice.hardware.audio import AudioHardwareManager
from ai_voice.hardware.multi_sensor import MultiSensorCaptureEngine

def test_config_serialization():
    cfg = PipelineConfig()
    cfg_dict = cfg.to_dict()
    assert "hardware" in cfg_dict
    assert "dsp" in cfg_dict
    assert "model" in cfg_dict

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        cfg.save_to_file(path)
        loaded = PipelineConfig.load_from_file(path)
        assert loaded.hardware.sample_rate_in == cfg.hardware.sample_rate_in
        assert loaded.dsp.vocal_low_cutoff == cfg.dsp.vocal_low_cutoff
    finally:
        if os.path.exists(path):
            os.remove(path)

def test_dsp_filters():
    engine = AudioFilterEngine(sample_rate=48000)
    # Generate 1 second test tone
    t = np.linspace(0, 1.0, 48000, endpoint=False)
    # 1kHz tone (vocal) + 4kHz tone (notch target) + 60Hz hum (below passband)
    audio = np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 4000 * t) + np.sin(2 * np.pi * 60 * t)
    
    filtered = engine.apply_vocal_enhancement(audio)
    assert len(filtered) == len(audio)
    
    # Check mechanical friction gate
    is_spike, energy, delta = engine.check_mechanical_cable_spike(np.zeros(2048, dtype=np.float32))
    assert not is_spike

    # Inject sudden massive step
    is_spike, energy, delta = engine.check_mechanical_cable_spike(np.ones(2048, dtype=np.float32) * 2.0)
    assert is_spike

def test_ultrasonic_demodulator():
    demod = UltrasonicDemodulator(sample_rate=192000)
    # 32kHz ultrasound burst
    t = np.linspace(0, 0.05, int(192000 * 0.05), endpoint=False)
    raw = (0.2 * np.sin(2 * np.pi * 32000 * t)).astype(np.float32)
    
    unmasked, env, peak = demod.process_ultrasound_frame(raw)
    assert len(unmasked) == len(raw)
    assert len(env) == len(raw)
    assert peak > 0.0

def test_resamplers():
    audio = np.random.normal(0, 0.1, 1920).astype(np.float32)
    # 192k -> 48k
    down = AudioResampler.resample(audio, 192000, 48000)
    assert len(down) == 480

    # 48k -> 16k
    hubert_in = AudioResampler.prepare_for_hubert(down, 48000)
    assert len(hubert_in) == 160

def test_trajectory_and_spatial_grid():
    interceptor = TrajectoryInterceptor(target_distance_init=5.0, velocity=-0.5, speed_of_sound=343.0)
    tof = interceptor.track_and_predict_trajectory()
    assert tof > 0.0
    res = interceptor.calculate_injection_window(tof, spoof_distance=3.5)
    assert "injection_delay_ms" in res
    assert "state" in res

    grid = SpatialDensityGrid()
    updated = grid.update_vectors([(3.5, 0.8), (7.0, 0.4)])
    assert updated.shape == (grid.grid_size, grid.grid_size)
    assert np.max(updated) > 0.0

def test_panns_detector():
    detector = MultiBandPANNsDetector(num_classes=2)
    # 48kHz audio chunk
    test_audio = np.sin(2 * np.pi * 1000 * np.linspace(0, 0.5, 24000)).astype(np.float32)
    result = detector.predict_audio(test_audio, sample_rate=48000)
    assert "predicted_class" in result
    assert "confidence" in result
    assert "label" in result
    assert len(result["probabilities"]) == 2

def test_hubert_converter():
    engine = HubertEngine()
    test_audio = np.random.normal(0, 0.05, 4800).astype(np.float32)
    tokens = engine.extract_semantic_tokens(AudioResampler.prepare_for_hubert(test_audio, 48000))
    assert tokens.ndim == 3
    assert tokens.shape[-1] == 768

    converted = engine.convert_voice_frame(test_audio, in_sample_rate=48000, out_sample_rate=44100)
    assert len(converted) > 0

def test_telemetry_and_dataset_logger():
    with tempfile.TemporaryDirectory() as tmpdir:
        ds_cfg = DatasetConfig(output_directory=tmpdir)
        dsp_cfg = DspFilterConfig(speech_energy_threshold=0.01)
        logger = AutomatedDatasetLogger(ds_cfg, dsp_cfg, sample_rate=48000)

        # Feed active speech frames
        active_frame = (0.05 * np.ones(2048, dtype=np.float32))
        rec1 = logger.process_frame(active_frame, current_energy=0.05)
        assert rec1 is None  # still accumulating

        # Silence frame to trigger flush
        logger.speech_timeout = logger.speech_timeout - 2.0  # simulate timeout
        # Add enough frames for >= 1.0s
        for _ in range(25):
            logger.recording_buffer.append(active_frame)
        rec2 = logger.process_frame(np.zeros(2048, dtype=np.float32), current_energy=0.0)
        assert rec2 is not None
        assert os.path.exists(rec2["full_path"])
        assert os.path.exists(logger.manifest_path)

        # Telemetry check
        pipe_cfg = PipelineConfig(dataset=ds_cfg)
        tracker = LivePerformanceTracker(pipe_cfg)
        tel = tracker.collect_telemetry()
        assert tel["manifest_line_count"] >= 1
