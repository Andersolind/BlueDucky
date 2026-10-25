"""
AI-Voice Automated Speech Dataset & Manifest Logger
===================================================
Automatically slices voice activity frames into normalized audio segments
and logs them directly into StyleTTS2 (train_list.txt) and HuBERT (metadata.csv) dataset manifests.
"""

import os
import csv
import time
import uuid
import numpy as np
import soundfile as sf
from typing import Dict, Any, List, Optional
from ai_voice.config import DatasetConfig, DspFilterConfig

class AutomatedDatasetLogger:
    """Slices continuous speech streams into normalized dataset clips and updates manifests."""

    def __init__(self, dataset_config: Optional[DatasetConfig] = None, dsp_config: Optional[DspFilterConfig] = None, sample_rate: int = 48000):
        self.dataset_config = dataset_config or DatasetConfig()
        self.dsp_config = dsp_config or DspFilterConfig()
        self.sample_rate = sample_rate

        self.audio_dir = os.path.join(self.dataset_config.output_directory, self.dataset_config.audio_subdir)
        os.makedirs(self.audio_dir, exist_ok=True)
        
        self.manifest_path = os.path.join(self.dataset_config.output_directory, self.dataset_config.manifest_filename)
        self.metadata_path = os.path.join(self.dataset_config.output_directory, self.dataset_config.metadata_filename)

        # Initialize metadata CSV if missing
        if not os.path.exists(self.metadata_path):
            with open(self.metadata_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["audio_file", "timestamp", "duration_sec", "sample_rate"])

        self.recording_buffer: List[np.ndarray] = []
        self.is_speaking = False
        self.speech_timeout = 0.0

    def process_frame(self, clean_audio_frame: np.ndarray, current_energy: float) -> Optional[Dict[str, Any]]:
        """
        Receives clean audio frame. Accumulates speech while energy > threshold,
        and packages segment to disk upon silence timeout.
        """
        saved_record = None

        if current_energy > self.dsp_config.speech_energy_threshold:
            self.is_speaking = True
            self.speech_timeout = time.time()
            self.recording_buffer.append(clean_audio_frame)
        else:
            if self.is_speaking and (time.time() - self.speech_timeout > self.dsp_config.speech_silence_timeout_sec):
                self.is_speaking = False
                if self.recording_buffer:
                    complete_clip = np.concatenate(self.recording_buffer)
                    self.recording_buffer = []

                    duration_sec = len(complete_clip) / self.sample_rate
                    if duration_sec >= self.dataset_config.min_clip_duration_sec:
                        saved_record = self._save_clip(complete_clip, duration_sec)

        return saved_record

    def _save_clip(self, clip_data: np.ndarray, duration_sec: float) -> Dict[str, Any]:
        # Amplitude normalization
        max_amp = np.max(np.abs(clip_data))
        if max_amp > 0:
            norm_clip = clip_data / max_amp
        else:
            norm_clip = clip_data

        clip_id = str(uuid.uuid4())[:8]
        filename = f"clip_{clip_id}.wav"
        full_path = os.path.join(self.audio_dir, filename)

        # Write audio
        sf.write(full_path, norm_clip, self.sample_rate)

        # Append to StyleTTS2 manifest: wavs/clip_xxxx.wav|PROCESSED_VIBRATION_STREAM|0
        rel_path = f"{self.dataset_config.audio_subdir}/{filename}"
        with open(self.manifest_path, "a", encoding="utf-8") as f:
            f.write(f"{rel_path}|PROCESSED_VIBRATION_STREAM|0\n")

        # Append to metadata CSV
        with open(self.metadata_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([filename, time.time(), round(duration_sec, 3), self.sample_rate])

        return {
            "filename": filename,
            "full_path": full_path,
            "duration_sec": duration_sec,
            "sample_rate": self.sample_rate
        }

    def reset(self):
        self.recording_buffer = []
        self.is_speaking = False
