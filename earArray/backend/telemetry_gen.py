"""
Live & Simulated Multi-Layer Telemetry Generator
================================================
Generates unified frames combining:
- earDefence / sniitch4ears (SVM + 7-stage validator, channel power, baseline)
- benine4u (replay carrier/envelope/THD confidence)
- 4snitichingcars / carDefender (BLE ranging, Live Listen, Subaru STARLINK & transducers)
- toneSnicher2026 (64-subcarrier Wi-Fi CSI, GCC-PHAT DOA, VAD, 16-band SHA-1 fingerprints)
- Reverse-Physics Suite (Retro/Intermod, LO Leakage, Speaker Microphonics)
- Sensing & Delivery Cores (Pilot IQ Vibrometry, Delay-and-Sum + Binaural HRTF)
"""

import hashlib
import math
import time
from typing import Any, Dict, List
import numpy as np


SAMPLE_BLE_DEVICES = [
    {"address": "00:1D:DF:84:2A:11", "name": "SUBARU BT", "manufacturer": "Harman/Subaru", "device_type": "SUBARU", "base_rssi": -54, "azimuth": 62.0, "is_speaker": False, "is_vehicle": True, "a2dp_sink": True, "gen": "Gen 3.x+ Harman Kardon 576W (12-spk)"},
    {"address": "04:FE:31:9B:10:C4", "name": "Bose SoundLink Mini", "manufacturer": "Bose", "device_type": "SPEAKER", "base_rssi": -49, "azimuth": -48.0, "is_speaker": True, "is_vehicle": False, "a2dp_sink": True, "gen": "Portable A2DP Sink"},
    {"address": "AC:37:43:51:8E:02", "name": "Observer iPhone", "manufacturer": "Apple", "device_type": "PHONE", "base_rssi": -58, "azimuth": 18.0, "is_speaker": False, "is_vehicle": False, "a2dp_sink": False, "a2dp_source": True, "gen": "Live Listen Capable"},
    {"address": "00:1E:B6:3C:91:77", "name": "Outback STARLINK", "manufacturer": "Denso CP1", "device_type": "SUBARU", "base_rssi": -66, "azimuth": 118.0, "is_speaker": False, "is_vehicle": True, "a2dp_sink": False, "gen": "Denso CP1 (2020+)"},
    {"address": "C3:2D:EA:D6:E6:78", "name": "[Unnamed Transceiver]", "manufacturer": "Unknown", "device_type": "UNKNOWN", "base_rssi": -52, "azimuth": 20.0, "is_speaker": False, "is_vehicle": False, "a2dp_sink": False, "gen": "BLE Beacon"},
]


def estimate_ble_distance(rssi: float, tx_power: float = -59.0, n_exp: float = 2.5) -> float:
    return round(10.0 ** ((tx_power - rssi) / (10.0 * n_exp)), 2)


def build_unified_frame(
    tick: int,
    retro_snap: Dict[str, Any],
    lo_snap: Dict[str, Any],
    micro_snap: Dict[str, Any],
    pilot_snap: Dict[str, Any],
    beam_snap: Dict[str, Any],
    pluto_snap: Dict[str, Any] = None,
    tof_snap: Dict[str, Any] = None,
    subvocal_snap: Dict[str, Any] = None,
    enclave_snap: Dict[str, Any] = None,
) -> Dict[str, Any]:
    t = time.time()
    rng = np.random.default_rng((tick + int(t * 10)) % 1_000_000)

    # 1. EarDefence + Sniitch4Ears multi-stage telemetry
    active_tx = retro_snap["params"]["active_transceiver_enabled"]
    left_bp = float(0.42 + 0.12 * math.sin(t * 0.9) + (0.08 if not active_tx else 0.14))
    right_bp = float(0.45 + 0.10 * math.cos(t * 0.8) + (0.48 if active_tx else 0.04))
    max_bp = max(left_bp, right_bp, 1e-6)
    l_norm, r_norm = left_bp / max_bp, right_bp / max_bp
    range_bp = abs(r_norm - l_norm)
    imbalance = max(l_norm, r_norm) / max(min(l_norm, r_norm), 0.05)
    corr = float(0.34 if active_tx else 0.89) + float(rng.normal(0, 0.02))
    flatness = float(0.08 if active_tx else 0.44)
    svm_conf = float(1.0 / (1.0 + math.exp(-(2.5 * range_bp + 1.5 * (imbalance - 1.0) - 1.2 * corr - 0.6))))

    temporal_hits = 4 if active_tx else 1
    status_label = (
        "ANOMALY_CONFIRMED" if (active_tx and svm_conf > 0.62)
        else ("MONITORING" if svm_conf > 0.42 else "SAFE")
    )

    # 2. Benine4u replay authenticity metrics
    mod_depth = round(0.24 + 0.05 * math.sin(t * 1.4), 3) if active_tx else 0.03
    replay_conf = round(min(0.95, 0.58 + mod_depth) if active_tx else 0.14, 3)

    # 3. BLE + Live Listen + Subaru / Vehicle Transducer fusion
    ble_list: List[Dict[str, Any]] = []
    for i, dev in enumerate(SAMPLE_BLE_DEVICES):
        jitter = float(2.2 * math.sin(t * 0.6 + i * 1.3) + rng.normal(0, 0.6))
        rssi = int(round(dev["base_rssi"] + jitter))
        dist = estimate_ble_distance(rssi)
        risk = "HIGH" if dev["is_speaker"] else ("MEDIUM" if dev["is_vehicle"] or dev["device_type"] == "UNKNOWN" else "LOW")
        ble_list.append({
            **dev,
            "rssi": rssi,
            "distance_m": dist,
            "risk_level": risk,
            "live_listen_score": round(0.82 if dev["is_speaker"] else (0.55 if dev.get("a2dp_source") else 0.15), 2),
        })

    # 4. MotionDeluxe (toneSnicher2026): 64-subcarrier CSI + GCC-PHAT DOA + 16-band SHA1 fingerprint
    sc_idx = np.arange(64)
    csi_amp = (
        1.0
        + 0.22 * np.sin(sc_idx * 0.19 + t * 2.4)
        + 0.11 * np.cos(sc_idx * 0.09 - t * 1.6)
        + rng.normal(0, 0.03, size=64)
    )
    csi_motion = round(float(np.std(csi_amp - 1.0)), 4)
    doa_deg = round(float(retro_snap["intermodulation_metrics"]["virtual_midair_doa_deg"] + rng.normal(0, 1.2)), 1)
    tdoa_us = round((0.08 * math.sin(math.radians(doa_deg)) / 343.0) * 1e6, 1)
    doa_conf = round(0.86 if active_tx else 0.64, 2)

    bands_16 = np.abs(np.sin(np.linspace(0.4, 3.8, 16) + t * 0.7)) + 0.15
    bands_16 = (bands_16 / np.sum(bands_16)).tolist()
    q_bytes = np.clip(np.round(np.array(bands_16) * 255), 0, 255).astype(np.uint8).tobytes()
    fp_hash = hashlib.sha1(q_bytes).hexdigest()[:16]

    gesture = "talking" if (csi_motion > 0.12 and active_tx) else ("presence_nearby" if csi_motion > 0.08 else "listening")
    cross_rules = ["voice_present"]
    if active_tx:
        cross_rules.extend(["hf_appears", "ble_close_hf", "ble_close_sound_dir", "heterodyne_midair_beat"])

    return {
        "tick": tick,
        "timestamp": time.strftime("%H:%M:%S"),
        "ear_defence": {
            "status": status_label,
            "direction": "Right" if right_bp >= left_bp else "Left",
            "svm_confidence": round(svm_conf, 3),
            "left_power": round(left_bp, 3),
            "right_power": round(right_bp, 3),
            "range_bp": round(range_bp, 3),
            "imbalance_ratio": round(imbalance, 2),
            "correlation": round(corr, 3),
            "spectral_flatness": round(flatness, 3),
            "temporal_consistency": f"{temporal_hits}/5 windows",
            "baseline_calibrated": True,
        },
        "replay_detector": {
            "confidence": replay_conf,
            "carrier_hz": retro_snap["frequencies_hz"]["f1_sonar"],
            "modulation_depth": mod_depth,
            "thd_ratio": 0.072 if active_tx else 0.014,
            "verdict": "SYNTHETIC_MODULATED_CARRIER" if active_tx else "AMBIENT_BACKGROUND",
        },
        "vehicle_ble": {
            "devices": ble_list,
            "parking_sensor_40_48khz": True,
            "subaru_harman_576w_ready": True,
            "speaker_resonances_db": {"subwoofer": 24.2, "door_woofer": 19.6, "dash_tweeter": 28.4},
        },
        "cross_layer": {
            "gesture": gesture,
            "csi_subcarriers_64": np.round(csi_amp, 3).tolist(),
            "csi_motion": csi_motion,
            "csi_rate_hz": 48.5,
            "doa_deg": doa_deg,
            "tdoa_us": tdoa_us,
            "doa_conf": doa_conf,
            "voice_ratio": 0.68 if active_tx else 0.22,
            "hf_z": 7.4 if active_tx else 1.1,
            "sub_5hz_presence": True,
            "fp_hash": fp_hash,
            "bands_16": [round(b, 4) for b in bands_16],
            "active_rules": cross_rules,
        },
        "retro_intermod": retro_snap,
        "lo_leakage": lo_snap,
        "speaker_microphonics": micro_snap,
        "pilot_sensing": pilot_snap,
        "beamforming_hrtf": beam_snap,
        "pluto_bridge": pluto_snap or {},
        "spatial_tof": tof_snap or {},
        "subvocal_learner": subvocal_snap or {},
        "audible_enclave": enclave_snap or {},
    }
