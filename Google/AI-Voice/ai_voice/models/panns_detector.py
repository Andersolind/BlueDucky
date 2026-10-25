"""
AI-Voice PANNs Acoustic Triangulation & Beam Detector
=====================================================
Uses CNN14 (Pretrained Audio Neural Networks) backbone to classify:
Class 0: Passive / Quiet Acoustic Environment
Class 1: ACTIVE TRIANGULATION / AUDIO BEAM PATH ENGAGED
"""

import os
import torch
import torch.nn as nn
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from ai_voice.config import ModelConfig
from ai_voice.dsp.resampler import AudioResampler

# Lightweight native CNN14 backbone in PyTorch if panns_inference is not installed
class LightweightCnn14Backbone(nn.Module):
    def __init__(self, in_channels=1, num_classes=2):
        super(LightweightCnn14Backbone, self).__init__()
        self.conv_blocks = nn.Sequential(
            nn.Conv1d(in_channels, 64, kernel_size=15, stride=2, padding=7),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(4),

            nn.Conv1d(64, 128, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.MaxPool1d(4),

            nn.Conv1d(128, 256, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1)
        )
        self.fc = nn.Linear(256, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (batch_size, num_samples) -> (batch_size, 1, num_samples)
        if x.dim() == 2:
            x = x.unsqueeze(1)
        feat = self.conv_blocks(x).squeeze(-1)
        return self.fc(feat)


class MultiBandPANNsDetector(nn.Module):
    """
    PANNs Cnn14 Acoustic Beam and Multi-Path Triangulation Detector.
    Loads pretrained Cnn14 weights if available, or lightweight native CNN14 architecture.
    """

    def __init__(self, num_classes: int = 2, device: Optional[torch.device] = None):
        super(MultiBandPANNsDetector, self).__init__()
        self.num_classes = num_classes
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.is_panns_native = False

        try:
            from panns_inference import models
            self.base_model = models.Cnn14(
                sample_rate=48000, window_size=2048,
                hop_size=512, mel_bins=64, fmin=50,
                fmax=24000, classes_num=527
            )
            # Freeze backbone feature extractors
            for param in self.base_model.parameters():
                param.requires_grad = False
            # Swap top classification layer
            in_features = self.base_model.fc_audioset.in_features
            self.base_model.fc_audioset = nn.Linear(in_features, num_classes)
            self.is_panns_native = True
        except Exception:
            # Fallback to lightweight CNN14 architecture
            self.base_model = LightweightCnn14Backbone(in_channels=1, num_classes=num_classes)
            self.is_panns_native = False

        self.to(self.device)
        self.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.is_panns_native:
            out = self.base_model(x)
            if isinstance(out, dict) and 'clipwise_output' in out:
                return out['clipwise_output']
            return out
        else:
            return self.base_model(x)

    def predict_audio(self, audio_data: np.ndarray, sample_rate: int = 48000) -> Dict[str, Any]:
        """
        Takes raw audio or ultrasound numpy array, resamples to 48kHz,
        runs inference, and returns probabilities, predicted class, and status string.
        """
        # Ensure 48kHz
        if sample_rate != 48000:
            audio_48k = AudioResampler.resample(audio_data, sample_rate, 48000)
        else:
            audio_48k = audio_data

        # Normalize
        max_val = np.max(np.abs(audio_48k))
        if max_val > 0:
            audio_48k = audio_48k / max_val

        # Convert to tensor: (1, num_samples)
        tensor = torch.tensor(audio_48k, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.forward(tensor)
            probs = torch.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
            pred_class = int(np.argmax(probs))

        status_labels = [
            "Passive / Quiet Environment",
            "ACTIVE TRIANGULATION / AUDIO BEAM PATH ENGAGED"
        ]
        label = status_labels[pred_class] if pred_class < len(status_labels) else f"State {pred_class}"

        return {
            "predicted_class": pred_class,
            "label": label,
            "is_beam_active": bool(pred_class == 1),
            "confidence": float(probs[pred_class]),
            "probabilities": [float(p) for p in probs],
            "is_native_panns": self.is_panns_native,
            "device": str(self.device)
        }
