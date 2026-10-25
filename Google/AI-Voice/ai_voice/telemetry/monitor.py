"""
AI-Voice Live Telemetry & System Monitoring
===========================================
Extracts real-time hardware telemetry:
- PyTorch GPU VRAM allocated and cached
- Host CPU usage & memory
- Dataset line count relative to target limits
- Active target speaker voice profile
"""

import os
import time
import psutil
import torch
from typing import Dict, Any, Optional
from ai_voice.config import PipelineConfig

class LivePerformanceTracker:
    """Tracks compute load and dataset expansion in background telemetry thread."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def collect_telemetry(self) -> Dict[str, Any]:
        """Gathers single snapshot of compute and pipeline metrics."""
        manifest_path = os.path.join(
            self.config.dataset.output_directory,
            self.config.dataset.manifest_filename
        )
        line_count = 0
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                pass

        gpu_vram_allocated_mb = 0.0
        gpu_vram_cached_mb = 0.0
        if self.device.type == "cuda":
            try:
                gpu_vram_allocated_mb = torch.cuda.memory_allocated(self.device) / (1024 ** 2)
                gpu_vram_cached_mb = torch.cuda.memory_reserved(self.device) / (1024 ** 2)
            except Exception:
                pass

        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        return {
            "timestamp": time.time(),
            "device_type": self.device.type,
            "gpu_vram_allocated_mb": round(gpu_vram_allocated_mb, 2),
            "gpu_vram_cached_mb": round(gpu_vram_cached_mb, 2),
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(mem.percent, 1),
            "manifest_line_count": line_count,
            "target_line_limit": self.config.dataset.target_manifest_line_limit,
            "dataset_progress_pct": round((line_count / max(1, self.config.dataset.target_manifest_line_limit)) * 100.0, 1),
            "active_speaker_profile": self.config.model.active_speaker_profile
        }
