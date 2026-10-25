#!/usr/bin/env python3
"""
AI-Voice Command Line Interface (CLI)
=====================================
Provides command-line commands for:
- Live streaming multi-sensor capture
- Batch capture & PANNs neural beam classification
- HuBERT semantic tokenization & speaker profile extraction
- Trajectory ToF injection calculations
- Ollama SIGINT cognitive reasoning briefings
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_voice.config import PipelineConfig
from ai_voice.models.pipeline import UnifiedAIVoicePipeline
from ai_voice.dsp.spatial import TrajectoryInterceptor
from ai_voice.telemetry.monitor import LivePerformanceTracker
from ai_voice.ollama_bridge import OllamaSIGINTBridge

def cmd_status(args, config):
    print("\n--- [SYSTEM & HARDWARE STATUS] ---")
    pipeline = UnifiedAIVoicePipeline(config)
    tracker = LivePerformanceTracker(config)
    telemetry = tracker.collect_telemetry()
    devices = pipeline.audio_mgr.list_devices()
    dodo_idx = pipeline.audio_mgr.find_dodotronic_index()
    ollama = OllamaSIGINTBridge(host=config.ollama_host, model=config.ollama_model).check_health()

    print(f"Device: {telemetry['device_type'].upper()}")
    print(f"VRAM Allocated: {telemetry['gpu_vram_allocated_mb']} MB / Cached: {telemetry['gpu_vram_cached_mb']} MB")
    print(f"Dataset Manifest Count: {telemetry['manifest_line_count']} / {telemetry['target_line_limit']}")
    print(f"Dodotronic Detected Index: {dodo_idx if dodo_idx is not None else 'Not Found (Using Simulated Stream)'}")
    print(f"Ollama Daemon: {'ONLINE' if ollama['online'] else 'OFFLINE'} | Model: {ollama.get('active_model')}")
    print("\nAvailable Audio Devices:")
    for d in devices:
        print(f"  [{d['index']}] {d['name']} (In: {d['inputs']}, Out: {d['outputs']})")
    print("---------------------------------\n")

def cmd_batch(args, config):
    duration = args.duration
    print(f"[*] Executing synchronized {duration}s batch capture across all sensors...")
    pipeline = UnifiedAIVoicePipeline(config)
    result = pipeline.run_single_batch_inference(duration_sec=duration)
    print("\n[✔] Multi-Sensor Batch Results:")
    print(f"  - RTL-SDR EMI Power: {result['rtl_emi_power']:.8f}")
    print(f"  - RF T0 Sync Triggers: {result['rf_t0_count']}")
    print(f"  - PANNs Classification: {result['panns_prediction']['label']}")
    print(f"  - PANNs Confidence: {result['panns_prediction']['confidence']*100:.2f}%")
    if result.get("hubert_token_shape"):
        print(f"  - HuBERT Semantic Tensor Shape: {result['hubert_token_shape']}")
    print("\n")

def cmd_trajectory(args, config):
    interceptor = TrajectoryInterceptor(
        target_distance_init=args.distance,
        velocity=args.velocity,
        speed_of_sound=config.spatial.speed_of_sound
    )
    print("\n--- [SPATIAL TRAJECTORY INTERCEPT SIMULATOR] ---")
    for frame in range(1, args.frames + 1):
        time.sleep(0.3)
        real_tof = interceptor.track_and_predict_trajectory()
        res = interceptor.calculate_injection_window(real_tof, spoof_distance=args.spoof_distance)
        print(f"[Frame {frame:02d}] Real Distance: {res['real_distance_m']:.2f}m | Real ToF: {res['real_tof_ms']:.2f}ms")
        print(f"         └──► Status: {res['state']} | Tx Pulse Delay: {res['injection_delay_ms']:.2f}ms past T0\n")

def cmd_ollama(args, config):
    print("[*] Performing Multi-Sensor Diagnostic and Querying Ollama...")
    pipeline = UnifiedAIVoicePipeline(config)
    tracker = LivePerformanceTracker(config)
    telemetry = tracker.collect_telemetry()
    state = pipeline.last_state.copy()
    state.update(telemetry)

    bridge = OllamaSIGINTBridge(host=config.ollama_host, model=config.ollama_model)
    health = bridge.check_health()
    if not health["online"]:
        print("⚠️ Ollama is offline. Start it with `ollama serve`.")
        return

    print(f"🧠 Tactical Briefing from `{bridge.model}`:\n")
    report = bridge.analyze_telemetry_frame(state)
    print("=" * 70)
    print(report)
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="AI-Voice Multi-Sensor & Neural CLI")
    parser.add_argument("--config", type=str, default=None, help="Path to config.json")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Status
    p_status = subparsers.add_parser("status", help="Show system, hardware, and Ollama status")

    # Batch
    p_batch = subparsers.add_parser("batch", help="Run synchronized multi-sensor batch inference")
    p_batch.add_argument("--duration", type=float, default=3.0, help="Batch duration in seconds")

    # Trajectory
    p_traj = subparsers.add_parser("trajectory", help="Run trajectory tracking and injection window solver")
    p_traj.add_argument("--distance", type=float, default=6.0, help="Initial target distance in meters")
    p_traj.add_argument("--velocity", type=float, default=-0.8, help="Target velocity in m/s")
    p_traj.add_argument("--spoof-distance", type=float, default=3.5, help="Desired spoofed distance in meters")
    p_traj.add_argument("--frames", type=int, default=5, help="Number of tracking frames to simulate")

    # Ollama
    p_ollama = subparsers.add_parser("ollama", help="Run cognitive tactical analysis via Ollama")

    args = parser.parse_args()
    config = PipelineConfig.load_from_file(args.config) if args.config else PipelineConfig()

    if args.command == "status":
        cmd_status(args, config)
    elif args.command == "batch":
        cmd_batch(args, config)
    elif args.command == "trajectory":
        cmd_trajectory(args, config)
    elif args.command == "ollama":
        cmd_ollama(args, config)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
