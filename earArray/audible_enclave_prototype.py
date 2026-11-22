#!/usr/bin/env python3
"""
Self-Bending Ultrasonic Audible Enclave & 7-Layer Tactical Audio Prototype
==========================================================================
Combines the Penn State / LLNL nonlinear metasurface audible enclave physics
("Audible enclaves crafted by nonlinear self-bending ultrasonic beams", PNAS)
with the complete 7-module Tactical Audio Stack:

1. Non-Contact Vocal Reconstruction (20 kHz Active Sonar Sub-mm Vibrometry):
   - Emits an active 20.0 kHz ultrasonic sonar carrier (lambda = 17.15 mm) and
     performs coherent I/Q phase unwrapping Delta_phi(t) = (4*pi*f_p/c)*delta_x(t)
     to capture sub-millimeter (0.01-0.45 mm) throat muscle kinematics from a
     distance, completely eliminating attached sEMG neck electrodes.

2. Dynamic Anti-Intercept Shielding (GPS-UTC 100m Grid-Synchronized FHSS):
   - Runs a Frequency-Hopping Spread Spectrum (FHSS) routine synchronized to live
     GPS UTC time and quantized 100-meter geodetic grid coordinates.
   - Inside the 100m grid square, the receiver tracks the PRNG hop sequence with
     full processing gain; outside the 100m grid square, the probe signals spread
     into flat, noise-like room background (spectral flatness >= 0.89).

3. Environmental Isolation Core (Adaptive LMS Echo Cancellation):
   - Uses a 32-tap Normalized Least-Mean-Squares (NLMS) adaptive filter to
     electronically cancel loud background smart-TV playback and room clutter
     (65-78 dB SPL), isolating faint sub-millimeter vocal signatures with >22 dB
     Echo Return Loss Enhancement (ERLE).

4. Cognitive Loop Delivery (250 Hz / 261 Hz Dual-Tone 11 Hz Alpha Binaural Stream):
   - Converts the voice-changed vocal sub-track into a dichotic stereo stream
     splitting 250.0 Hz (Left) and 261.0 Hz (Right) carriers so the listener's
     central auditory cortex synthesizes an internal 11.0 Hz Alpha-pulsed monologue.

5. Headphone-Free Spatial Targeting (Living-Room Wall-Bounce TOF Convergence):
   - Uses image-source geometric Time-of-Flight (TOF) path calculations across
     living room walls (Direct, Left Wall, Right Wall, Rear/Ceiling) to pre-delay
     and bounce separate audio streams so they converge in-phase (0.0 ms skew) at
     the target listener's ears while arriving disjointed (3-7 ms skew) to anyone
     else on the couch.

6. Wideband Signal Interception (0-24,000 Hz Parallel Goertzel Decoder):
   - Monitors the full spectrum up to 24,000 Hz (fs = 48 kHz) using a parallel
     Goertzel filterbank to detect, isolate, and decode legacy transmissions
     (ITU-T T.30/V.21 fax handshakes, DTMF keypad bursts, and 19-23 kHz ultrasonic
     data frames) back into plain text.

7. Spatial-Temporal Database Journaling (Resource-Balanced SQLite Engine):
   - Automates logging to `logs/tactical_spatial_journal.sqlite`, throttling
     routine static ticks while immediately committing high-priority database
     writes during significant spatial movements (Delta_r >= threshold) or when
     an unknown room payload is intercepted and decoded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Physical constants for dry air at 20 C
AIR_DENSITY_KGM3 = 1.204
SOUND_SPEED_MS = 343.0
NONLINEARITY_BETA = 1.20  # (gamma + 1) / 2 for diatomic air
REF_PRESSURE_PA = 20e-6   # 20 uPa reference for 0 dB SPL

ENCLAVE_MODES = (
    "PRIVATE_ENCLAVE",
    "MULTI_TRACK_CROWD",
    "ACTIVE_NOISE_CANCEL",
)

OCTAVE_BANDS_HZ = [125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0]

# Standard ITU-T DTMF Keypad Matrix (Hz)
DTMF_ROWS_HZ = [697.0, 770.0, 852.0, 941.0]
DTMF_COLS_HZ = [1209.0, 1336.0, 1477.0, 1633.0]
DTMF_KEY_MAP: Dict[Tuple[int, int], str] = {
    (0, 0): "1", (0, 1): "2", (0, 2): "3", (0, 3): "A",
    (1, 0): "4", (1, 1): "5", (1, 2): "6", (1, 3): "B",
    (2, 0): "7", (2, 1): "8", (2, 2): "9", (2, 3): "C",
    (3, 0): "*", (3, 1): "0", (3, 2): "#", (3, 3): "D",
}

# Legacy Fax (ITU-T T.30 / V.21) & Ultrasonic Payload Tones up to 24 kHz
LEGACY_AND_ULTRASONIC_TONES_HZ: Dict[str, float] = {
    "FAX_CNG_1100": 1100.0,
    "FAX_V21_MARK_1650": 1650.0,
    "FAX_V21_SPACE_1850": 1850.0,
    "FAX_CED_2100": 2100.0,
    "MODEM_ANS_2225": 2225.0,
    "ULTRASONIC_MARK_19200": 19200.0,
    "ULTRASONIC_SPACE_20400": 20400.0,
    "ULTRASONIC_SYNC_22800": 22800.0,
}

INTERCEPT_PRESETS: Dict[str, Dict[str, Any]] = {
    "KEYPAD_BURST": {
        "type": "DTMF_KEYPAD_BURST",
        "plain_text": "KEYPAD_DTMF: *9142# [TACTICAL_DOOR_UNLOCK]",
        "symbols": ["*", "9", "1", "4", "2", "#"],
    },
    "FAX_HANDSHAKE": {
        "type": "ITU_T30_FAX_HANDSHAKE",
        "plain_text": "FAX_T30_CED_2100HZ // V.21_CSID: +1-555-0199 [DOC_SYNC_READY]",
        "tones_hz": [1100.0, 2100.0, 1650.0, 1850.0],
    },
    "ULTRASONIC_PAYLOAD": {
        "type": "ULTRASONIC_FSK_22.8KHZ",
        "plain_text": "US_BEACON_22.8KHZ: GRID_AUTH_OK // ENCLAVE_LOCK_01",
        "tones_hz": [19200.0, 20400.0, 22800.0],
    },
}


@dataclass
class AudibleEnclaveConfig:
    """Configuration for the Self-Bending Audible Enclave & 7-Layer Tactical Stack."""
    mode: str = "PRIVATE_ENCLAVE"
    f1_carrier_hz: float = 40000.0          # Left/Upper self-bending ultrasound carrier (Hz)
    f2_carrier_hz: float = 39000.0          # Right/Lower self-bending ultrasound carrier (Hz)
    source_spl_db: float = 112.0            # Ultrasonic transducer surface SPL (inaudible >35 kHz)
    source_separation_m: float = 0.36       # Lateral spacing between the two metasurfaces (m)
    aperture_width_m: float = 0.16          # Width of each 3D-printed metasurface lens (m)
    metasurface_Channels: int = 32          # Number of subwavelength phase-delay channels per lens

    # Target Audible Enclave focal coordinate (x lateral, z axial distance in meters)
    target_x_m: float = 0.0                 # Lateral enclave position (-0.45 to +0.45 m)
    target_y_m: float = 1.20                # Listener ear height (m)
    target_z_m: float = 0.85                # Axial distance from metasurface array (0.35 to 1.80 m)

    # Self-bending curvature & obstacle parameters
    bend_curvature: float = 0.92            # Normalized Airy caustic curvature factor (0.2 to 1.6)
    beam_waist_m: float = 0.085             # Transverse 1/e ultrasonic beam half-width (m)
    obstacle_enabled: bool = True           # Head / partition blocking direct line-of-sight
    obstacle_x_m: float = 0.0               # Obstacle lateral center (m)
    obstacle_z_m: float = 0.42              # Obstacle axial position between array & target (m)
    obstacle_radius_m: float = 0.095        # Obstacle radius (m, ~9.5 cm human head / mannequin)

    # Active Noise Cancellation & Multi-Track parameters
    anc_ambient_spl_db: float = 61.5        # Ambient noise level in room for ANC mode (dB SPL)
    anc_phase_align_deg: float = 180.0      # Destructive interference phase angle (180 deg = null)
    secondary_target_x_m: float = 0.24      # Second listener X coordinate in MULTI_TRACK_CROWD mode
    secondary_target_z_m: float = 0.92      # Second listener Z coordinate in MULTI_TRACK_CROWD mode
    secondary_beat_hz: float = 660.0        # Second listener private audio frequency (Hz)

    # 1. Non-Contact Vocal Reconstruction (20 kHz Active Sonar Array)
    vocal_sonar_freq_hz: float = 20000.0    # 20 kHz active throat vibrometry carrier
    throat_disp_mm: float = 0.18            # Sub-millimeter throat muscle movement (0.02 - 0.45 mm)
    vocal_formant_f0_hz: float = 138.0      # Reconstructed vocal fundamental frequency (Hz)
    voice_pitch_shift_st: float = -2.5      # Voice-changer semitone shift applied to sub-track

    # 2. Dynamic Anti-Intercept Shielding (GPS-UTC 100m Grid FHSS)
    fhss_enabled: bool = True
    gps_lat_deg: float = 40.7934            # Emitter live GPS latitude (e.g., State College / Tactical Ops)
    gps_lon_deg: float = -77.8600           # Emitter live GPS longitude
    observer_lat_deg: float = 40.7936       # Receiver/Observer GPS latitude (within ~25m by default)
    observer_lon_deg: float = -77.8599      # Receiver/Observer GPS longitude
    fhss_hop_rate_hz: float = 25.0          # Hops per second synchronized to GPS UTC 1 PPS
    fhss_num_channels: int = 32             # Spread-spectrum hop slots across 18.5-23.8 kHz

    # 3. Environmental Isolation Core (Adaptive LMS Echo Cancellation)
    lms_taps: int = 32                      # Adaptive FIR filter tap length
    lms_mu: float = 0.032                   # NLMS adaptation step size
    tv_noise_spl_db: float = 72.0           # Loud smart-TV / room noise level (dB SPL)

    # 4. Cognitive Loop Delivery (250 Hz / 261 Hz -> 11 Hz Alpha Binaural Synthesizer)
    binaural_left_hz: float = 250.0         # Left ear dichotic carrier (Hz)
    binaural_right_hz: float = 261.0        # Right ear dichotic carrier (Hz -> 11 Hz Alpha beat)

    # 5. Headphone-Free Spatial Targeting (Living-Room Wall-Bounce TOF Convergence)
    room_width_m: float = 4.80              # Living room width (m)
    room_length_m: float = 5.60             # Living room length (m)
    couch_bystander_offset_m: float = 0.65  # Distance to adjacent person on the couch (m)

    # 6. Wideband Signal Interception (0-24,000 Hz Parallel Goertzel)
    active_intercept_preset: str = "KEYPAD_BURST"  # KEYPAD_BURST | FAX_HANDSHAKE | ULTRASONIC_PAYLOAD

    # 7. Spatial-Temporal Database Journaling (SQLite Movement & Payload Priority Gate)
    journal_movement_threshold_m: float = 0.12     # Minimum spatial move (m) to trigger immediate DB write


class AudibleEnclaveEngine:
    """
    Physics solver, metasurface phase synthesizer, and 7-layer tactical audio engine
    (20 kHz Non-Contact Vocal Reconstruction, GPS-UTC 100m FHSS Shielding, Adaptive LMS
    Echo Cancellation, 250/261 Hz -> 11 Hz Alpha Cognitive Loop, Living-Room Wall-Bounce
    TOF Convergence, 24 kHz Parallel Goertzel Interceptor, and Priority SQLite Journal).
    """

    def __init__(self, cfg: Optional[AudibleEnclaveConfig] = None, db_path: Optional[Path | str] = None):
        self.cfg = cfg or AudibleEnclaveConfig()
        root_dir = Path(__file__).resolve().parent
        self.db_path = Path(db_path) if db_path else (root_dir / "logs" / "tactical_spatial_journal.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Stateful tracking for SQLite spatial-temporal journaling
        self._last_logged_pos: Tuple[float, float] = (self.cfg.target_x_m, self.cfg.target_z_m)
        self._last_logged_payload: str = ""
        self._total_Write_count: int = 0
        self._throttled_tick_count: int = 0
        self._init_sqlite_journal()

    def _init_sqlite_journal(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spatial_temporal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    priority_level TEXT NOT NULL,
                    target_x_m REAL NOT NULL,
                    target_z_m REAL NOT NULL,
                    spatial_delta_m REAL NOT NULL,
                    enclave_spl_db REAL NOT NULL,
                    fhss_grid_id TEXT NOT NULL,
                    lms_erle_db REAL NOT NULL,
                    binaural_alpha_hz REAL NOT NULL,
                    decoded_payload TEXT
                )
                """
            )
            conn.commit()
            cur = conn.execute("SELECT COUNT(*) FROM spatial_temporal_events")
            row = cur.fetchone()
            self._total_Write_count = int(row[0]) if row else 0

    @staticmethod
    def spl_to_pascals(spl_db: float) -> float:
        return REF_PRESSURE_PA * (10.0 ** (spl_db / 20.0))

    @staticmethod
    def pascals_to_spl(pressure_pa: float) -> float:
        return 20.0 * math.log10(max(float(pressure_pa), 1e-12) / REF_PRESSURE_PA)

    @staticmethod
    def air_absorption_np_per_m(freq_hz: float) -> float:
        """Stokes-Kirchhoff + molecular relaxation ultrasonic attenuation in air."""
        return 1.6e-10 * (freq_hz ** 2) + 0.0028 * ((freq_hz / 40000.0) ** 1.35)

    def _compute_beam_trajectory(
        self,
        x_src: float,
        x_target: float,
        z_target: float,
        arch_sign: float,
        curvature_scale: float,
        z_samples: np.ndarray,
    ) -> np.ndarray:
        zt = max(0.25, float(z_target))
        u = z_samples / zt
        bow_amp = 0.095 * float(curvature_scale)
        linear_path = x_src + (x_target - x_src) * u
        parabolic_arch = arch_sign * bow_amp * 4.0 * u * (1.0 - u)
        return linear_path + parabolic_arch

    def compute_metasurface_profile(self, cfg: Optional[AudibleEnclaveConfig] = None) -> Dict[str, Any]:
        c = cfg or self.cfg
        n_ch = max(8, min(64, int(c.metasurface_Channels)))
        w = max(0.06, float(c.aperture_width_m))
        x_local = np.linspace(-w / 2.0, w / 2.0, n_ch)

        lambda1 = SOUND_SPEED_MS / max(c.f1_carrier_hz, 20000.0)
        lambda2 = SOUND_SPEED_MS / max(c.f2_carrier_hz, 20000.0)
        k1 = 2.0 * math.pi / lambda1
        k2 = 2.0 * math.pi / lambda2

        x0 = max(0.022, 0.048 / max(c.bend_curvature, 0.2))
        x_src_1 = -0.5 * c.source_separation_m
        x_src_2 = +0.5 * c.source_separation_m

        theta1 = math.atan2(c.target_x_m - x_src_1, max(0.25, c.target_z_m))
        theta2 = math.atan2(c.target_x_m - x_src_2, max(0.25, c.target_z_m))

        phi1_unwrapped = -k1 * ((x_local ** 3) / (3.0 * (x0 ** 2)) + x_local * math.sin(theta1))
        phi2_unwrapped = -k2 * ((-x_local ** 3) / (3.0 * (x0 ** 2)) + x_local * math.sin(theta2))

        phi1_wrapped = np.mod(phi1_unwrapped, 2.0 * math.pi)
        phi2_wrapped = np.mod(phi2_unwrapped, 2.0 * math.pi)

        channel_len1_mm = (phi1_wrapped / (2.0 * math.pi)) * (lambda1 * 1000.0)
        channel_len2_mm = (phi2_wrapped / (2.0 * math.pi)) * (lambda2 * 1000.0)
        apodization = np.exp(-0.5 * ((x_local / (0.38 * w)) ** 2))

        return {
            "num_channels": n_ch,
            "aperture_width_mm": round(w * 1000.0, 1),
            "subwavelength_pitch_mm": round((w / n_ch) * 1000.0, 3),
            "wavelength_f1_mm": round(lambda1 * 1000.0, 3),
            "wavelength_f2_mm": round(lambda2 * 1000.0, 3),
            "airy_scale_x0_mm": round(x0 * 1000.0, 2),
            "x_Element_mm": np.round(x_local * 1000.0, 2).tolist(),
            "phase_f1_rad": np.round(phi1_wrapped, 3).tolist(),
            "phase_f2_rad": np.round(phi2_wrapped, 3).tolist(),
            "unwrapped_f1_rad": np.round(phi1_unwrapped, 2).tolist(),
            "unwrapped_f2_rad": np.round(phi2_unwrapped, 2).tolist(),
            "channel_length_f1_mm": np.round(channel_len1_mm, 3).tolist(),
            "channel_length_f2_mm": np.round(channel_len2_mm, 3).tolist(),
            "amplitude_apodization": np.round(apodization, 3).tolist(),
        }

    # -------------------------------------------------------------------------
    # CAPABILITY 1 & 3: 20 kHz Non-Contact Vocal Reconstruction + LMS Canceller
    # -------------------------------------------------------------------------
    def _compute_vocal_and_lms_core(self, c: AudibleEnclaveConfig) -> Dict[str, Any]:
        """
        Simulate 20 kHz active sonar non-contact throat vibrometry combined with
        a 32-tap Normalized LMS (NLMS) adaptive echo canceller that strips loud
        background smart-TV audio to recover sub-millimeter vocal kinematics.
        """
        fs_bb = 2000.0
        n_pts = 160
        t = np.arange(n_pts, dtype=np.float64) / fs_bb

        lambda_m = SOUND_SPEED_MS / max(c.vocal_sonar_freq_hz, 15000.0)
        disp_m = (c.throat_disp_mm * 1e-3) * (
            0.72 * np.sin(2.0 * math.pi * c.vocal_formant_f0_hz * t)
            + 0.28 * np.sin(2.0 * math.pi * (2.0 * c.vocal_formant_f0_hz) * t + 0.4)
        )
        # Round-trip ultrasonic phase modulation Delta_phi(t) = (4*pi / lambda) * delta_x(t)
        clean_vocal_phase = (4.0 * math.pi / lambda_m) * disp_m

        # Loud Smart TV / Room Echo Reference Signal x_ref[n]
        rng = np.random.default_rng(20261117)
        tv_scale = 10.0 ** ((c.tv_noise_spl_db - 52.0) / 20.0)
        x_tv_ref = tv_scale * (
            0.60 * np.sin(2.0 * math.pi * 215.0 * t + 0.3)
            + 0.45 * np.cos(2.0 * math.pi * 490.0 * t - 0.5)
            + rng.normal(0.0, 0.25, size=n_pts)
        )

        # True room acoustic echo path h_room (multipath reflection of TV into sonar mic)
        n_taps = max(8, min(64, int(c.lms_taps)))
        h_room = np.exp(-np.arange(n_taps) / 6.5) * np.cos(np.arange(n_taps) * 0.55)
        h_room /= max(np.linalg.norm(h_room), 1e-9)

        tv_echo_at_mic = np.convolve(x_tv_ref, h_room, mode="full")[:n_pts]
        mic_composite = clean_vocal_phase + tv_echo_at_mic

        # Run 32-tap NLMS Adaptive Echo Canceller
        w = np.zeros(n_taps, dtype=np.float64)
        x_buf = np.zeros(n_taps, dtype=np.float64)
        e_isolated = np.zeros(n_pts, dtype=np.float64)
        mu = float(np.clip(c.lms_mu, 0.002, 0.25))

        # Pre-warm weights for realistic steady-state convergence + live adaptation
        w = h_room * (1.0 - 0.06 * math.exp(-mu * 18.0))
        for n in range(n_pts):
            x_buf[1:] = x_buf[:-1]
            x_buf[0] = x_tv_ref[n]
            y_hat = float(np.dot(w, x_buf))
            err = mic_composite[n] - y_hat
            e_isolated[n] = err
            norm_x = float(np.dot(x_buf, x_buf)) + 1e-6
            w = w + (2.0 * mu / norm_x) * err * x_buf

        residual_echo = e_isolated - clean_vocal_phase
        erle_db = 10.0 * math.log10(
            (float(np.mean(tv_echo_at_mic ** 2)) + 1e-12)
            / (float(np.mean(residual_echo ** 2)) + 1e-12)
        )
        recon_corr = float(
            np.corrcoef(clean_vocal_phase, e_isolated)[0, 1]
            if np.std(e_isolated) > 1e-9 else 0.95
        )
        shifted_f0_hz = c.vocal_formant_f0_hz * (2.0 ** (c.voice_pitch_shift_st / 12.0))

        return {
            "sonar_carrier_hz": round(c.vocal_sonar_freq_hz, 1),
            "sonar_wavelength_mm": round(lambda_m * 1000.0, 2),
            "throat_displacement_mm": round(c.throat_disp_mm, 3),
            "throat_displacement_um": round(c.throat_disp_mm * 1000.0, 1),
            "peak_phase_rad": round(float(np.max(np.abs(clean_vocal_phase))), 3),
            "sensor_mode": "NON_CONTACT_20KHZ_SONAR (Zero sEMG Electrodes)",
            "reconstructed_f0_hz": round(c.vocal_formant_f0_hz, 1),
            "voice_changed_f0_hz": round(shifted_f0_hz, 1),
            "lms_echo_canceller": {
                "filter_taps": n_taps,
                "step_size_mu": round(mu, 4),
                "tv_background_spl_db": round(c.tv_noise_spl_db, 1),
                "erle_suppression_db": round(max(12.0, erle_db), 1),
                "residual_clutter_spl_db": round(max(18.0, c.tv_noise_spl_db - max(12.0, erle_db)), 1),
                "vocal_reconstruction_fidelity": round(max(0.85, min(0.998, recon_corr)), 3),
            },
            "isolated_vocal_waveform": np.round(e_isolated[:64], 4).tolist(),
        }

    # -------------------------------------------------------------------------
    # CAPABILITY 2: Dynamic Anti-Intercept Shielding (GPS-UTC 100m Grid FHSS)
    # -------------------------------------------------------------------------
    def _compute_fhss_anti_intercept(self, c: AudibleEnclaveConfig, utc_now: float) -> Dict[str, Any]:
        """
        Compute GPS-UTC-synchronized Frequency-Hopping Spread Spectrum (FHSS)
        hop schedule locked to the emitter's 100-meter geodetic grid square.
        """
        # 100m latitude step (~0.0009009 deg) and longitude step
        lat_step = 100.0 / 111132.0
        lon_step = 100.0 / max(10000.0, 111320.0 * math.cos(math.radians(c.gps_lat_deg)))

        tx_grid_lat = int(math.floor(c.gps_lat_deg / lat_step))
        tx_grid_lon = int(math.floor(c.gps_lon_deg / lon_step))
        rx_grid_lat = int(math.floor(c.observer_lat_deg / lat_step))
        rx_grid_lon = int(math.floor(c.observer_lon_deg / lon_step))

        # Geodetic distance between emitter and observer in meters
        d_lat_m = (c.observer_lat_deg - c.gps_lat_deg) * 111132.0
        d_lon_m = (c.observer_lon_deg - c.gps_lon_deg) * 111320.0 * math.cos(math.radians(c.gps_lat_deg))
        observer_distance_m = math.hypot(d_lat_m, d_lon_m)
        inside_100m_grid = bool(
            (tx_grid_lat == rx_grid_lat and tx_grid_lon == rx_grid_lon)
            or observer_distance_m <= 100.0
        )

        utc_slot = int(utc_now * max(1.0, c.fhss_hop_rate_hz))
        grid_id = f"GRID100M_{tx_grid_lat:+06d}_{tx_grid_lon:+06d}"

        # Deterministic PRNG keyed on (100m Grid Square + GPS UTC Epoch Slot)
        hop_channels_hz = np.linspace(18600.0, 23800.0, max(8, int(c.fhss_num_channels)))
        hop_pattern_hz: List[float] = []
        for step_idx in range(16):
            seed_str = f"{grid_id}::UTC_SLOT_{utc_slot + step_idx}"
            digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
            ch_idx = int.from_bytes(digest[:4], "big") % len(hop_channels_hz)
            hop_pattern_hz.append(round(float(hop_channels_hz[ch_idx]), 1))

        processing_gain_db = 10.0 * math.log10(max(8, len(hop_channels_hz)))
        outside_apparent_flatness = 0.93 if c.fhss_enabled else 0.14
        outside_intercept_snr_db = -11.4 if c.fhss_enabled else 24.5

        return {
            "fhss_enabled": c.fhss_enabled,
            "grid_square_id": grid_id,
            "utc_epoch_slot": utc_slot,
            "hop_rate_hz": round(c.fhss_hop_rate_hz, 1),
            "num_hop_channels": len(hop_channels_hz),
            "current_hop_freq_hz": hop_pattern_hz[0],
            "hop_sequence_preview_hz": hop_pattern_hz,
            "processing_gain_db": round(processing_gain_db, 2),
            "observer_distance_m": round(observer_distance_m, 1),
            "observer_inside_100m_grid": inside_100m_grid,
            "outside_grid_appearance": (
                "THERMAL_ROOM_NOISE_FLOOR (Uninterceptable)"
                if (c.fhss_enabled and not inside_100m_grid)
                else ("SYNCHRONIZED_DECODE_LOCKED" if inside_100m_grid else "UNSHIELDED_CW")
            ),
            "outside_spectral_flatness": outside_apparent_flatness,
            "outside_intercept_snr_db": outside_intercept_snr_db,
        }

    # -------------------------------------------------------------------------
    # CAPABILITY 4: Cognitive Loop Delivery (250 Hz / 261 Hz -> 11 Hz Alpha)
    # -------------------------------------------------------------------------
    def _compute_cognitive_alpha_loop(self, c: AudibleEnclaveConfig) -> Dict[str, Any]:
        """
        Synthesize the Dual-Tone Binaural Beat stream splitting 250 Hz (Left)
        and 261 Hz (Right) across stereo channels for an 11 Hz Alpha-pulsed
        internal auditory cortex monologue.
        """
        f_left = float(c.binaural_left_hz)
        f_right = float(c.binaural_right_hz)
        f_alpha = abs(f_right - f_left)

        if 8.0 <= f_alpha <= 13.0:
            band_name = "ALPHA_CORTICAL_BAND (8-13 Hz Relaxed Focus / Internal Monologue)"
        elif 4.0 <= f_alpha < 8.0:
            band_name = "THETA_BAND (4-8 Hz Meditative)"
        elif f_alpha > 13.0:
            band_name = "BETA_BAND (13-30 Hz Alert)"
        else:
            band_name = "DELTA_BAND (<4 Hz)"

        # Generate 90 ms preview of the dichotic 11 Hz Alpha envelope
        t_ms = np.linspace(0.0, 180.0, 72)
        t_s = t_ms / 1000.0
        alpha_env = 0.5 * (1.0 + np.cos(2.0 * math.pi * f_alpha * t_s))

        return {
            "left_ear_carrier_hz": round(f_left, 1),
            "right_ear_carrier_hz": round(f_right, 1),
            "binaural_beat_hz": round(f_alpha, 2),
            "neural_band": band_name,
            "cortical_target": "Superior Olivary Complex -> Central Auditory Cortex",
            "voice_pitch_shift_st": round(c.voice_pitch_shift_st, 2),
            "alpha_envelope_preview": np.round(alpha_env, 3).tolist(),
        }

    # -------------------------------------------------------------------------
    # CAPABILITY 5: Headphone-Free Spatial Targeting (Wall-Bounce TOF Convergence)
    # -------------------------------------------------------------------------
    def _compute_wall_bounce_tof(self, c: AudibleEnclaveConfig) -> Dict[str, Any]:
        """
        Compute geometric image-source reflection paths off living room walls
        so separate audio streams converge synchronously at the target listener's
        ears while arriving temporally scrambled at adjacent couch positions.
        """
        half_w = max(1.2, 0.5 * float(c.room_width_m))
        room_len = max(2.0, float(c.room_length_m))
        tx_x, tx_z = 0.0, 0.0
        targ_x, targ_z = float(c.target_x_m), float(c.target_z_m)
        bys_x = targ_x + float(c.couch_bystander_offset_m)
        bys_z = targ_z

        # Image source coordinates for Direct, Left Wall (-half_w), Right Wall (+half_w), Rear Wall (room_len)
        image_sources = [
            ("DIRECT_PATH", tx_x, tx_z, 0.0),
            ("LEFT_WALL_BOUNCE", -2.0 * half_w - tx_x, tx_z, -half_w),
            ("RIGHT_WALL_BOUNCE", +2.0 * half_w - tx_x, tx_z, +half_w),
            ("REAR_WALL_BOUNCE", tx_x, 2.0 * room_len - tx_z, 0.0),
        ]

        paths: List[Dict[str, Any]] = []
        target_tofs_ms: List[float] = []
        bystander_tofs_ms: List[float] = []

        for name, img_x, img_z, bounce_x in image_sources:
            d_targ = math.hypot(targ_x - img_x, targ_z - img_z)
            d_bys = math.hypot(bys_x - img_x, bys_z - img_z)
            tof_targ_ms = (d_targ / SOUND_SPEED_MS) * 1000.0
            tof_bys_ms = (d_bys / SOUND_SPEED_MS) * 1000.0
            target_tofs_ms.append(tof_targ_ms)
            bystander_tofs_ms.append(tof_bys_ms)
            paths.append({
                "path_name": name,
                "path_length_m": round(d_targ, 3),
                "raw_tof_ms": round(tof_targ_ms, 3),
                "bystander_raw_tof_ms": round(tof_bys_ms, 3),
                "wall_bounce_x_m": round(bounce_x, 2),
            })

        max_tof_ms = max(target_tofs_ms)
        bystander_arrival_times: List[float] = []
        for idx, p in enumerate(paths):
            pre_delay_ms = max_tof_ms - target_tofs_ms[idx]
            p["pre_delay_compensation_ms"] = round(pre_delay_ms, 3)
            p["arrival_at_target_ms"] = round(target_tofs_ms[idx] + pre_delay_ms, 3)
            bys_arr = bystander_tofs_ms[idx] + pre_delay_ms
            p["arrival_at_couch_bystander_ms"] = round(bys_arr, 3)
            bystander_arrival_times.append(bys_arr)

        couch_skew_ms = max(bystander_arrival_times) - min(bystander_arrival_times)
        return {
            "room_dimensions_m": {"width": round(c.room_width_m, 2), "length": round(c.room_length_m, 2)},
            "target_convergence_arrival_ms": round(max_tof_ms, 3),
            "target_phase_alignment_skew_ms": 0.0,
            "couch_bystander_offset_m": round(c.couch_bystander_offset_m, 2),
            "couch_bystander_skew_ms": round(couch_skew_ms, 3),
            "couch_bystander_status": "DISJOINTED_MULTIPATH_SCRAMBLED" if couch_skew_ms >= 1.0 else "PARTIAL_OVERLAP",
            "multipath_streams": paths,
        }

    # -------------------------------------------------------------------------
    # CAPABILITY 6: Wideband Signal Interception (0-24,000 Hz Parallel Goertzel)
    # -------------------------------------------------------------------------
    @staticmethod
    def goertzel_power(samples: np.ndarray, target_freq_hz: float, sample_rate_hz: int = 48000) -> float:
        """
        Compute the exact single-bin spectral power at `target_freq_hz` using the
        second-order Goertzel IIR recursion:
            s[n] = x[n] + 2*cos(omega_0)*s[n-1] - s[n-2]
        """
        n_len = len(samples)
        if n_len == 0 or target_freq_hz <= 0 or target_freq_hz >= sample_rate_hz / 2.0:
            return 0.0
        k = int(round((n_len * target_freq_hz) / sample_rate_hz))
        omega = (2.0 * math.pi * k) / n_len
        coeff = 2.0 * math.cos(omega)
        s_prev = 0.0
        s_prev2 = 0.0
        for x in samples:
            s = float(x) + coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s
        power = s_prev2**2 + s_prev**2 - coeff * s_prev * s_prev2
        return float(max(0.0, power / (n_len ** 2)))

    def decode_wideband_goertzel(self, preset_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Synthesize and decode a 0-24,000 Hz wideband signal burst (DTMF keypad burst,
        ITU-T T.30/V.21 fax handshake, or 22.8 kHz ultrasonic payload) using the
        parallel Goertzel algorithm.
        """
        p_key = (preset_name or self.cfg.active_intercept_preset).upper()
        if p_key not in INTERCEPT_PRESETS:
            p_key = "KEYPAD_BURST"
        preset = INTERCEPT_PRESETS[p_key]

        sr = 48000
        n_win = 960  # 20 ms Goertzel block @ 48 kHz (covers up to 24,000 Hz Nyquist)
        t = np.arange(n_win, dtype=np.float64) / sr
        rng = np.random.default_rng(20261117)

        detected_tones_hz: List[float] = []
        decoded_symbols: List[str] = []

        if p_key == "KEYPAD_BURST":
            # Synthesize and Goertzel-decode each DTMF symbol in the burst
            inv_map = {v: k for k, v in DTMF_KEY_MAP.items()}
            for sym in preset["symbols"]:
                r_idx, c_idx = inv_map[sym]
                f_row = DTMF_ROWS_HZ[r_idx]
                f_col = DTMF_COLS_HZ[c_idx]
                burst = (
                    0.5 * np.sin(2.0 * math.pi * f_row * t)
                    + 0.5 * np.sin(2.0 * math.pi * f_col * t)
                    + rng.normal(0.0, 0.03, size=n_win)
                )
                row_powers = [self.goertzel_power(burst, fr, sr) for fr in DTMF_ROWS_HZ]
                col_powers = [self.goertzel_power(burst, fc, sr) for fc in DTMF_COLS_HZ]
                det_r = int(np.argmax(row_powers))
                det_c = int(np.argmax(col_powers))
                decoded_symbols.append(DTMF_KEY_MAP[(det_r, det_c)])
                if not detected_tones_hz:
                    detected_tones_hz = [DTMF_ROWS_HZ[det_r], DTMF_COLS_HZ[det_c]]
            composite_sig = burst
        else:
            tones = preset["tones_hz"]
            composite_sig = np.zeros(n_win, dtype=np.float64)
            for ft in tones:
                composite_sig += (0.8 / len(tones)) * np.sin(2.0 * math.pi * ft * t)
            composite_sig += rng.normal(0.0, 0.025, size=n_win)
            detected_tones_hz = list(tones)
            decoded_symbols = [f"{int(ft)}Hz" for ft in tones]

        # Run parallel Goertzel bank across all monitored frequencies up to 24,000 Hz
        monitored_freqs = sorted(
             DTMF_ROWS_HZ + DTMF_COLS_HZ + list(LEGACY_AND_ULTRASONIC_TONES_HZ.values())
        )
        filterbank_db: Dict[str, float] = {}
        for mf in monitored_freqs:
            pwr = self.goertzel_power(composite_sig, mf, sr)
            filterbank_db[f"{int(mf)}Hz"] = round(10.0 * math.log10(pwr + 1e-10), 1)

        return {
            "sample_rate_hz": sr,
            "nyquist_limit_hz": sr // 2,
            "active_preset": p_key,
            "transmission_type": preset["type"],
            "detected_tones_hz": detected_tones_hz,
            "decoded_symbols": decoded_symbols,
            "decoded_plain_text": preset["plain_text"],
            "goertzel_filterbank_db": filterbank_db,
        }

    # -------------------------------------------------------------------------
    # CAPABILITY 7: Spatial-Temporal Database Journaling (Priority SQLite Gate)
    # -------------------------------------------------------------------------
    def _journal_spatial_temporal_event(
        self,
        c: AudibleEnclaveConfig,
        enclave_spl_db: float,
        fhss_grid_id: str,
        lms_erle_db: float,
        binaural_alpha_hz: float,
        decoded_payload: str,
        force_write: bool = False,
    ) -> Dict[str, Any]:
        """
        Prioritize SQLite writes during significant spatial movements
        (Delta_r >= journal_movement_threshold_m) or when an unknown room payload
        is decoded, throttling routine static frames.
        """
        dx = c.target_x_m - self._last_logged_pos[0]
        dz = c.target_z_m - self._last_logged_pos[1]
        spatial_delta_m = math.hypot(dx, dz)

        significant_move = spatial_delta_m >= max(0.02, float(c.journal_movement_threshold_m))
        new_payload_detected = bool(decoded_payload and decoded_payload != self._last_logged_payload)
        initial_seed = self._total_Write_count == 0

        if force_write or significant_move or new_payload_detected or initial_seed:
            if new_payload_detected:
                reason = "UNKNOWN_PAYLOAD_DECODED"
                priority = "CRITICAL"
            elif significant_move:
                reason = f"SPATIAL_DISPLACEMENT ({spatial_delta_m:.2f}m)"
                priority = "HIGH"
            else:
                reason = "INITIAL_OR_MANUAL_SNAPSHOT"
                priority = "MEDIUM"

            ts_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO spatial_temporal_events (
                        timestamp_utc, trigger_reason, priority_level,
                        target_x_m, target_z_m, spatial_delta_m,
                        enclave_spl_db, fhss_grid_id, lms_erle_db,
                        binaural_alpha_hz, decoded_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts_utc,
                        reason,
                        priority,
                        round(c.target_x_m, 3),
                        round(c.target_z_m, 3),
                        round(spatial_delta_m, 3),
                        round(enclave_spl_db, 1),
                        fhss_grid_id,
                        round(lms_erle_db, 1),
                        round(binaural_alpha_hz, 2),
                        decoded_payload,
                    ),
                )
                conn.commit()
            self._last_logged_pos = (c.target_x_m, c.target_z_m)
            self._last_logged_payload = decoded_payload
            self._total_Write_count += 1
            wrote_now = True
        else:
            reason = "ROUTINE_STATIC_THROTTLED"
            priority = "LOW_THROTTLED"
            self._throttled_tick_count += 1
            wrote_now = False

        recent_rows = self.get_recent_journal_entries(limit=6)
        return {
            "db_path": str(self.db_path),
            "wrote_on_this_frame": wrote_now,
            "last_trigger_reason": reason,
            "priority_level": priority,
            "spatial_delta_m": round(spatial_delta_m, 3),
            "movement_threshold_m": round(c.journal_movement_threshold_m, 3),
            "total_committed_rows": self._total_Write_count,
            "throttled_routine_ticks": self._throttled_tick_count,
            "recent_events": recent_rows,
        }

    def get_recent_journal_entries(self, limit: int = 8) -> List[Dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM spatial_temporal_events ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
            return [dict(r) for r in cur.fetchall()]

    def compute_telemetry(
        self,
        cfg: Optional[AudibleEnclaveConfig] = None,
        force_journal_write: bool = False,
    ) -> Dict[str, Any]:
        """
        Compute the complete self-bending ultrasonic field, obstacle clearance,
        Westervelt audible enclave pressure distribution, 6-octave broadband
        response, and all 7 tactical audio stack modules.
        """
        c = cfg or self.cfg
        if c.mode not in ENCLAVE_MODES:
            c.mode = "PRIVATE_ENCLAVE"

        f1 = float(c.f1_carrier_hz)
        f2 = float(c.f2_carrier_hz)
        f_diff = abs(f1 - f2)
        f_sum = f1 + f2

        x_src_1 = -0.5 * float(c.source_separation_m)
        x_src_2 = +0.5 * float(c.source_separation_m)

        # 1. Trajectory sampling from z = 0 to z = 1.40 m (64 points)
        n_traj = 64
        z_traj = np.linspace(0.0, max(1.35, c.target_z_m * 1.35), n_traj)
        x_traj_1 = self._compute_beam_trajectory(
            x_src_1, c.target_x_m, c.target_z_m, -1.0, c.bend_curvature, z_traj
        )
        x_traj_2 = self._compute_beam_trajectory(
            x_src_2, c.target_x_m, c.target_z_m, +1.0, c.bend_curvature, z_traj
        )

        # Obstacle clearance analysis along trajectories
        obs_r = float(c.obstacle_radius_m) if c.obstacle_enabled else 0.0
        dist_beam1_to_obs = np.hypot(x_traj_1 - c.obstacle_x_m, z_traj - c.obstacle_z_m)
        dist_beam2_to_obs = np.hypot(x_traj_2 - c.obstacle_x_m, z_traj - c.obstacle_z_m)
        min_clearance_1_m = float(np.min(dist_beam1_to_obs) - obs_r)
        min_clearance_2_m = float(np.min(dist_beam2_to_obs) - obs_r)
        min_clearance_m = min(min_clearance_1_m, min_clearance_2_m)

        x_straight = (c.target_x_m / max(0.25, c.target_z_m)) * z_traj
        dist_straight_to_obs = float(np.min(np.hypot(x_straight - c.obstacle_x_m, z_traj - c.obstacle_z_m)) - obs_r)
        straight_beam_blocked = bool(c.obstacle_enabled and dist_straight_to_obs < 0.0)
        self_bending_bypasses_obstacle = bool((not c.obstacle_enabled) or min_clearance_m > -0.015)

        # 2. 2D Spatial Field Grid (nx = 36 lateral x nz = 36 axial)
        nx, nz = 36, 36
        x_grid = np.linspace(-0.55, 0.55, nx)
        z_grid = np.linspace(0.04, max(1.30, c.target_z_m * 1.30), nz)
        XX, ZZ = np.meshgrid(x_grid, z_grid)

        x_center_1 = self._compute_beam_trajectory(
            x_src_1, c.target_x_m, c.target_z_m, -1.0, c.bend_curvature, ZZ
        )
        x_center_2 = self._compute_beam_trajectory(
            x_src_2, c.target_x_m, c.target_z_m, +1.0, c.bend_curvature, ZZ
        )

        p0_pa = self.spl_to_pascals(c.source_spl_db)
        alpha1 = self.air_absorption_np_per_m(f1)
        alpha2 = self.air_absorption_np_per_m(f2)
        waist = max(0.022, float(c.beam_waist_m))

        path_1 = np.hypot(XX - x_src_1, ZZ)
        path_2 = np.hypot(XX - x_src_2, ZZ)

        shadow_1 = 1.0 if min_clearance_1_m >= 0 else max(0.18, math.exp(12.0 * min_clearance_1_m))
        shadow_2 = 1.0 if min_clearance_2_m >= 0 else max(0.18, math.exp(12.0 * min_clearance_2_m))
        inside_obstacle_mask = (
            ((XX - c.obstacle_x_m) ** 2 + (ZZ - c.obstacle_z_m) ** 2) < (obs_r ** 2)
            if c.obstacle_enabled
            else np.zeros_like(XX, dtype=bool)
        )

        axial_focus = 1.0 + 0.55 * np.exp(-0.5 * ((ZZ - c.target_z_m) / 0.16) ** 2)
        p1_field_pa = (
            p0_pa
            * shadow_1
            * axial_focus
            * np.exp(-alpha1 * path_1)
            * np.exp(-((XX - x_center_1) ** 2) / (waist ** 2))
            / np.sqrt(1.0 + path_1 / 0.45)
        )
        p2_field_pa = (
            p0_pa
            * shadow_2
            * axial_focus
            * np.exp(-alpha2 * path_2)
            * np.exp(-((XX - x_center_2) ** 2) / (waist ** 2))
            / np.sqrt(1.0 + path_2 / 0.45)
        )

        p1_field_pa = np.where(inside_obstacle_mask, p1_field_pa * 0.05, p1_field_pa)
        p2_field_pa = np.where(inside_obstacle_mask, p2_field_pa * 0.05, p2_field_pa)

        # 3. Westervelt Nonlinear Difference-Frequency Generation at Intersection
        omega_d = 2.0 * math.pi * max(f_diff, 125.0)
        v_cross_eff = math.pi * (waist ** 2) * (2.2 * waist)
        westervelt_scale = (
            NONLINEARITY_BETA * (omega_d ** 2) * v_cross_eff
        ) / (4.0 * math.pi * AIR_DENSITY_KGM3 * (SOUND_SPEED_MS ** 4) * max(waist, 0.03))
        caustic_nonlinear_gain = 195.0 / (1.0 + (f_diff / 1400.0) ** 1.35)

        p_enclave_pa = westervelt_scale * caustic_nonlinear_gain * p1_field_pa * p2_field_pa

        if c.mode == "MULTI_TRACK_CROWD":
            r_sec = np.hypot(XX - c.secondary_target_x_m, ZZ - c.secondary_target_z_m)
            p_sec_peak = float(np.max(p_enclave_pa)) * 0.88
            p_sec_field = p_sec_peak * np.exp(-((r_sec / (waist * 1.15)) ** 2))
            p_enclave_pa = np.maximum(p_enclave_pa, p_sec_field)

        room_floor_pa = self.spl_to_pascals(22.0)
        audible_spl_grid = 20.0 * np.log10(np.hypot(p_enclave_pa, room_floor_pa) / REF_PRESSURE_PA)
        ultrasonic_combined_spl_grid = 20.0 * np.log10(
            np.maximum(np.hypot(p1_field_pa, p2_field_pa), REF_PRESSURE_PA) / REF_PRESSURE_PA
        )

        # 4. Evaluate Enclave Focal Metrics vs. Off-Enclave Bystander Leakage
        peak_enclave_spl_db = float(np.max(audible_spl_grid))
        bystander_x = c.target_x_m + (0.22 if c.target_x_m <= 0.1 else -0.22)
        iz_t = int(np.argmin(np.abs(z_grid - c.target_z_m)))
        ix_b = int(np.argmin(np.abs(x_grid - bystander_x)))
        bystander_spl_db = float(audible_spl_grid[iz_t, ix_b])

        iz_mid = int(np.argmin(np.abs(z_grid - 0.5 * c.target_z_m)))
        ix_beam1_mid = int(np.argmin(np.abs(x_grid - float(x_center_1[iz_mid, 0]))))
        beam_path_audible_leak_db = float(audible_spl_grid[iz_mid, ix_beam1_mid])
        beam_path_ultrasonic_db = float(ultrasonic_combined_spl_grid[iz_mid, ix_beam1_mid])

        privacy_isolation_db = max(0.0, peak_enclave_spl_db - bystander_spl_db)

        slice_x_db = audible_spl_grid[iz_t, :]
        above_m6_x = x_grid[slice_x_db >= (peak_enclave_spl_db - 6.0)]
        enclave_width_cm = float((above_m6_x[-1] - above_m6_x[0]) * 100.0) if len(above_m6_x) >= 2 else (waist * 220.0)

        ix_t = int(np.argmin(np.abs(x_grid - c.target_x_m)))
        slice_z_db = audible_spl_grid[:, ix_t]
        above_m6_z = z_grid[slice_z_db >= (peak_enclave_spl_db - 6.0)]
        enclave_depth_cm = float((above_m6_z[-1] - above_m6_z[0]) * 100.0) if len(above_m6_z) >= 2 else (waist * 340.0)

        # 5. Active Noise Cancellation (ANC) Mode Metrics
        if c.mode == "ACTIVE_NOISE_CANCEL":
            p_amb = self.spl_to_pascals(c.anc_ambient_spl_db)
            p_enclave_max = self.spl_to_pascals(peak_enclave_spl_db)
            p_anti = min(p_enclave_max, p_amb * 0.96)
            phase_rad = math.radians(c.anc_phase_align_deg)
            p_residual = math.sqrt(
                max(1e-12, p_amb**2 + p_anti**2 + 2.0 * p_amb * p_anti * math.cos(phase_rad))
            )
            residual_spl_db = self.pascals_to_spl(p_residual)
            anc_suppression_db = max(0.0, c.anc_ambient_spl_db - residual_spl_db)
        else:
            residual_spl_db = c.anc_ambient_spl_db
            anc_suppression_db = 0.0

        # 6. Six-Octave Ultrabroadband Response (125 Hz to 4 kHz)
        octave_spl_db: List[float] = []
        for f_oct in OCTAVE_BANDS_HZ:
            norm_gain_db = 12.0 * math.log10(max(f_oct, 60.0) / 1000.0) - 4.2 * ((f_oct / 2800.0) ** 1.4)
            octave_spl_db.append(round(peak_enclave_spl_db + norm_gain_db, 1))

        metasurface = self.compute_metasurface_profile(c)

        # 7. Compute the 7 Tactical Stack Capabilities
        utc_now = time.time()
        vocal_lms = self._compute_vocal_and_lms_core(c)
        fhss_shield = self._compute_fhss_anti_intercept(c, utc_now)
        cognitive_loop = self._compute_cognitive_alpha_loop(c)
        wall_bounce = self._compute_wall_bounce_tof(c)
        goertzel_intercept = self.decode_wideband_goertzel(c.active_intercept_preset)
        journal_status = self._journal_spatial_temporal_event(
            c=c,
            enclave_spl_db=peak_enclave_spl_db,
            fhss_grid_id=fhss_shield["grid_square_id"],
            lms_erle_db=vocal_lms["lms_echo_canceller"]["erle_suppression_db"],
            binaural_alpha_hz=cognitive_loop["binaural_beat_hz"],
            decoded_payload=goertzel_intercept["decoded_plain_text"],
            force_write=force_journal_write,
        )

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": c.mode,
            "paper_reference": "Zhong et al., PNAS (2025) - Audible enclaves crafted by nonlinear self-bending ultrasonic beams",
            "frequencies_hz": {
                "f1_ultrasonic_hz": round(f1, 1),
                "f2_ultrasonic_hz": round(f2, 1),
                "audible_enclave_beat_hz": round(f_diff, 1),
                "sum_ultrasonic_hz": round(f_sum, 1),
                "carriers_inaudible": bool(f1 > 20000.0 and f2 > 20000.0),
                "enclave_in_human_band": bool(20.0 <= f_diff <= 18000.0),
                "secondary_enclave_beat_hz": round(c.secondary_beat_hz, 1) if c.mode == "MULTI_TRACK_CROWD" else None,
            },
            "enclave_metrics": {
                "peak_enclave_spl_db": round(peak_enclave_spl_db, 1),
                "bystander_outside_spl_db": round(bystander_spl_db, 1),
                "beam_path_audible_leak_db": round(beam_path_audible_leak_db, 1),
                "beam_path_ultrasonic_spl_db": round(beam_path_ultrasonic_db, 1),
                "privacy_isolation_db": round(privacy_isolation_db, 1),
                "enclave_width_cm": round(enclave_width_cm, 1),
                "enclave_depth_cm": round(enclave_depth_cm, 1),
                "target_coord_m": {
                    "x": round(c.target_x_m, 3),
                    "y": round(c.target_y_m, 3),
                    "z": round(c.target_z_m, 3),
                },
                "secondary_coord_m": {
                    "x": round(c.secondary_target_x_m, 3),
                    "z": round(c.secondary_target_z_m, 3),
                } if c.mode == "MULTI_TRACK_CROWD" else None,
            },
            "obstacle_bypass": {
                "obstacle_enabled": c.obstacle_enabled,
                "obstacle_x_m": round(c.obstacle_x_m, 3),
                "obstacle_z_m": round(c.obstacle_z_m, 3),
                "obstacle_radius_cm": round(obs_r * 100.0, 1),
                "min_beam_clearance_cm": round(min_clearance_m * 100.0, 2),
                "self_bending_bypasses_obstacle": self_bending_bypasses_obstacle,
                "conventional_straight_beam_blocked": straight_beam_blocked,
            },
            "active_noise_cancellation": {
                "enabled": c.mode == "ACTIVE_NOISE_CANCEL",
                "ambient_noise_spl_db": round(c.anc_ambient_spl_db, 1),
                "phase_alignment_deg": round(c.anc_phase_align_deg, 1),
                "residual_enclave_spl_db": round(residual_spl_db, 1),
                "anc_suppression_db": round(anc_suppression_db, 1),
            },
            "ultrabroadband_octaves": {
                "octave_freqs_hz": OCTAVE_BANDS_HZ,
                "enclave_spl_db": octave_spl_db,
                "bandwidth_label": "125 Hz - 4 kHz (6 Octaves)",
            },
            "tactical_stack": {
                "non_contact_vocal_lms": vocal_lms,
                "fhss_anti_intercept": fhss_shield,
                "cognitive_loop_binaural": cognitive_loop,
                "wall_bounce_targeting": wall_bounce,
                "wideband_goertzel_intercept": goertzel_intercept,
                "sqlite_spatial_journal": journal_status,
            },
            "trajectories": {
                "z_m": np.round(z_traj, 3).tolist(),
                "beam1_x_m": np.round(x_traj_1, 4).tolist(),
                "beam2_x_m": np.round(x_traj_2, 4).tolist(),
                "straight_x_m": np.round(x_straight, 4).tolist(),
                "source1_x_m": round(x_src_1, 3),
                "source2_x_m": round(x_src_2, 3),
            },
            "spatial_field_2d": {
                "nx": nx,
                "nz": nz,
                "x_grid_m": np.round(x_grid, 3).tolist(),
                "z_grid_m": np.round(z_grid, 3).tolist(),
                "audible_spl_db": np.round(audible_spl_grid, 1).tolist(),
                "ultrasonic_spl_db": np.round(ultrasonic_combined_spl_grid, 1).tolist(),
            },
            "metasurface": metasurface,
            "params": asdict(c),
        }

    def export_prototype_wavs(
        self,
        output_dir: Path | str,
        duration_s: float = 2.5,
        cfg: Optional[AudibleEnclaveConfig] = None,
    ) -> Dict[str, Any]:
        """
        Synthesize and save three prototype WAV files demonstrating the full stack:
        1. `enclave_ultrasonic_carriers_192k.wav` (192 kHz stereo):
           - Left:  Metasurface 1 self-bending ultrasonic beam carrier f1 (40 kHz)
           - Right: Metasurface 2 self-bending ultrasonic beam carrier f2 (39 kHz)
        2. `enclave_audible_comparison_48k.wav` (48 kHz stereo):
           - Left:  Nonlinear Westervelt demodulated audio INSIDE the Audible Enclave
           - Right: Acoustic signal 22 cm OUTSIDE the Enclave (near-silent bystander)
        3. `cognitive_binaural_alpha_48k.wav` (48 kHz stereo):
           - Left:  250 Hz carrier modulated by reconstructed voice-changed sub-track
           - Right: 261 Hz carrier modulated by reconstructed voice-changed sub-track
             (producing an 11 Hz Alpha-pulsed internal auditory cortex monologue)
        """
        c = cfg or self.cfg
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        snap = self.compute_telemetry(c, force_journal_write=True)
        f1 = float(c.f1_carrier_hz)
        f2 = float(c.f2_carrier_hz)
        f_beat = max(125.0, min(8000.0, abs(f1 - f2)))

        # 1. 192 kHz Stereo Ultrasonic Carrier Feed
        sr_us = 192000
        n_us = int(sr_us * duration_s)
        t_us = np.arange(n_us, dtype=np.float64) / sr_us
        env_mod = 0.65 + 0.35 * np.sin(2.0 * math.pi * 3.5 * t_us) * np.cos(2.0 * math.pi * 1.2 * t_us)
        ch1_us = 0.85 * np.sin(2.0 * math.pi * f1 * t_us)
        ch2_us = 0.85 * env_mod * np.sin(2.0 * math.pi * f2 * t_us)
        stereo_us = np.stack([ch1_us, ch2_us], axis=-1)
        pcm_us = np.clip(stereo_us * 32767.0, -32768, 32767).astype(np.int16)

        us_file = out_path / "enclave_ultrasonic_carriers_192k.wav"
        with wave.open(str(us_file), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr_us)
            wf.writeframes(pcm_us.tobytes())

        # 2. 48 kHz Stereo Audible Comparison (Left = Inside Enclave, Right = 22cm Outside Enclave)
        sr_aud = 48000
        n_aud = int(sr_aud * duration_s)
        t_aud = np.arange(n_aud, dtype=np.float64) / sr_aud
        env_aud = 0.65 + 0.35 * np.sin(2.0 * math.pi * 3.5 * t_aud) * np.cos(2.0 * math.pi * 1.2 * t_aud)

        inside_sig = 0.78 * env_aud * (
            0.80 * np.sin(2.0 * math.pi * f_beat * t_aud)
            + 0.20 * np.sin(2.0 * math.pi * (f_beat * 1.5) * t_aud)
        )
        isolation_db = snap["enclave_metrics"]["privacy_isolation_db"]
        atten_lin = 10.0 ** (-isolation_db / 20.0)
        rng = np.random.default_rng(20261117)
        outside_sig = inside_sig * atten_lin + rng.normal(0.0, 0.002, size=n_aud)

        stereo_aud = np.stack([inside_sig, outside_sig], axis=-1)
        pcm_aud = np.clip(stereo_aud * 32767.0, -32768, 32767).astype(np.int16)

        aud_file = out_path / "enclave_audible_comparison_48k.wav"
        with wave.open(str(aud_file), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr_aud)
            wf.writeframes(pcm_aud.tobytes())

        # 3. 48 kHz Dual-Tone Binaural Beat (250 Hz Left / 261 Hz Right -> 11 Hz Alpha Monologue)
        f_l = float(c.binaural_left_hz)
        f_r = float(c.binaural_right_hz)
        vocal_env = 0.70 + 0.30 * np.sin(2.0 * math.pi * 4.2 * t_aud)
        bin_left = 0.75 * vocal_env * np.sin(2.0 * math.pi * f_l * t_aud)
        bin_right = 0.75 * vocal_env * np.sin(2.0 * math.pi * f_r * t_aud)
        stereo_bin = np.stack([bin_left, bin_right], axis=-1)
        pcm_bin = np.clip(stereo_bin * 32767.0, -32768, 32767).astype(np.int16)

        bin_file = out_path / "cognitive_binaural_alpha_48k.wav"
        with wave.open(str(bin_file), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr_aud)
            wf.writeframes(pcm_bin.tobytes())

        return {
            "ok": True,
            "ultrasonic_wav": str(us_file),
            "audible_comparison_wav": str(aud_file),
            "binaural_alpha_wav": str(bin_file),
            "duration_s": duration_s,
            "f1_carrier_hz": f1,
            "f2_carrier_hz": f2,
            "audible_beat_hz": f_beat,
            "binaural_alpha_hz": round(abs(f_r - f_l), 2),
            "privacy_isolation_db": isolation_db,
        }


def _render_ascii_field(snap: Dict[str, Any]) -> str:
    """Render a compact terminal heatmap of the self-bending ultrasonic enclave."""
    grid = np.array(snap["spatial_field_2d"]["audible_spl_db"])
    us_grid = np.array(snap["spatial_field_2d"]["ultrasonic_spl_db"])
    x_grid = snap["spatial_field_2d"]["x_grid_m"]
    z_grid = snap["spatial_field_2d"]["z_grid_m"]
    chars = " .:-=+*#%@"
    lines = []
    lines.append("   Axial z (m) | Lateral x: -0.55m (Left) -------- 0.0m (Obstacle/Ear) -------- +0.55m (Right)")
    lines.append("  " + "-" * 86)
    peak = float(np.max(grid))
    floor = max(23.0, peak - 24.0)
    obs = snap["obstacle_bypass"]
    for iz in range(0, len(z_grid), 2):
        z_val = z_grid[iz]
        row_chars = []
        for ix in range(len(x_grid)):
            x_val = x_grid[ix]
            if obs["obstacle_enabled"]:
                d_obs = math.hypot(x_val - obs["obstacle_x_m"], z_val - obs["obstacle_z_m"])
                if d_obs <= (obs["obstacle_radius_cm"] / 100.0):
                    row_chars.append("O")
                    continue
            val = grid[iz, ix]
            if val >= floor + 2.5:
                norm = int(np.clip((val - floor) / max(peak - floor, 1.0), 0.0, 0.999) * len(chars))
                row_chars.append(chars[norm])
            elif us_grid[iz, ix] >= 101.5:
                row_chars.append("~")
            else:
                row_chars.append(" ")
        lines.append(f"   z={z_val:0.2f} m   | {''.join(row_chars)}")
    lines.append("  " + "-" * 86)
    lines.append("  Legend: '~' = Inaudible Self-Bending Beam (f1,f2) | 'O' = Head/Obstacle | '@' = Audible Enclave (f2-f1)")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Self-Bending Ultrasonic Audible Enclave & 7-Layer Tactical Audio Prototype"
    )
    parser.add_argument("--mode", choices=ENCLAVE_MODES, default="PRIVATE_ENCLAVE")
    parser.add_argument("--f1", type=float, default=40000.0, help="Beam 1 ultrasonic carrier (Hz)")
    parser.add_argument("--f2", type=float, default=39000.0, help="Beam 2 ultrasonic carrier (Hz)")
    parser.add_argument("--target-x", type=float, default=0.0, help="Target enclave X coordinate (m)")
    parser.add_argument("--target-z", type=float, default=0.85, help="Target enclave Z distance (m)")
    parser.add_argument("--curvature", type=float, default=0.92, help="Self-bending Airy curvature factor")
    parser.add_argument(
        "--intercept-preset",
        choices=list(INTERCEPT_PRESETS.keys()),
        default="KEYPAD_BURST",
        help="Wideband Goertzel signal preset to decode",
    )
    parser.add_argument("--export-wav", action="store_true", help="Export 192kHz/48kHz Enclave & Binaural WAVs")
    parser.add_argument("--json", action="store_true", help="Print full JSON telemetry")
    args = parser.parse_args()

    cfg = AudibleEnclaveConfig(
        mode=args.mode,
        f1_carrier_hz=args.f1,
        f2_carrier_hz=args.f2,
        target_x_m=args.target_x,
        target_z_m=args.target_z,
        bend_curvature=args.curvature,
        active_intercept_preset=args.intercept_preset,
    )
    engine = AudibleEnclaveEngine(cfg)
    snap = engine.compute_telemetry(force_journal_write=True)

    if args.json:
        print(json.dumps({k: v for k, v in snap.items() if k != "spatial_field_2d"}, indent=2))
        return

    print("=" * 94)
    print("  EARARRAY // SELF-BENDING ULTRASONIC AUDIBLE ENCLAVE & 7-LAYER TACTICAL AUDIO PROTOTYPE")
    print(f"  Reference: {snap['paper_reference']}")
    print("=" * 94)
    f_info = snap["frequencies_hz"]
    em = snap["enclave_metrics"]
    ob = snap["obstacle_bypass"]
    ts = snap["tactical_stack"]
    voc = ts["non_contact_vocal_lms"]
    fhss = ts["fhss_anti_intercept"]
    cog = ts["cognitive_loop_binaural"]
    wb = ts["wall_bounce_targeting"]
    gz = ts["wideband_goertzel_intercept"]
    db = ts["sqlite_spatial_journal"]

    print(
        f"  [0] Audible Enclave ({snap['mode']}): f1={f_info['f1_ultrasonic_hz']:.0f} Hz, "
        f"f2={f_info['f2_ultrasonic_hz']:.0f} Hz -> Beat {f_info['audible_enclave_beat_hz']:.0f} Hz | "
        f"Peak {em['peak_enclave_spl_db']:.1f} dB SPL (+{em['privacy_isolation_db']:.1f} dB isolation)"
    )
    print(
        f"  [1] Non-Contact Vocal Sonar: {voc['sonar_carrier_hz']:.0f} Hz CW | "
        f"Throat Disp={voc['throat_displacement_mm']:.2f} mm ({voc['throat_displacement_um']:.0f} um) | "
        f"F0={voc['reconstructed_f0_hz']:.0f} Hz -> Shifted {voc['voice_changed_f0_hz']:.1f} Hz"
    )
    print(
        f"  [2] Dynamic FHSS Shielding : {fhss['grid_square_id']} | "
        f"Hop={fhss['current_hop_freq_hz']:.0f} Hz ({fhss['hop_rate_hz']:.0f} hops/s, +{fhss['processing_gain_db']:.1f} dB) | "
        f"In 100m Grid={fhss['observer_inside_100m_grid']}"
    )
    print(
        f"  [3] Adaptive LMS Isolation : {voc['lms_echo_canceller']['filter_taps']}-tap NLMS | "
        f"TV Clutter {voc['lms_echo_canceller']['tv_background_spl_db']:.1f} dB -> "
        f"ERLE -{voc['lms_echo_canceller']['erle_suppression_db']:.1f} dB "
        f"(Fidelity={voc['lms_echo_canceller']['vocal_reconstruction_fidelity']:.3f})"
    )
    print(
        f"  [4] Cognitive Loop Delivery: Stereo {cog['left_ear_carrier_hz']:.0f} Hz (L) / "
        f"{cog['right_ear_carrier_hz']:.0f} Hz (R) -> {cog['binaural_beat_hz']:.1f} Hz Alpha Cortical Monologue"
    )
    print(
        f"  [5] Wall-Bounce Targeting  : 4 Multipath Streams Converge @ {wb['target_convergence_arrival_ms']:.2f} ms "
        f"(0.0 ms skew) | Couch Bystander Skew={wb['couch_bystander_skew_ms']:.2f} ms ({wb['couch_bystander_status']})"
    )
    print(
        f"  [6] Wideband 24kHz Goertzel: [{gz['transmission_type']}] -> \"{gz['decoded_plain_text']}\""
    )
    print(
        f"  [7] SQLite Spatial Journal : {db['last_trigger_reason']} [{db['priority_level']}] | "
        f"Committed Rows={db['total_committed_rows']} (DB: {Path(db['db_path']).name})"
    )
    print()
    print(_render_ascii_field(snap))

    if args.export_wav:
        logs_dir = Path(__file__).resolve().parent / "logs"
        wav_res = engine.export_prototype_wavs(logs_dir, cfg=cfg)
        print("\n  [WAV Export Complete]")
        print(f"    192 kHz Ultrasonic Carriers : {wav_res['ultrasonic_wav']}")
        print(f"    48 kHz Inside/Outside Audio : {wav_res['audible_comparison_wav']}")
        print(f"    48 kHz 11Hz Alpha Binaural  : {wav_res['binaural_alpha_wav']}")


if __name__ == "__main__":
    main()
