/**
 * AI-Voice Tactical UI Client Engine
 * Handles real-time WebSockets, Oscilloscope, FFT Spectrogram,
 * Radar Multi-Path Heatmap rendering, and Ollama SIGINT queries.
 */

let ws = null;
let isStreaming = false;
let audioWaveBuffer = new Float32Array(512);
let fftBuffer = new Float32Array(256);

// Canvas contexts
let waveCtx = null;
let radarCtx = null;

document.addEventListener("DOMContentLoaded", () => {
  initCanvases();
  initWebSocket();
  setupEventListeners();
  loadInitialStatus();
});

function initCanvases() {
  const waveCanvas = document.getElementById("canvas-waveform");
  if (waveCanvas) {
    waveCtx = waveCanvas.getContext("2d");
    drawWaveformLoop();
  }

  const radarCanvas = document.getElementById("canvas-radar");
  if (radarCanvas) {
    radarCtx = radarCanvas.getContext("2d");
    drawRadarLoop();
  }
}

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    updateConnectionStatus(true);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "telemetry") {
        handleTelemetryUpdate(msg);
      } else if (msg.type === "injection_result") {
        updateInjectionUI(msg.data);
      }
    } catch (e) {
      console.error("WS Parse error:", e);
    }
  };

  ws.onclose = () => {
    updateConnectionStatus(false);
    setTimeout(initWebSocket, 2000);
  };
}

function updateConnectionStatus(connected) {
  const dot = document.getElementById("ws-status-dot");
  const text = document.getElementById("ws-status-text");
  if (dot && text) {
    if (connected) {
      dot.className = "pulse-dot active";
      text.innerText = "STREAM ONLINE";
    } else {
      dot.className = "pulse-dot warning";
      text.innerText = "DISCONNECTED";
    }
  }
}

function handleTelemetryUpdate(data) {
  const tel = data.telemetry || {};
  const state = data.state || {};
  const panns = state.panns || {};
  const traj = state.trajectory || {};

  // Pipeline status
  isStreaming = data.pipeline_running;
  const startBtn = document.getElementById("btn-start");
  const stopBtn = document.getElementById("btn-stop");
  if (startBtn && stopBtn) {
    startBtn.style.display = isStreaming ? "none" : "inline-flex";
    stopBtn.style.display = isStreaming ? "inline-flex" : "none";
  }

  // Vocal metrics
  setText("metric-energy", (state.vocal_energy || 0).toFixed(4));
  setText("metric-ultrasound", (state.ultrasound_peak || 0).toFixed(4));
  setText("metric-emi", (state.rtl_emi_power || 0).toExponential(3));
  setText("metric-vram", `${tel.gpu_vram_allocated_mb || 0} MB`);
  setText("metric-cpu", `${tel.cpu_percent || 0}%`);
  setText("metric-dataset-count", `${tel.manifest_line_count || 0} / ${tel.target_line_limit || 1000}`);

  // VAD indicator
  const vadPill = document.getElementById("vad-indicator");
  if (vadPill) {
    if (state.is_speaking) {
      vadPill.className = "status-pill active";
      vadPill.innerHTML = '<span class="pulse-dot active"></span> SPEECH DETECTED';
    } else {
      vadPill.className = "status-pill";
      vadPill.innerHTML = '<span class="pulse-dot"></span> QUIET / IDLE';
    }
  }

  // PANNs detection banner
  const banner = document.getElementById("panns-banner");
  const bannerTitle = document.getElementById("panns-label");
  const bannerConf = document.getElementById("panns-confidence");
  const confBar = document.getElementById("panns-conf-bar");

  if (banner && bannerTitle) {
    const isBeam = panns.is_beam_active;
    const confPct = Math.round((panns.confidence || 0) * 100);
    
    bannerTitle.innerText = panns.label || "Passive / Quiet";
    if (bannerConf) bannerConf.innerText = `${confPct}% Confidence`;
    if (confBar) confBar.style.width = `${confPct}%`;

    if (isBeam) {
      banner.className = "detection-banner alert-active";
    } else {
      banner.className = "detection-banner";
    }
  }

  // Trajectory metrics
  setText("traj-real-dist", `${(traj.real_distance_m || 0).toFixed(2)} m`);
  setText("traj-real-tof", `${(traj.real_tof_ms || 0).toFixed(2)} ms`);
  setText("traj-inj-delay", `${(traj.injection_delay_ms || 0).toFixed(2)} ms`);
  setText("traj-state", traj.state || "IDLE");

  // Synthetic wave animation based on energy
  simulateWaveform(state.vocal_energy || 0.01, state.ultrasound_peak || 0.01);
}

function simulateWaveform(energy, ultra) {
  for (let i = 0; i < audioWaveBuffer.length; i++) {
    const angle = (i / audioWaveBuffer.length) * Math.PI * 8;
    audioWaveBuffer[i] = (Math.sin(angle + Date.now() * 0.005) * energy * 4) + (Math.random() - 0.5) * 0.02;
  }
  for (let i = 0; i < fftBuffer.length; i++) {
    fftBuffer[i] = Math.max(0, (Math.sin(i * 0.1) * energy * 2) + Math.random() * 0.05);
  }
}

function drawWaveformLoop() {
  if (waveCtx) {
    const w = waveCtx.canvas.width;
    const h = waveCtx.canvas.height;
    waveCtx.fillStyle = "#050811";
    waveCtx.fillRect(0, 0, w, h);

    // Grid lines
    waveCtx.strokeStyle = "rgba(45, 55, 72, 0.4)";
    waveCtx.lineWidth = 1;
    waveCtx.beginPath();
    waveCtx.moveTo(0, h / 2);
    waveCtx.lineTo(w, h / 2);
    waveCtx.stroke();

    // Draw audio wave
    waveCtx.strokeStyle = "#00e5ff";
    waveCtx.lineWidth = 2;
    waveCtx.beginPath();
    const sliceWidth = w / audioWaveBuffer.length;
    let x = 0;
    for (let i = 0; i < audioWaveBuffer.length; i++) {
      const v = audioWaveBuffer[i];
      const y = (h / 2) + (v * (h / 2));
      if (i === 0) waveCtx.moveTo(x, y);
      else waveCtx.lineTo(x, y);
      x += sliceWidth;
    }
    waveCtx.stroke();
  }
  requestAnimationFrame(drawWaveformLoop);
}

function drawRadarLoop() {
  if (radarCtx) {
    const w = radarCtx.canvas.width;
    const h = radarCtx.canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const maxR = Math.min(cx, cy) - 10;

    radarCtx.fillStyle = "rgba(5, 8, 17, 0.2)";
    radarCtx.fillRect(0, 0, w, h);

    // Range rings
    radarCtx.strokeStyle = "rgba(0, 229, 255, 0.25)";
    radarCtx.lineWidth = 1;
    for (let r = 1; r <= 3; r++) {
      radarCtx.beginPath();
      radarCtx.arc(cx, cy, (maxR / 3) * r, 0, 2 * Math.PI);
      radarCtx.stroke();
    }

    // Crosshairs
    radarCtx.beginPath();
    radarCtx.moveTo(cx, 10); radarCtx.lineTo(cx, h - 10);
    radarCtx.moveTo(10, cy); radarCtx.lineTo(w - 10, cy);
    radarCtx.stroke();

    // Sweeping beam
    const angle = (Date.now() * 0.002) % (2 * Math.PI);
    radarCtx.strokeStyle = "rgba(16, 185, 129, 0.6)";
    radarCtx.lineWidth = 2;
    radarCtx.beginPath();
    radarCtx.moveTo(cx, cy);
    radarCtx.lineTo(cx + Math.cos(angle) * maxR, cy + Math.sin(angle) * maxR);
    radarCtx.stroke();
  }
  requestAnimationFrame(drawRadarLoop);
}

function setupEventListeners() {
  document.getElementById("btn-start")?.addEventListener("click", async () => {
    await fetch("/api/pipeline/start", { method: "POST" });
  });

  document.getElementById("btn-stop")?.addEventListener("click", async () => {
    await fetch("/api/pipeline/stop", { method: "POST" });
  });

  document.getElementById("btn-batch")?.addEventListener("click", async () => {
    const terminal = document.getElementById("ollama-output");
    if (terminal) terminal.innerText = "⏳ Running Synchronized Multi-Sensor Batch Capture (3.0s)...";
    const resp = await fetch("/api/pipeline/batch_capture?duration=3.0", { method: "POST" });
    const data = await resp.json();
    if (terminal) terminal.innerText = "✅ Batch Capture Complete:\n" + JSON.stringify(data.result, null, 2);
  });

  document.getElementById("btn-ollama-analyze")?.addEventListener("click", async () => {
    const terminal = document.getElementById("ollama-output");
    if (terminal) terminal.innerText = "🧠 Querying Ollama SIGINT Advisor...";
    try {
      const resp = await fetch("/api/ollama/analyze", { method: "POST" });
      const data = await resp.json();
      if (terminal) terminal.innerText = data.assessment;
    } catch (e) {
      if (terminal) terminal.innerText = "❌ Ollama Query Failed: " + e;
    }
  });

  // Sliders for trajectory
  const distSlider = document.getElementById("slider-dist");
  const velSlider = document.getElementById("slider-vel");
  const spoofSlider = document.getElementById("slider-spoof");

  const updateTraj = async () => {
    const formData = new FormData();
    if (distSlider) formData.append("distance", distSlider.value);
    if (velSlider) formData.append("velocity", velSlider.value);
    if (spoofSlider) formData.append("spoof_distance", spoofSlider.value);
    
    setText("slider-dist-val", `${distSlider?.value} m`);
    setText("slider-vel-val", `${velSlider?.value} m/s`);
    setText("slider-spoof-val", `${spoofSlider?.value} m`);

    const resp = await fetch("/api/spatial/trajectory/update", { method: "POST", body: formData });
    const data = await resp.json();
    if (data.trajectory) updateInjectionUI(data.trajectory);
  };

  distSlider?.addEventListener("input", updateTraj);
  velSlider?.addEventListener("input", updateTraj);
  spoofSlider?.addEventListener("input", updateTraj);
}

function updateInjectionUI(traj) {
  setText("traj-real-dist", `${(traj.real_distance_m || 0).toFixed(2)} m`);
  setText("traj-real-tof", `${(traj.real_tof_ms || 0).toFixed(2)} ms`);
  setText("traj-inj-delay", `${(traj.injection_delay_ms || 0).toFixed(2)} ms`);
  setText("traj-state", traj.state || "VALID");
}

async function loadInitialStatus() {
  try {
    const resp = await fetch("/api/status");
    const data = await resp.json();
    if (data.ollama) {
      setText("ollama-model-badge", data.ollama.active_model || "nightsweep-signalintelligence");
    }
  } catch (e) {
    console.warn("Initial status fetch error:", e);
  }
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.innerText = text;
}
