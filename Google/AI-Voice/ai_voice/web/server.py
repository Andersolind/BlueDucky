"""
AI-Voice Tactical Web Server & REST / WebSocket API
===================================================
Provides real-time streaming telemetry, multi-sensor controls,
PANNs neural beam detection, HuBERT voice conversion, spatial heatmap data,
and Ollama cognitive advisor queries.
"""

import os
import json
import time
import asyncio
from typing import Dict, Any, Optional
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from ai_voice.config import PipelineConfig
from ai_voice.models.pipeline import UnifiedAIVoicePipeline
from ai_voice.telemetry.monitor import LivePerformanceTracker
from ai_voice.telemetry.dataset_logger import AutomatedDatasetLogger
from ai_voice.ollama_bridge import OllamaSIGINTBridge

app = FastAPI(title="AI-Voice Multi-Sensor & Neural SIGINT Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
CONFIG = PipelineConfig()
PIPELINE = UnifiedAIVoicePipeline(CONFIG)
TELEMETRY = LivePerformanceTracker(CONFIG)
DATASET_LOGGER = AutomatedDatasetLogger(CONFIG.dataset, CONFIG.dsp, sample_rate=CONFIG.hardware.sample_rate_in)
OLLAMA_BRIDGE = OllamaSIGINTBridge(host=CONFIG.ollama_host, model=CONFIG.ollama_model)

active_websockets = set()

# WebSocket Telemetry Dispatcher
async def broadcast_telemetry_loop():
    while True:
        await asyncio.sleep(0.1) # 10 Hz broadcast
        if not active_websockets:
            continue
        
        telemetry_data = TELEMETRY.collect_telemetry()
        pipeline_state = PIPELINE.last_state.copy()
        
        # Format payload
        payload = {
            "type": "telemetry",
            "timestamp": time.time(),
            "pipeline_running": PIPELINE.is_running,
            "telemetry": telemetry_data,
            "state": {
                "vocal_energy": pipeline_state.get("vocal_energy", 0.0),
                "is_speaking": pipeline_state.get("is_speaking", False),
                "cable_spike_rejected": pipeline_state.get("cable_spike_rejected", False),
                "ultrasound_peak": pipeline_state.get("ultrasound_peak", 0.0),
                "rtl_emi_power": pipeline_state.get("rtl_emi_power", 0.0),
                "panns": pipeline_state.get("panns_prediction", {}),
                "trajectory": pipeline_state.get("trajectory", {}),
                "rf_sync_last_t0": pipeline_state.get("rf_sync_last_t0")
            }
        }
        
        dead_sockets = set()
        for ws in active_websockets:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead_sockets.add(ws)
        active_websockets.difference_update(dead_sockets)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_telemetry_loop())

# Static Files Directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h1>AI-Voice Server Active</h1><p>UI loading...</p>")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "time": time.time()}))
                elif action == "trigger_injection":
                    dist = float(msg.get("spoof_distance", 3.5))
                    real_tof = PIPELINE.trajectory_interceptor.track_and_predict_trajectory()
                    res = PIPELINE.trajectory_interceptor.calculate_injection_window(real_tof, spoof_distance=dist)
                    await websocket.send_text(json.dumps({"type": "injection_result", "data": res}))
            except Exception:
                pass
    except WebSocketDisconnect:
        active_websockets.discard(websocket)

# REST Endpoints
@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "pipeline_running": PIPELINE.is_running,
        "telemetry": TELEMETRY.collect_telemetry(),
        "ollama": OLLAMA_BRIDGE.check_health(),
        "config": CONFIG.to_dict()
    }

@app.get("/api/devices")
async def list_devices():
    return {
        "audio_devices": PIPELINE.audio_mgr.list_devices(),
        "dodotronic_suggested_index": PIPELINE.audio_mgr.find_dodotronic_index()
    }

@app.post("/api/pipeline/start")
async def start_pipeline():
    PIPELINE.start_streaming()
    return {"status": "started", "is_running": PIPELINE.is_running}

@app.post("/api/pipeline/stop")
async def stop_pipeline():
    PIPELINE.stop_streaming()
    return {"status": "stopped", "is_running": PIPELINE.is_running}

@app.post("/api/pipeline/batch_capture")
async def batch_capture(duration: float = 3.0):
    res = PIPELINE.run_single_batch_inference(duration_sec=duration)
    return {"status": "success", "result": res}

@app.get("/api/spatial/grid")
async def get_spatial_grid():
    norm_grid = PIPELINE.spatial_grid.get_normalized_grid()
    return {
        "grid": norm_grid,
        "grid_size": PIPELINE.spatial_grid.grid_size,
        "max_radius": PIPELINE.spatial_grid.max_radius,
        "resolution": PIPELINE.spatial_grid.resolution
    }

@app.post("/api/spatial/trajectory/update")
async def update_trajectory(distance: Optional[float] = Form(None), velocity: Optional[float] = Form(None), spoof_distance: float = Form(3.5)):
    if distance is not None:
        PIPELINE.trajectory_interceptor.set_distance(distance)
    if velocity is not None:
        PIPELINE.trajectory_interceptor.update_velocity(velocity)
    
    real_tof = PIPELINE.trajectory_interceptor.track_and_predict_trajectory()
    res = PIPELINE.trajectory_interceptor.calculate_injection_window(real_tof, spoof_distance=spoof_distance)
    return {"status": "success", "trajectory": res}

@app.post("/api/ollama/analyze")
async def ollama_analyze():
    state = PIPELINE.last_state.copy()
    telemetry = TELEMETRY.collect_telemetry()
    state.update(telemetry)
    assessment = OLLAMA_BRIDGE.analyze_telemetry_frame(state)
    return {
        "status": "success",
        "model": OLLAMA_BRIDGE.model,
        "assessment": assessment,
        "state_snapshot": state
    }

@app.post("/api/ollama/chat")
async def ollama_chat(prompt: str = Form(...)):
    res = OLLAMA_BRIDGE._query(prompt)
    return {"status": "success", "response": res}

@app.get("/api/dataset/manifest")
async def get_dataset_manifest():
    manifest_path = DATASET_LOGGER.manifest_path
    lines = []
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()][-50:] # last 50 entries
    return {
        "manifest_path": manifest_path,
        "total_lines": TELEMETRY.collect_telemetry()["manifest_line_count"],
        "recent_entries": lines
    }

def create_server():
    return app
