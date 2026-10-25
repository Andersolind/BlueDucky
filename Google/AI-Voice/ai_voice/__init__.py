"""
AI-Voice: Unified Multi-Sensor Acoustic & RF Signal Intelligence Suite
======================================================================
"""

from ai_voice.config import PipelineConfig, HardwareConfig, DspFilterConfig, ModelConfig, DatasetConfig, SpatialConfig
from ai_voice.dsp.filters import AudioFilterEngine, UltrasonicDemodulator
from ai_voice.dsp.resampler import AudioResampler
from ai_voice.dsp.spatial import TrajectoryInterceptor, SpatialDensityGrid
from ai_voice.hardware.audio import AudioHardwareManager
from ai_voice.hardware.sdr import RtlsdrManager, HackRfSyncSniffer
from ai_voice.hardware.multi_sensor import MultiSensorCaptureEngine
from ai_voice.models.panns_detector import MultiBandPANNsDetector
from ai_voice.models.hubert_converter import HubertEngine, StreamingVoiceConverter
from ai_voice.models.pipeline import UnifiedAIVoicePipeline
from ai_voice.telemetry.monitor import LivePerformanceTracker
from ai_voice.telemetry.dataset_logger import AutomatedDatasetLogger
from ai_voice.ollama_bridge import OllamaSIGINTBridge

__version__ = "1.0.0"
__all__ = [
    "PipelineConfig",
    "HardwareConfig",
    "DspFilterConfig",
    "ModelConfig",
    "DatasetConfig",
    "SpatialConfig",
    "AudioFilterEngine",
    "UltrasonicDemodulator",
    "AudioResampler",
    "TrajectoryInterceptor",
    "SpatialDensityGrid",
    "AudioHardwareManager",
    "RtlsdrManager",
    "HackRfSyncSniffer",
    "MultiSensorCaptureEngine",
    "MultiBandPANNsDetector",
    "HubertEngine",
    "StreamingVoiceConverter",
    "UnifiedAIVoicePipeline",
    "LivePerformanceTracker",
    "AutomatedDatasetLogger",
    "OllamaSIGINTBridge"
]
