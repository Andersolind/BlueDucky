#!/usr/bin/env python3
"""
EarArray Unified FastAPI Telemetry & Forensics Server
=====================================================
Integrates all workspace scripts, dolphin_forensics/, logs/,
Reverse-Physics Suite (Retroreflection/Intermod, LO Leakage, Speaker Microphonics),
and Sensing & Target Delivery Cores (Pilot-Tone IQ Demod, Delay-and-Sum + HRTF).
"""

import asyncio
import csv
import json
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
for _p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from retroreflection_intermod import RetroIntermodParams, RetroreflectionIntermodAnalyzer
from reverse_physics_suite import (
    LOLeakageAnalyzer,
    LOLeakageParams,
    SpeakerMicrophonicsAnalyzer,
    SpeakerMicrophonicsParams,
)
from sensing_and_beamforming import (
    BeamformingHRTFParams,
    PilotSensingParams,
    PilotTonePhaseDemodulator,
    SpatialBeamformingCore,
)
from pluto_neural_bridge import PlutoBridgeConfig, PlutoNeuralAdaptiveBridge

# Optional imports from existing workspace scripts
try:
    import benine4u
    HAS_REPLAY = True
except Exception:
    HAS_REPLAY = False

try:
    import sounddevice as sd
    HAS_SD = True
except Exception:
    HAS_SD = False

FORENSICS_DIR = ROOT_DIR / "dolphin_forensics"
LOGS_DIR = ROOT_DIR / "logs"

app = FastAPI(title="EarArray Spatial Telemetry Suite", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FORENSICS_DIR.exists():
    app.mount("/forensics_static", StaticFiles(directory=str(FORENSICS_DIR)), name="forensics_static")

# Engines & Stateful Parameters
retro_params = RetroIntermodParams()
lo_params = LOLeakageParams()
micro_params = SpeakerMicrophonicsParams()
pilot_params = PilotSensingParams()
beam_params = BeamformingHRTFParams()

retro_engine = RetroreflectionIntermodAnalyzer()
lo_engine = LOLeakageAnalyzer()
micro_engine = SpeakerMicrophonicsAnalyzer()
pilot_engine = PilotTonePhaseDemodulator()
beam_engine = SpatialBeamformingCore()
pluto_engine = PlutoNeuralAdaptiveBridge(PlutoBridgeConfig(), connect_hw=False)

sim_state: Dict[str, Any] = {
    "mode": "simulation",
    "running": True,
    "tick": 0,
    "subaru_focus": True,
}

MODULE_CATALOG = [
    {
        "file": "earDefence.py",
        "title": "EarArray Real-Time Monitor",
        "category": "Ultrasonic Sonar Defense",
        "summary": "FIR bandpass + Welch PSD + cross-channel SVM classifier & directional localizer with alert webhooks.",
    },
    {
        "file": "sniitch4ears.py",
        "title": "Enhanced Multi-Stage Validator",
        "category": "False-Positive Filtering",
        "summary": "7-stage validation pipeline, adaptive EMA environmental baseline, ZCR/crest/flatness features & temporal tracker.",
    },
    {
        "file": "benine4u.py",
        "title": "Ultrasonic Replay Analyzer",
        "category": "Signal Authenticity",
        "summary": "Detects AM carriers, Hilbert speech envelopes, speaker THD rolloff, loop autocorrelation & MP3 spectral cutoffs.",
    },
    {
        "file": "snitchingElectronics.py",
        "title": "Dolphin Forensics Diagnostic",
        "category": "Beacon & Source Attribution",
        "summary": "11-band FFT analyzer identifying SilverPush, Nearby, Lisnr, TV ACR, pest repellers, timing periodicity & WAV/PNG capture.",
    },
    {
        "file": "carDefender.py",
        "title": "BLE, Live Listen & Vehicle Scanner",
        "category": "RF + Transducer Fusion",
        "summary": "Log-distance BLE ranging, Apple Live Listen A2DP sink/source inspection & 96 kHz automotive resonance analysis.",
    },
    {
        "file": "4snitichingcars.py",
        "title": "Subaru STARLINK & Harman Kardon",
        "category": "Automotive Acoustics",
        "summary": "Specialized OUI/generation lookup (Harman 576W 12-spk, Denso CP1, Fujitsu Ten, Clarion) & 40-48 kHz sensor telemetry.",
    },
    {
        "file": "toneSnicher2026.py",
        "title": "MotionDeluxe Cross-Layer Engine",
        "category": "CSI + GCC-PHAT DOA + Fingerprints",
        "summary": "64-subcarrier Wi-Fi CSI motion, GCC-PHAT TDOA/DOA, WebRTC VAD, sub-5Hz presence & 16-band SHA-1 audio fingerprints.",
    },
    {
        "file": "daDefender.py",
        "title": "Placeholder Guard Stub",
        "category": "Workspace Stub",
        "summary": "Empty 0-byte placeholder file preserved in workspace root; unified into the live web telemetry console.",
    },
    {
        "file": "retroreflection_intermod.py",
        "title": "Retroreflection & Parametric Intermod",
        "category": "Bidirectional Acoustics",
        "summary": "Models passive clothing/torso/throat reflections vs active 19/20 kHz opposing pilot mid-air Westervelt heterodyne downconversion.",
    },
    {
        "file": "reverse_physics_suite.py",
        "title": "LO Leakage & Coil Microphonics",
        "category": "Counter-Observation Physics",
        "summary": "Receive-only SDR LO port/chassis radiation spatial heatmap + Faraday speaker voice-coil back-EMF microphonics.",
    },
    {
        "file": "sensing_and_beamforming.py",
        "title": "Pilot IQ Sensing & HRTF Beamforming",
        "category": "Non-Contact & Spatial Delivery",
        "summary": "Ultrasonic CW pilot-tone phase unwrapping vibrometry + Delay-and-Sum array steering & Woodworth HRTF ITD/ILD targeting.",
    },
    {
        "file": "pluto_neural_bridge.py",
        "title": "PlutoSDR Neural Adaptive Bridge",
        "category": "SDR + JACK/REAPER OSC + Bio-Macro ANN",
        "summary": "ADALM-Pluto 144 MHz RX/TX bridge, JACK audio routing, REAPER OSC track arming, 10s Earworm WAV snapshot, online Softmax ANN & Breath-to-Morse engine.",
    },
]


@app.get("/api/modules")
def list_modules():
    out = []
    for item in MODULE_CATALOG:
        p = ROOT_DIR / item["file"]
        size_b = p.stat().st_size if p.exists() else 0
        lines = 0
        if p.exists() and size_b > 0:
            with p.open("r", errors="ignore") as f:
                lines = sum(1 for _ in f)
        out.append({**item, "exists": p.exists(), "size_bytes": size_b, "lines": lines})
    return {
        "modules": out,
        "forensics_file_count": len(list(FORENSICS_DIR.iterdir())) if FORENSICS_DIR.exists() else 0,
        "logs_file_count": len(list(LOGS_DIR.iterdir())) if LOGS_DIR.exists() else 0,
    }


@app.get("/api/modules/{filename}/source")
def get_module_source(filename: str):
    safe_name = Path(filename).name
    target = ROOT_DIR / safe_name
    if not target.exists() or target.suffix != ".py":
        raise HTTPException(status_code=404, detail="Module not found")
    content = target.read_text(errors="replace")
    return {"file": safe_name, "size_bytes": len(content), "preview": content[:18000]}


@app.get("/api/devices")
def get_audio_devices():
    if not HAS_SD:
        return {"available": False, "devices": []}
    try:
        devs = sd.query_devices()
        out = []
        for idx, d in enumerate(devs):
            if int(d.get("max_input_channels", 0)) > 0:
                out.append({
                    "index": idx,
                    "name": d.get("name", ""),
                    "channels": int(d.get("max_input_channels", 0)),
                    "default_samplerate": float(d.get("default_samplerate", 44100.0)),
                })
        return {"available": True, "devices": out}
    except Exception as exc:
        return {"available": False, "error": str(exc), "devices": []}

from telemetry_gen import build_unified_frame


def _load_forensics_index() -> Dict[str, Any]:
    if not FORENSICS_DIR.exists():
        return {"detections": [], "reports": [], "beacon_counts": {}, "direction_counts": {}}

    json_files = sorted(
        [p for p in FORENSICS_DIR.glob("detection_*.json")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    reports = sorted([p.name for p in FORENSICS_DIR.glob("forensic_report_*.json")], reverse=True)

    detections = []
    beacon_counts: Dict[str, int] = {}
    dir_counts: Dict[str, int] = {"Left": 0, "Right": 0, "Unknown": 0}

    for jf in json_files[:150]:
        try:
            data = json.loads(jf.read_text(errors="ignore"))
            stem = jf.stem
            wav_name = f"{stem}.wav"
            # Matching spectrogram has same id/time suffix if present
            spec_suffix = stem.replace("detection_", "spectrogram_") + ".png"
            has_wav = (FORENSICS_DIR / wav_name).exists()
            has_spec = (FORENSICS_DIR / spec_suffix).exists()

            direction = data.get("direction", "Unknown")
            dir_counts[direction] = dir_counts.get(direction, 0) + 1
            fa = data.get("frequency_analysis", {})
            for b in fa.get("detected_beacons", []):
                bname = b.get("name", "Unknown")
                beacon_counts[bname] = beacon_counts.get(bname, 0) + 1

            detections.append({
                "file": jf.name,
                "wav_file": wav_name if has_wav else None,
                "spectrogram_file": spec_suffix if has_spec else None,
                "id": data.get("id"),
                "timestamp": data.get("timestamp"),
                "direction": direction,
                "dominant_ultrasonic_hz": round(float(fa.get("dominant_ultrasonic_hz", 0.0)), 1),
                "dominant_ultrasonic_db": round(float(fa.get("dominant_ultrasonic_db", 0.0)), 2),
                "beacons": fa.get("detected_beacons", []),
                "channels": data.get("channel_analysis", {}).get("channels", []),
            })
        except Exception:
            continue

    return {
        "total_detection_json_files": len(json_files),
        "detections": detections,
        "reports": reports,
        "beacon_counts": beacon_counts,
        "direction_counts": dir_counts,
    }


@app.get("/api/forensics/summary")
def forensics_summary():
    return _load_forensics_index()


@app.get("/api/forensics/report/{report_name}")
def forensics_report_detail(report_name: str):
    safe = Path(report_name).name
    p = FORENSICS_DIR / safe
    if not p.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return json.loads(p.read_text(errors="ignore"))


@app.get("/api/forensics/analyze/{wav_name}")
def analyze_forensic_wav(wav_name: str):
    safe = Path(wav_name).name
    wav_path = FORENSICS_DIR / safe
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="WAV file not found")

    intermod_res = retro_engine.analyze_wav_file(str(wav_path))
    replay_res = {}
    if HAS_REPLAY:
        try:
            from scipy.io import wavfile
            sr, audio = wavfile.read(str(wav_path))
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            analyzer = benine4u.ReplayAttackAnalyzer(int(sr))
            raw = analyzer.analyze(audio)
            replay_res = {
                "confidence": round(float(raw.get("confidence", 0.0)), 3),
                "threat_level": raw.get("threat_level", ""),
                "indicators": raw.get("indicators", []),
            }
        except Exception as exc:
            replay_res = {"error": str(exc)}

    return {"wav_file": safe, "intermodulation": intermod_res, "replay": replay_res}


@app.get("/api/logs")
def list_logs():
    if not LOGS_DIR.exists():
        return {"files": []}
    files = sorted([p.name for p in LOGS_DIR.glob("*.csv")], reverse=True)
    return {"files": files}


@app.get("/api/logs/{csv_name}")
def get_log_rows(csv_name: str, limit: int = 120):
    safe = Path(csv_name).name
    p = LOGS_DIR / safe
    if not p.exists():
        raise HTTPException(status_code=404, detail="CSV not found")
    rows = []
    with p.open("r", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if idx >= limit:
                break
            rows.append(row)
    return {"file": safe, "count": len(rows), "rows": rows}


def _update_dataclass(dc_obj: Any, payload: Dict[str, Any]):
    for k, v in payload.items():
        if hasattr(dc_obj, k) and v is not None:
            cur = getattr(dc_obj, k)
            try:
                if isinstance(cur, bool):
                    setattr(dc_obj, k, bool(v))
                elif isinstance(cur, int):
                    setattr(dc_obj, k, int(v))
                elif isinstance(cur, float):
                    setattr(dc_obj, k, float(v))
                else:
                    setattr(dc_obj, k, str(v))
            except Exception:
                pass


@app.get("/api/physics/state")
def get_physics_state():
    return {
        "retro_intermod": retro_engine.compute_physics_model(retro_params),
        "lo_leakage": lo_engine.compute_model(lo_params),
        "speaker_microphonics": micro_engine.compute_model(micro_params),
        "pilot_sensing": pilot_engine.compute_telemetry(pilot_params),
        "beamforming_hrtf": beam_engine.compute_telemetry(beam_params),
    }


@app.post("/api/physics/retro")
def update_retro(payload: Dict[str, Any]):
    _update_dataclass(retro_params, payload)
    return retro_engine.compute_physics_model(retro_params)


@app.post("/api/physics/lo")
def update_lo(payload: Dict[str, Any]):
    _update_dataclass(lo_params, payload)
    return lo_engine.compute_model(lo_params)


@app.post("/api/physics/microphonics")
def update_microphonics(payload: Dict[str, Any]):
    _update_dataclass(micro_params, payload)
    return micro_engine.compute_model(micro_params)


@app.post("/api/physics/pilot")
def update_pilot(payload: Dict[str, Any]):
    _update_dataclass(pilot_params, payload)
    return pilot_engine.compute_telemetry(pilot_params)


@app.post("/api/physics/beamforming")
def update_beamforming(payload: Dict[str, Any]):
    _update_dataclass(beam_params, payload)
    return beam_engine.compute_telemetry(beam_params)


@app.post("/api/pluto/config")
def update_pluto_config(payload: Dict[str, Any]):
    _update_dataclass(pluto_engine.cfg, payload)
    return pluto_engine.step_telemetry()


@app.post("/api/pluto/breath")
def push_pluto_breath(payload: Dict[str, Any]):
    return pluto_engine.push_breath_token(str(payload.get("token", "")))


@app.post("/api/pluto/train")
def train_pluto_ann(payload: Dict[str, Any]):
    snap = pluto_engine.step_telemetry()
    f = snap["neural_net"]["features"]
    fv = np.array([f["rf_variance"], f["audio_rms_x100"], f["zero_crossings"]], dtype=np.float64)
    pluto_engine.online_train_step(fv, str(payload.get("target_class", "STABLE_IDLE")))
    return pluto_engine.step_telemetry()


@app.post("/api/pluto/automation")
def trigger_pluto_automation(payload: Dict[str, Any]):
    pluto_engine.execute_preemptive_automation(str(payload.get("action", "ARM_AUDIO")))
    return pluto_engine.step_telemetry()


@app.post("/api/pluto/earworm")
def export_pluto_earworm():
    return pluto_engine.export_earworm_snapshots(LOGS_DIR)


@app.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket):
    await ws.accept()
    tick = 0
    try:
        while True:
            tick += 1
            frame = build_unified_frame(
                tick=tick,
                retro_snap=retro_engine.compute_physics_model(retro_params),
                lo_snap=lo_engine.compute_model(lo_params),
                micro_snap=micro_engine.compute_model(micro_params),
                pilot_snap=pilot_engine.compute_telemetry(pilot_params),
                beam_snap=beam_engine.compute_telemetry(beam_params),
                pluto_snap=pluto_engine.step_telemetry(),
            )
            await ws.send_json(frame)
            await asyncio.sleep(0.18)
    except WebSocketDisconnect:
        return
    except Exception:
        return


# Serve built UI if dist exists
DIST_DIR = ROOT_DIR / "ui" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="ui_dist")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
