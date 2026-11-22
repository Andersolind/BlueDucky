# EarArray — Spatial Ultrasonic Sonar, Zero-Equipment Mid-Air Subvocal + PlutoSDR Self-Learner & HRTF Telemetry Suite

Air-gapped spatial acoustic defense, bidirectional reverse-physics modeling, multi-node ultrasonic Time-of-Flight (TOF) self-calibration, non-contact mid-air sublevel vocalization + ADALM-Pluto SDR self-supervised learning, and Vue 3 + Three.js 3D telemetry console powered by `ollama run andersolind/nightsweep-sigint`.

---

## Core Architecture & Modules

| Module | Category | Description |
| :--- | :--- | :--- |
| `audible_enclave_prototype.py` | **Nonlinear Metasurfaces + 7-Layer Tactical Stack** | Dual 3D-printed subwavelength metasurface Airy self-bending ultrasonic beams ($f_1 = 40\text{ kHz}, f_2 = 39\text{ kHz}$) forming localized **Audible Enclaves** ($f_2 - f_1 = 125\text{ Hz}\text{--}4\text{ kHz}$, $>35\text{ dB}$ isolation) + **20 kHz Non-Contact Vocal Reconstruction** (sub-mm throat vibrometry, zero sEMG electrodes), **GPS-UTC 100m Grid FHSS Shielding**, **32-Tap Adaptive LMS Echo Canceller**, **Cognitive Loop Delivery** ($250\text{ Hz} / 261\text{ Hz} \rightarrow 11\text{ Hz}$ Alpha Binaural Monologue), **Living-Room Wall-Bounce TOF Convergence**, **Wideband 24 kHz Parallel Goertzel Decoder** (DTMF keypad, ITU-T T.30/V.21 fax, ultrasonic FSK), and **Priority SQLite Spatial-Temporal Journaling** (`logs/tactical_spatial_journal.sqlite`). |
| `midair_subvocal_pluto_learner.py` | **Zero-Equipment Self-Supervised AI** | Pure mid-air $20\text{ kHz} / 19\text{ kHz}$ ultrasonic carrier laryngeal phase demodulation ($\Delta\phi = \frac{4\pi f_p}{c}\delta x$ for $5\text{--}145\,\mu\text{m}$ skin displacement under $\le 28\text{ dB SPL}$ silence), 32-tap NLMS multipath clutter cancellation, Acoustic $\leftrightarrow$ PlutoSDR ($144.3 / 144.8\text{ MHz}$ NBFM) cross-modal coherence teacher gating ($\gamma^2 \ge 0.62$), and online 6-class Softmax + EMA prototype self-learning (`ALPHA_LOCK`, `SILENT_RELAY`, `PHASE_NULL`). |
| `spatial_tof_calibration.py` | **10m×10m Ultrasonic Trilateration** | `execute_hardware_self_calibration(tof_12, tof_13)` dynamically computes `NODE_1` $[0,10]$, `NODE_2` $[0,y_2]$, and `NODE_3` $[x_3,0]$ baseline geometry ($c = 343.0\text{ m/s}$), while `compute_spatial_trajectory_overlay(x, y)` maps targets across NE, NW, SE, and SW architectural quadrants. |
| `pluto_neural_bridge.py` | **SDR + JACK/REAPER OSC + Bio-Macro ANN** | $144.3 / 144.8\text{ MHz}$ ADALM-Pluto $\leftrightarrow$ JACK (`sdr_demod_to_reaper`, `reaper_fx_to_sdr`) & Cockos REAPER OSC (`127.0.0.1:8000`) track arming, 10s Earworm WAV snapshot buffer, online 4-class Softmax ANN, and Breath-to-Morse (`CQ`, `READY`, `OK`) synthesizer. |
| `retroreflection_intermod.py` | **Bidirectional Acoustics** | Models passive clothing scatter, torso cardiopulmonary micro-Doppler, and throat vibrometry vs. active $20\text{ kHz} / 19\text{ kHz}$ opposing pilot Westervelt mid-air heterodyne mixing ($1\text{ kHz}$ audible difference tone). |
| `reverse_physics_suite.py` | **Counter-Observation Physics** | Receive-only SDR internal mixer Local Oscillator (LO) port/chassis radiation spatial heatmap + dynamic speaker voice-coil Faraday back-EMF ($V_{\text{emf}} = B \cdot l \cdot v_{\text{cone}}$) microphonics. |
| `sensing_and_beamforming.py` | **Non-Contact & Spatial Delivery** | Continuous-wave ultrasonic pilot I/Q quadrature phase unwrapping vibrometry + Delay-and-Sum 8-mic array steering and Woodworth binaural HRTF (ITD/ILD) spatial targeting. |
| `earDefence.py` / `sniitch4ears.py` | **Ultrasonic Sonar Defense** | FIR bandpass + Welch PSD + cross-channel SVM classifier & 7-stage false-positive validation pipeline. |
| `benine4u.py` / `snitchingElectronics.py` | **Forensics & Replay Attribution** | Detects modulated ultrasonic carriers, Hilbert envelopes, speaker THD rolloff, SilverPush/Lisnr/TV ACR beacons, and spectrogram/WAV forensics (`dolphin_forensics/`). |
| `carDefender.py` / `4snitichingcars.py` | **BLE + Automotive Transducer Scanner** | Log-distance BLE ranging, Apple Live Listen A2DP sink/source inspection, and Subaru STARLINK / Harman Kardon 576W 12-speaker 40–48 kHz ultrasonic sensor telemetry. |
| `toneSnicher2026.py` | **CSI + GCC-PHAT DOA** | 64-subcarrier Wi-Fi CSI motion, GCC-PHAT TDOA/DOA, WebRTC VAD, and 16-band SHA-1 geometric audio fingerprints. |

---

## Quick Start

### 1. Build the Local Ollama SIGINT Model (`andersolind/nightsweep-sigint`)
```bash
ollama create andersolind/nightsweep-sigint -f Modelfile
ollama run andersolind/nightsweep-sigint
```

### 2. Run the Self-Bending Ultrasonic Audible Enclave Prototype (CLI + 192kHz/48kHz WAV Synthesizer)
```bash
python3 audible_enclave_prototype.py --mode PRIVATE_ENCLAVE --f1 40000 --f2 39000 --export-wav
```

### 3. Run the Standalone Zero-Equipment Mid-Air Subvocal + PlutoSDR Self-Learner
```bash
python3 midair_subvocal_pluto_learner.py --epochs 25 --inject SILENT_RELAY --ollama-model andersolind/nightsweep-sigint --advise
```

### 4. Launch the Full-Stack FastAPI + Vue 3 / Three.js Spatial Telemetry Console
```bash
./start_ui.sh
# Or build the production UI and serve from FastAPI on http://0.0.0.0:8765:
cd ui && npm install && npm run build && cd ..
python3 backend/server.py
```

### 4. Run End-to-End Unit & Integration Tests
```bash
python3 -m unittest test_eararray_suite.py -v
```
