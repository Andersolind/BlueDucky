"""
AI-Voice to Ollama SIGINT Tactical Bridge
=========================================
Feeds live multi-sensor acoustic telemetry, PANNs beam detection classifications,
HuBERT token patterns, and SDR EMI power metrics into local Ollama models for
cognitive threat attribution, triangulation tracking, and tactical countermeasures.
"""

import json
import time
import requests
from typing import Dict, Any, Optional

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "nightsweep-signalintelligence:latest"

class OllamaSIGINTBridge:
    """Interface connecting AI-Voice multi-sensor feeds to local Ollama runtime."""

    def __init__(self, host: str = DEFAULT_OLLAMA_HOST, model: str = DEFAULT_MODEL):
        self.host = host.rstrip("/")
        self.model = model

    def check_health(self) -> Dict[str, Any]:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3.0)
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                return {
                    "online": True,
                    "models": models,
                    "active_model": self.model,
                    "model_available": any(self.model in m or m in self.model for m in models)
                }
        except Exception as e:
            return {"online": False, "error": str(e), "models": []}
        return {"online": False, "models": []}

    def analyze_telemetry_frame(self, telemetry: Dict[str, Any]) -> str:
        """
        Sends structured multi-sensor acoustic and RF telemetry matrix to Ollama
        for tactical assessment.
        """
        panns = telemetry.get("panns_prediction", {})
        traj = telemetry.get("trajectory", {})
        emi_power = telemetry.get("rtl_emi_power", 0.0)
        ult_peak = telemetry.get("ultrasound_peak", 0.0)
        vocal_energy = telemetry.get("vocal_energy", 0.0)
        t0_sync = telemetry.get("rf_sync_last_t0")

        prompt = f"""### AI-VOICE MULTI-SENSOR ACOUSTIC & RF INTELLIGENCE DATA MATRIX:
- Telemetry Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
- Audible Vocal RMS Energy: {vocal_energy:.5f}
- Dodotronic 192kHz Ultrasound Peak Amplitude: {ult_peak:.5f}
- RTL-SDR Transducer EMI Leakage Power: {emi_power:.8f}
- HackRF T0 RF Sync Pulse State: {"TRIGGERED" if t0_sync else "UNSYNCED / LISTENING"}

#### Neural Acoustic Beam Classification (PANNs CNN14):
- Classified State: {panns.get("label", "Unknown")}
- Beam Detection Confidence: {panns.get("confidence", 0.0):.4f}
- Active Beam Path Flag: {panns.get("is_beam_active", False)}

#### Spatial Kinematics & Trajectory Interceptor:
- Target Estimated Range: {traj.get("real_distance_m", 0.0):.2f} meters
- Real Expected Time-of-Flight: {traj.get("real_tof_ms", 0.0):.2f} ms
- Injection Window Timing: {traj.get("injection_delay_ms", 0.0):.2f} ms past T0
- Tactical Intercept Mode: {traj.get("state", "IDLE")}

### REQUIRED TACTICAL BRIEFING:
Provide a concise 3-part tactical assessment:
1. **Threat & Beam Assessment**: Evaluate whether active acoustic triangulation/beamforming is occurring.
2. **Multi-Domain Correlation**: Correlate the ultrasound peak, EMI power, and RF sync pulse.
3. **Countermeasure Recommendation**: Provide tactical recommendations (e.g. injection delay, acoustic masking, or RF shielding).
"""
        return self._query(prompt)

    def _query(self, prompt: str) -> str:
        url = f"{self.host}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_ctx": 4096
            }
        }
        try:
            resp = requests.post(url, json=payload, timeout=180.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "").strip()
            else:
                return f"⚠️ Ollama Error ({resp.status_code}): {resp.text}"
        except Exception as e:
            return f"⚠️ Ollama Connection Error: {e}"
