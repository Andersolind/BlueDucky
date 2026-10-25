# AI-Voice: Unified Multi-Sensor Acoustic & RF Signal Intelligence Suite

A production-grade, modular framework for multi-domain acoustic triangulation, Dodotronic 192kHz ultrasonic demodulation, PANNs neural beam path detection, HuBERT bone-conduction voice synthesis tokenization, RTL-SDR EMI leakage correlation, HackRF T0 synchronization, and Ollama cognitive tactical briefings.

## Architecture

```
AI-Voice/
├── ai_voice/
│   ├── config.py                 # Structured dataclass configurations & profile serialization
│   ├── ollama_bridge.py          # Cognitive Tactical Bridge to local Ollama SIGINT models
│   ├── dsp/
│   │   ├── filters.py            # Vocal Butterworth bandpass, multi-notch array, dynamic spectral gating
│   │   ├── resampler.py          # Anti-aliasing multi-rate converters (192kHz -> 48kHz -> 16kHz)
│   │   └── spatial.py            # TrajectoryInterceptor & 2D Polar-to-Cartesian Spatial Density Grid
│   ├── hardware/
│   │   ├── audio.py              # PyAudio abstraction & transparent synthetic stream fallback
│   │   ├── sdr.py                # RTL-SDR EMI capture & HackRF high-speed T0 sync sniffer
│   │   └── multi_sensor.py       # Asynchronous parallel multi-domain capture orchestrator
│   ├── models/
│   │   ├── panns_detector.py     # Cnn14 Acoustic Beam & Triangulation Neural Classifier
│   │   ├── hubert_converter.py   # HuBERT semantic token extractor & StreamingVoiceConverter
│   │   └── pipeline.py           # End-to-end unified processing pipeline
│   ├── telemetry/
│   │   ├── monitor.py            # Real-time GPU VRAM, CPU, and dataset telemetry engine
│   │   └── dataset_logger.py     # Automated StyleTTS2 manifest & metadata index builder
│   └── web/
│       ├── server.py             # FastAPI & WebSocket high-frequency real-time server
│       └── static/               # Cyber/Tactical Material 3 dashboard (HTML5, JS, CSS)
├── app.py                        # Web dashboard launcher
├── cli.py                        # Command-line interface
└── tests/
    └── test_ai_voice.py          # Complete unit test suite
```

## Quick Start

### 1. Launch Tactical Web Dashboard
```bash
python3 app.py --port 8080 --host 0.0.0.0
```
Open `http://localhost:8080` in your browser.

### 2. Command-Line Operations
```bash
# System & hardware status
python3 cli.py status

# Run 3-second synchronized multi-sensor batch capture & neural classification
python3 cli.py batch --duration 3.0

# Simulate dynamic spatial trajectory tracking & spoof injection window
python3 cli.py trajectory --distance 6.0 --velocity -0.8 --spoof-distance 3.5

# Query local Ollama SIGINT tactical model
python3 cli.py ollama
```

### 3. Run Automated Tests
```bash
pytest tests/ -v
```
