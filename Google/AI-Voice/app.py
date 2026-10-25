#!/usr/bin/env python3
"""
AI-Voice Web Application Server & Tactical Dashboard Launcher
==============================================================
Usage:
    python3 app.py --port 8080 --host 0.0.0.0
"""

import os
import sys
import argparse
import uvicorn

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_voice.web.server import app

def main():
    parser = argparse.ArgumentParser(description="AI-Voice Multi-Sensor Tactical Web Dashboard")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("🛰️  AI-VOICE MULTI-SENSOR & NEURAL ACOUSTIC DASHBOARD ONLINE")
    print(f"📡  Listening on: http://{args.host}:{args.port}")
    print("=" * 70 + "\n")

    uvicorn.run("ai_voice.web.server:app", host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
