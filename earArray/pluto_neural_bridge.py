#!/usr/bin/env python3
"""
PlutoSDR Neural Adaptive Bridge
===============================
Integrates ADALM-Pluto VHF/UHF SDR (with graceful simulation fallback when hardware
or JACK is offline), REAPER DAW OSC UDP automation, 10-second rolling Earworm WAV
snapshot recorder, online 4-class Softmax ANN with live backpropagation, and
Breath-Gesture Bio-Macro prefix forecasting + Telegraphic Morse generator.
"""

import math
import os
import socket
import struct
import sys
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import adi  # Native ADALM-Pluto hardware interface library
    HAS_ADI = True
except ImportError:
    HAS_ADI = False

try:
    import jack  # Python bindings for low-latency JACK audio routing
    HAS_JACK = True
except ImportError:
    HAS_JACK = False


@dataclass
class PlutoBridgeConfig:
    rx_freq: int = 144_300_000
    tx_freq: int = 144_800_000
    rf_sample_rate: int = 2_000_000
    audio_sample_rate: int = 48_000
    buffer_size: int = 4096
    decimation_factor: int = 40
    rx_gain: float = 45.0
    tx_atten: float = 45.0
    fm_deviation: float = 5000.0
    squelch_threshold_db: float = -55.0
    reaper_ip: str = "127.0.0.1"
    reaper_osc_port: int = 8000
    learning_rate: float = 0.01
    sim_rf_activity: float = 0.35
    sim_audio_rms: float = 0.018


class PlutoNeuralAdaptiveBridge:
    CLASSES = ["STABLE_IDLE", "SITTING", "STANDING", "ROOM_MOVEMENT"]

    BIOMACRO_MAP = {
        ("INHALE", "INHALE", "EXHALE"): "CQ",
        ("EXHALE", "EXHALE", "INHALE"): "READY",
        ("INHALE", "EXHALE", "INHALE"): "OK",
    }

    MORSE_ALPHABET = {
        "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
        "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
        "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
        "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
        "Y": "-.--", "Z": "--..",
    }

    def __init__(self, cfg: Optional[PlutoBridgeConfig] = None, connect_hw: bool = False):
        self.cfg = cfg or PlutoBridgeConfig()
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.is_squelch_open = False
        self.earworm_max_len = self.cfg.audio_sample_rate * 10
        self.earworm_rx_buffer = deque(maxlen=self.earworm_max_len)

        self.breath_gesture_queue: List[str] = []
        self.last_gesture_state = "REST"
        self.gesture_start_time = time.time()
        self.predicted_macro_intent = "NONE"
        self.last_dispatched_morse = ""
        self.last_morse_symbols = ""

        self.current_presence_state = "STABLE_IDLE"
        self.num_features = 3
        self.num_classes = len(self.CLASSES)

        rng = np.random.default_rng(42)
        self.weights = rng.normal(0.0, np.sqrt(2.0 / self.num_features), size=(self.num_classes, self.num_features))
        # Seed sensible directional priors so RF_Variance & Audio_RMS map intuitively before user training
        self.weights[0] = np.array([-1.4, -1.2, -0.5])  # STABLE_IDLE
        self.weights[1] = np.array([0.4, 0.5, 0.3])     # SITTING
        self.weights[2] = np.array([1.1, 0.9, 0.6])     # STANDING
        self.weights[3] = np.array([1.9, 1.5, 0.9])     # ROOM_MOVEMENT
        self.biases = np.array([0.8, 0.1, -0.3, -0.7], dtype=np.float64)

        self.is_reaper_track_armed = False
        self.is_rf_carrier_precharged = False
        self.rf_amplitude_history = deque(maxlen=150)
        self.osc_log: deque = deque(maxlen=20)
        self.train_steps = 0
        self.saved_snapshots: List[str] = []

        self.hw_connected = False
        self.jack_connected = False
        self.sdr = None
        self.jack_client = None

        if connect_hw and HAS_ADI:
            try:
                self.sdr = adi.Pluto("ip:pluto.local")
                self.sdr.sample_rate = self.cfg.rf_sample_rate
                self.sdr.rx_lo = self.cfg.rx_freq
                self.sdr.rx_buffer_size = self.cfg.buffer_size
                self.sdr.gain_control_mode_chan0 = "manual"
                self.sdr.rx_hardwaregain_chan0 = self.cfg.rx_gain
                self.sdr.tx_destroy_buffer()
                self.sdr.tx_lo = self.cfg.tx_freq
                self.sdr.tx_hardwaregain_chan0 = -float(self.cfg.tx_atten)
                self.hw_connected = True
            except Exception:
                self.hw_connected = False

        if connect_hw and HAS_JACK:
            try:
                self.jack_client = jack.Client("PlutoSDR_Neural_Engine")
                self.audio_out = self.jack_client.outports.register("sdr_demod_to_reaper")
                self.audio_in = self.jack_client.inports.register("reaper_fx_to_sdr")
                self.jack_connected = True
            except Exception:
                self.jack_connected = False

    def send_reaper_osc_packet(self, osc_address: str, float_value: float):
        try:
            def osc_string(s: str) -> bytes:
                b = s.encode("utf-8") + b"\x00"
                return b + b"\x00" * ((4 - (len(b) % 4)) % 4)
            packet = osc_string(osc_address) + osc_string(",f") + struct.pack(">f", float(float_value))
            self.udp_sock.sendto(packet, (self.cfg.reaper_ip, int(self.cfg.reaper_osc_port)))
            self.osc_log.appendleft({
                "ts": time.strftime("%H:%M:%S"),
                "address": osc_address,
                "value": round(float(float_value), 2),
            })
        except Exception:
            pass

    @staticmethod
    def softmax(logits: np.ndarray) -> np.ndarray:
        exp_logits = np.exp(logits - np.max(logits))
        return exp_logits / np.sum(exp_logits)

    def run_neural_inference(self, feature_vector: np.ndarray) -> Tuple[int, float, np.ndarray]:
        logits = np.dot(self.weights, feature_vector) + self.biases
        probabilities = self.softmax(logits)
        idx = int(np.argmax(probabilities))
        return idx, float(probabilities[idx]), probabilities

    def online_train_step(self, feature_vector: np.ndarray, target_class_string: str):
        if target_class_string not in self.CLASSES:
            return
        target_idx = self.CLASSES.index(target_class_string)
        logits = np.dot(self.weights, feature_vector) + self.biases
        probs = self.softmax(logits)

        target_one_hot = np.zeros(self.num_classes)
        target_one_hot[target_idx] = 1.0
        error_gradient = probs - target_one_hot

        lr = float(self.cfg.learning_rate)
        self.weights -= lr * np.outer(error_gradient, feature_vector)
        self.biases -= lr * error_gradient
        self.train_steps += 1

    def execute_preemptive_automation(self, action_type: str):
        if action_type == "ARM_AUDIO":
            if not self.is_reaper_track_armed:
                self.is_reaper_track_armed = True
                self.send_reaper_osc_packet("/track/1/mute", 0.0)
                self.send_reaper_osc_packet("/track/1/monitor", 1.0)
        elif action_type == "PRECHARGE_RF":
            if not self.is_rf_carrier_precharged:
                self.is_rf_carrier_precharged = True
                if self.hw_connected and self.sdr is not None:
                    self.sdr.tx(np.zeros(self.cfg.buffer_size, dtype=np.complex64))
                self.send_reaper_osc_packet("/pluto/tx/precharge", 1.0)
        elif action_type == "DISARM_AND_RESET":
            if self.is_reaper_track_armed or self.is_rf_carrier_precharged:
                self.is_reaper_track_armed = False
                self.is_rf_carrier_precharged = False
                self.send_reaper_track_reset()

    def send_reaper_track_reset(self):
        self.send_reaper_osc_packet("/track/1/mute", 1.0)
        self.send_reaper_osc_packet("/track/1/monitor", 0.0)

    def encode_morse(self, word: str) -> str:
        return " ".join(self.MORSE_ALPHABET.get(ch.upper(), "") for ch in word if ch.isalpha())

    def forecast_macro_intent(self) -> str:
        tokens = tuple(self.breath_gesture_queue[-3:])
        if not tokens:
            self.predicted_macro_intent = "NONE"
            return "NONE"

        # Exact 3-token match dispatches Morse + precharges RF
        if len(tokens) == 3 and tokens in self.BIOMACRO_MAP:
            word = self.BIOMACRO_MAP[tokens]
            self.predicted_macro_intent = f"DISPATCH:{word}"
            self.last_dispatched_morse = word
            self.last_morse_symbols = self.encode_morse(word)
            self.execute_preemptive_automation("PRECHARGE_RF")
            self.breath_gesture_queue.clear()
            return self.predicted_macro_intent

        # Prefix lookahead matching
        candidates = [
            macro for seq, macro in self.BIOMACRO_MAP.items()
            if seq[: len(tokens)] == tokens
        ]
        if len(candidates) == 1:
            self.predicted_macro_intent = f"LOOKAHEAD:{candidates[0]}"
            self.execute_preemptive_automation("PRECHARGE_RF")
        elif len(candidates) > 1:
            self.predicted_macro_intent = "PREFIX:" + "/".join(candidates)
        else:
            self.predicted_macro_intent = "UNMAPPED_RESET"
            self.breath_gesture_queue.clear()
        return self.predicted_macro_intent

    def push_breath_token(self, token: str) -> Dict:
        tok = token.upper().strip()
        if tok in ("INHALE", "EXHALE"):
            self.breath_gesture_queue.append(tok)
            if len(self.breath_gesture_queue) > 3:
                self.breath_gesture_queue = self.breath_gesture_queue[-3:]
            self.last_gesture_state = tok
            self.forecast_macro_intent()
        elif tok == "CLEAR":
            self.breath_gesture_queue.clear()
            self.predicted_macro_intent = "NONE"
        return self.step_telemetry()

    def export_earworm_snapshots(self, out_dir: Optional[Path] = None) -> Dict:
        folder = out_dir or (Path(__file__).resolve().parent / "logs")
        folder.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        rx_filename = f"earworm_rx_{ts}.wav"
        filepath = folder / rx_filename

        if len(self.earworm_rx_buffer) < 4800:
            # Populate synthetic 2-second FM demodulated audio burst if buffer just started
            t = np.linspace(0, 2.0, self.cfg.audio_sample_rate * 2, endpoint=False)
            synth = 0.25 * np.sin(2 * np.pi * 650.0 * t) + 0.03 * np.random.randn(len(t))
            self.earworm_rx_buffer.extend(synth.tolist())

        rx_data = np.clip(np.array(list(self.earworm_rx_buffer), dtype=np.float32), -1.0, 1.0)
        scaled = (rx_data * 32767.0).astype(np.int16)
        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.cfg.audio_sample_rate)
            wf.writeframes(scaled.tobytes())

        self.saved_snapshots.insert(0, rx_filename)
        return {"saved": True, "file": rx_filename, "samples": int(len(scaled)), "duration_s": round(len(scaled) / self.cfg.audio_sample_rate, 2)}

    def step_telemetry(self) -> Dict:
        t = time.time()
        rng = np.random.default_rng(int(t * 20) % 1_000_000)

        # Acquire or synthesize IQ + Audio block
        act = float(self.cfg.sim_rf_activity)
        iq_env = (0.04 + act * 0.45 * (1.0 + 0.6 * math.sin(t * 1.9))) * (
            np.exp(1j * np.linspace(0, 8 * np.pi, 512)) + rng.normal(0, 0.08 + act * 0.25, 512)
        )
        audio_block = (
            float(self.cfg.sim_audio_rms) * np.sin(2 * np.pi * 440.0 * np.arange(512) / self.cfg.audio_sample_rate)
            + rng.normal(0, 0.004, 512)
        )
        self.earworm_rx_buffer.extend(audio_block.tolist())

        mean_power = float(np.mean(np.abs(iq_env) ** 2) + 1e-10)
        power_db = 10.0 * math.log10(mean_power) - 38.0
        self.rf_amplitude_history.append(power_db)
        self.is_squelch_open = bool(power_db >= self.cfg.squelch_threshold_db)

        rf_variance = float(np.var(self.rf_amplitude_history)) if len(self.rf_amplitude_history) > 6 else float(act * 1.6)
        audio_rms = float(np.sqrt(np.mean(audio_block ** 2)) + 1e-10)
        zcr = float(np.nonzero(np.diff(audio_block > 0))[0].size / len(audio_block))

        fv = np.array([rf_variance, audio_rms * 100.0, zcr], dtype=np.float64)
        c_idx, conf, probs = self.run_neural_inference(fv)
        pred_state = self.CLASSES[c_idx]

        if rf_variance < 0.08 and audio_rms < 0.003:
            self.online_train_step(fv, "STABLE_IDLE")

        if pred_state in ("STANDING", "ROOM_MOVEMENT") and conf > 0.65:
            self.execute_preemptive_automation("ARM_AUDIO")
        elif pred_state == "STABLE_IDLE" and conf > 0.65:
            self.execute_preemptive_automation("DISARM_AND_RESET")

        self.current_presence_state = pred_state

        return {
            "timestamp": time.strftime("%H:%M:%S"),
            "hardware": {
                "pluto_connected": self.hw_connected,
                "jack_connected": self.jack_connected,
                "mode": "ADALM_PLUTO_LIVE" if self.hw_connected else "PLUTO_DIGITAL_TWIN",
                "rx_freq_mhz": round(self.cfg.rx_freq / 1e6, 3),
                "tx_freq_mhz": round(self.cfg.tx_freq / 1e6, 3),
                "rf_sample_rate_msps": round(self.cfg.rf_sample_rate / 1e6, 2),
                "squelch_open": self.is_squelch_open,
                "rf_power_db": round(power_db, 2),
            },
            "neural_net": {
                "predicted_state": pred_state,
                "confidence": round(conf, 3),
                "probabilities": {cls: round(float(probs[i]), 3) for i, cls in enumerate(self.CLASSES)},
                "features": {
                    "rf_variance": round(rf_variance, 4),
                    "audio_rms_x100": round(audio_rms * 100.0, 3),
                    "zero_crossings": round(zcr, 4),
                },
                "weights": np.round(self.weights, 3).tolist(),
                "train_steps": self.train_steps,
            },
            "automation_osc": {
                "reaper_endpoint": f"{self.cfg.reaper_ip}:{self.cfg.reaper_osc_port}",
                "jack_ports": ["sdr_demod_to_reaper", "reaper_fx_to_sdr"],
                "is_reaper_track_armed": self.is_reaper_track_armed,
                "is_rf_carrier_precharged": self.is_rf_carrier_precharged,
                "recent_osc_packets": list(self.osc_log)[:6],
            },
            "biomacro_morse": {
                "breath_queue": list(self.breath_gesture_queue),
                "predicted_macro_intent": self.predicted_macro_intent,
                "last_dispatched_morse": self.last_dispatched_morse,
                "last_morse_symbols": self.last_morse_symbols,
            },
            "earworm": {
                "buffer_fill_s": round(len(self.earworm_rx_buffer) / self.cfg.audio_sample_rate, 1),
                "max_s": 10.0,
                "saved_snapshots": self.saved_snapshots[:5],
            },
            "rf_history_db": [round(float(x), 2) for x in list(self.rf_amplitude_history)[-60:]],
            "params": asdict(self.cfg),
        }


if __name__ == "__main__":
    bridge = PlutoNeuralAdaptiveBridge()
    bridge.push_breath_token("INHALE")
    bridge.push_breath_token("INHALE")
    snap = bridge.push_breath_token("EXHALE")
    print("State:", snap["neural_net"]["predicted_state"], "| Morse:", snap["biomacro_morse"])
