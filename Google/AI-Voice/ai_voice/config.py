"""
AI-Voice Configuration Module
=============================
Defines structured data profiles for hardware interfaces, DSP filters,
neural network models, dataset manifest management, and telemetry trackers.
"""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class HardwareConfig:
    sample_rate_in: int = 48000
    sample_rate_out: int = 44100
    dodotronic_sample_rate: int = 192000
    builtin_sample_rate: int = 44100
    chunk_size: int = 2048
    builtin_mic_index: int = 0
    dodotronic_index: int = 1
    playback_index: int = 0
    rtl_sdr_frequency: int = 150000       # 150 kHz (transducer EMI leakage)
    rtl_sdr_sample_rate: int = 2048000
    hackrf_sync_frequency: int = 433920000 # 433.92 MHz (T0 RF sync pulse)
    hackrf_sample_rate: int = 2000000
    channels: int = 1
    mock_hardware_if_missing: bool = True

@dataclass
class DspFilterConfig:
    vocal_low_cutoff: float = 80.0
    vocal_high_cutoff: float = 8000.0
    filter_order: int = 4
    electronic_notch_frequencies: List[float] = field(
        default_factory=lambda: [4000.0, 8000.0, 12000.0, 16000.0, 19200.0]
    )
    notch_q: float = 40.0
    ultrasound_highpass_cutoff: float = 3500.0
    ultrasound_lowpass_cutoff: float = 45000.0
    noise_floor_alpha: float = 0.95
    noise_subtraction_multiplier: float = 1.5
    cable_friction_gate_threshold: float = 0.45
    speech_energy_threshold: float = 0.015
    speech_silence_timeout_sec: float = 1.0

@dataclass
class ModelConfig:
    device: str = "auto"  # 'auto', 'cuda', or 'cpu'
    hubert_model_name: str = "facebook/hubert-base-ls960"
    panns_num_classes: int = 2
    panns_sample_rate: int = 48000
    panns_fmin: int = 50
    panns_fmax: int = 24000
    panns_classes: List[str] = field(
        default_factory=lambda: ["Passive / Quiet Environment", "ACTIVE TRIANGULATION / AUDIO BEAM PATH ENGAGED"]
    )
    active_speaker_profile: str = "target_speaker.pt"
    embedding_dim: int = 768

@dataclass
class DatasetConfig:
    output_directory: str = os.path.expanduser("~/triangulation_dataset")
    audio_subdir: str = "wavs"
    manifest_filename: str = "train_list.txt"
    metadata_filename: str = "metadata.csv"
    target_manifest_line_limit: int = 1000
    min_clip_duration_sec: float = 1.0

@dataclass
class SpatialConfig:
    speed_of_sound: float = 343.0  # m/s
    max_room_radius_m: float = 15.0
    grid_resolution_m: float = 0.1
    default_spoof_distance_m: float = 3.5

@dataclass
class PipelineConfig:
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    dsp: DspFilterConfig = field(default_factory=DspFilterConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    spatial: SpatialConfig = field(default_factory=SpatialConfig)
    telemetry_interval_sec: float = 2.0
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "nightsweep-signalintelligence:latest"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineConfig":
        hardware = HardwareConfig(**data.get("hardware", {}))
        dsp = DspFilterConfig(**data.get("dsp", {}))
        model = ModelConfig(**data.get("model", {}))
        dataset = DatasetConfig(**data.get("dataset", {}))
        spatial = SpatialConfig(**data.get("spatial", {}))
        return cls(
            hardware=hardware,
            dsp=dsp,
            model=model,
            dataset=dataset,
            spatial=spatial,
            telemetry_interval_sec=data.get("telemetry_interval_sec", 2.0),
            ollama_host=data.get("ollama_host", "http://localhost:11434"),
            ollama_model=data.get("ollama_model", "nightsweep-signalintelligence:latest")
        )

    def save_to_file(self, file_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_from_file(cls, file_path: str) -> "PipelineConfig":
        if not os.path.exists(file_path):
            return cls()
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
