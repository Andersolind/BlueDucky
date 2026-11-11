#!/usr/bin/env python3
"""
Sensing Core & Target Delivery Core
===================================

1. Sensing Core: Pilot-Tone Phase Demodulation
   - Non-contact ambient tracking replacing physical skin-contact sEMG electrodes.
   - Emits an ultrasonic CW pilot tone f_p and performs coherent IQ quadrature
     demodulation (I/Q baseband mixing + phase unwrapping) to recover micron-scale
     tissue/laryngeal/gesture displacement:
         delta_phi(t) = (4 * pi / lambda_p) * delta_d(t)

2. Target Delivery Core: Spatial Isolation & Beamforming
   - Delay-and-Sum Array Beamforming: Computes geometric steering delays tau_m(theta_0)
     across a multi-channel array to focus sensitivity on an exact look-angle while
     electronically nulling off-axis room noise.
   - Binaural Audio Spatial Targeting (HRTF): Maps processed audio through a spherical-head
     Woodworth + pinna HRTF model to compute exact Interaural Time Differences (ITD) and
     Interaural Level Differences (ILD) aimed at a 3D target listener coordinate.
"""

import math
import time
from dataclasses import dataclass, asdict
from typing import Dict, List
import numpy as np

SOUND_SPEED_MS = 343.0
HEAD_RADIUS_M = 0.0875  # Standard adult Woodworth head radius (8.75 cm)


@dataclass
class PilotSensingParams:
    pilot_freq_hz: float = 24000.0        # Non-contact ultrasonic pilot carrier
    sample_rate_hz: int = 96000
    target_range_m: float = 1.45          # Distance to tracked subject (no skin contact)
    laryngeal_f0_hz: float = 132.0        # Subvocal / vocal fold micro-motion frequency
    laryngeal_disp_um: float = 42.0       # Micron displacement amplitude (um)
    gesture_freq_hz: float = 1.8          # Fine motor / jaw / gesture motion (Hz)
    gesture_disp_um: float = 380.0        # Sub-mm gesture amplitude (um)
    snr_db: float = 28.0                  # Baseband IQ SNR
    dc_clutter_Static: float = 0.35       # Static room clutter vector


class PilotTonePhaseDemodulator:
    """Coherent IQ quadrature phase demodulator for non-contact vibrometry."""

    def compute_telemetry(self, p: PilotSensingParams) -> Dict:
        wavelength_m = SOUND_SPEED_MS / max(p.pilot_freq_hz, 1000.0)
        wavelength_mm = wavelength_m * 1000.0

        # Synthesize 80 ms baseband capture @ 2 kHz decimated rate (160 samples)
        fs_bb = 2000.0
        n_pts = 160
        t = np.arange(n_pts) / fs_bb
        phase_offset = (time.time() * 1.7) % (2.0 * math.pi)

        # True physical surface displacement delta_d(t) in meters
        disp_m = (
            (p.laryngeal_disp_um * 1e-6) * np.sin(2.0 * math.pi * p.laryngeal_f0_hz * t + phase_offset)
            + (p.gesture_disp_um * 1e-6) * np.sin(2.0 * math.pi * p.gesture_freq_hz * t + phase_offset * 0.3)
        )

        # Theoretical round-trip phase shift: phi(t) = 4 * pi * d(t) / lambda
        true_phi = (4.0 * math.pi / wavelength_m) * disp_m

        # Complex IQ baseband with static clutter + AWGN
        noise_std = 10.0 ** (-p.snr_db / 20.0)
        rng = np.random.default_rng(int(time.time() * 12) % 100000)
        i_raw = p.dc_clutter_Static + np.cos(true_phi) + rng.normal(0.0, noise_std, size=n_pts)
        q_raw = 0.15 + np.sin(true_phi) + rng.normal(0.0, noise_std, size=n_pts)

        # Circle-center DC clutter removal (non-contact calibration)
        i_cal = i_raw - np.mean(i_raw) + np.mean(np.cos(true_phi))
        q_cal = q_raw - np.mean(q_raw) + np.mean(np.sin(true_phi))

        # Arctan2 + phase unwrapping
        demod_phi = np.unwrap(np.arctan2(q_cal, i_cal))
        demod_phi = demod_phi - np.mean(demod_phi)
        recovered_disp_um = (demod_phi * wavelength_m / (4.0 * math.pi)) * 1e6

        rms_error_um = float(np.sqrt(np.mean((recovered_disp_um - disp_m * 1e6) ** 2)))
        phase_sensitivity_rad_per_mm = (4.0 * math.pi) / wavelength_mm
        max_phase_excursion_rad = float(np.max(np.abs(demod_phi)))

        # IQ constellation arc points (64 points)
        iq_arc = [
            {"i": round(float(i_cal[k]), 4), "q": round(float(q_cal[k]), 4)}
            for k in range(0, n_pts, 2)
        ]

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "NON_CONTACT_PILOT_IQ",
            "metrics": {
                "pilot_wavelength_mm": round(wavelength_mm, 3),
                "phase_sensitivity_rad_mm": round(phase_sensitivity_rad_per_mm, 3),
                "max_phase_rad": round(max_phase_excursion_rad, 3),
                "peak_displacement_um": round(float(np.max(np.abs(recovered_disp_um))), 1),
                "tracking_rms_error_um": round(rms_error_um, 2),
                "coherence_quality": round(float(np.clip(1.0 - noise_std * 2.5, 0.0, 0.995)), 3),
            },
            "waveform": {
                "time_ms": np.round(t * 1000.0, 2).tolist(),
                "displacement_um": np.round(recovered_disp_um, 2).tolist(),
                "phase_rad": np.round(demod_phi, 4).tolist(),
            },
            "iq_constellation": iq_arc,
            "params": asdict(p),
        }


@dataclass
class BeamformingHRTFParams:
    # Delay-and-Sum Microphone/Emitter Array
    num_mics: int = 8                     # M-element linear/circular array
    element_spacing_m: float = 0.042      # 4.2 cm spacing (~half-wavelength @ 4 kHz)
    center_freq_hz: float = 3200.0        # Design passband center for array pattern
    steer_azimuth_deg: float = -24.0      # Look-angle steering (-90 to +90 deg)
    null_jammer_deg: float = 42.0         # Ambient room noise source angle
    window_taper: str = "hamming"         # "uniform" | "hamming" | "chebyshev_like"

    # Binaural HRTF Spatial Targeting
    target_x_m: float = -1.15             # Target listener X coordinate (m)
    target_y_m: float = 1.20              # Ear-height Y coordinate (m)
    target_z_m: float = 2.40              # Target listener Z coordinate (m)
    voice_pitch_shift_st: float = -2.5    # Voice-changer semitone shift metadata
    pinna_elevation_deg: float = 8.0      # Elevation cue for pinna notch


class SpatialBeamformingCore:
    """Delay-and-Sum beamforming + Woodworth/HRTF ITD & ILD spatial targeting."""

    def compute_telemetry(self, p: BeamformingHRTFParams) -> Dict:
        m_count = max(2, min(32, int(p.num_mics)))
        d = max(0.005, float(p.element_spacing_m))
        f0 = max(200.0, float(p.center_freq_hz))
        k_wave = (2.0 * math.pi * f0) / SOUND_SPEED_MS
        theta0_rad = math.radians(p.steer_azimuth_deg)

        # Element indices centered at array origin
        idx = np.arange(m_count) - (m_count - 1) / 2.0

        # Geometric steering delays tau_m = (x_m * sin(theta_0)) / c
        delays_us = ((idx * d * math.sin(theta0_rad)) / SOUND_SPEED_MS) * 1e6

        # Shading weights
        if p.window_taper == "hamming":
            weights = np.hamming(m_count)
        elif p.window_taper == "chebyshev_like":
            weights = np.blackman(m_count) + 0.08
        else:
            weights = np.ones(m_count)
        weights = weights / np.sum(weights)

        # Polar array factor across -90..+90 deg (181 angles)
        angles_deg = np.linspace(-90.0, 90.0, 181)
        angles_rad = np.radians(angles_deg)
        phase_diff = k_wave * d * (np.sin(angles_rad)[:, None] - math.sin(theta0_rad))
        steering_mat = np.exp(1j * phase_diff * idx[None, :])
        af_complex = steering_mat @ weights
        af_mag = np.abs(af_complex)
        af_db = 20.0 * np.log10(np.clip(af_mag, 1e-4, 1.0))

        # Jammer / ambient room noise suppression at null_jammer_deg
        jam_idx = int(np.argmin(np.abs(angles_deg - p.null_jammer_deg)))
        jammer_atten_db = float(-af_db[jam_idx])
        array_gain_db = round(10.0 * math.log10(m_count), 2)

        # Half-power (-3 dB) beamwidth estimate
        above_3db = angles_deg[af_db >= -3.0]
        beamwidth_deg = float(above_3db[-1] - above_3db[0]) if len(above_3db) >= 2 else 180.0

        # ---- Binaural HRTF ITD & ILD Mapping for Target Coordinate ----
        horiz_dist = math.hypot(p.target_x_m, p.target_z_m)
        full_dist = math.sqrt(p.target_x_m**2 + (p.target_y_m - 1.2)**2 + p.target_z_m**2)
        target_az_rad = math.atan2(p.target_x_m, max(0.05, p.target_z_m))
        target_az_deg = math.degrees(target_az_rad)

        # Woodworth spherical-head ITD formula: ITD = (a / c) * (theta + sin(theta))
        az_abs = min(abs(target_az_rad), math.pi / 2.0)
        itd_sec = (HEAD_RADIUS_M / SOUND_SPEED_MS) * (az_abs + math.sin(az_abs))
        itd_us = math.copysign(itd_sec * 1e6, target_az_rad)

        # Frequency-dependent head-shadowing ILD (Brown & Duda spherical head approximation)
        hrtf_freqs = np.geomspace(125.0, 16000.0, 48)
        ild_curve_db = []
        left_gain_db = []
        right_gain_db = []

        pinna_notch_hz = 7200.0 + 95.0 * p.pinna_elevation_deg
        for f_h in hrtf_freqs:
            alpha_f = (2.0 * math.pi * f_h * HEAD_RADIUS_M) / SOUND_SPEED_MS
            # Max ILD grows with dimensionless head size alpha_f * sin(azimuth)
            ild_mag = 1.5 + 9.5 * math.log10(1.0 + (alpha_f * math.sin(az_abs)) ** 1.6)
            signed_ild = math.copysign(ild_mag, target_az_rad)
            # Pinna spectral elevation notch around 6-10 kHz
            notch = -9.0 * math.exp(-0.5 * ((f_h - pinna_notch_hz) / 650.0) ** 2)
            ild_curve_db.append(round(signed_ild, 2))
            right_gain_db.append(round((signed_ild * 0.5) + notch, 2))
            left_gain_db.append(round((-signed_ild * 0.5) + notch, 2))

        broadband_ild_db = float(np.mean(np.abs(ild_curve_db[16:38]))) * (1.0 if target_az_rad >= 0 else -1.0)
        spatial_bleed_isolation_db = round(min(32.0, array_gain_db + abs(broadband_ild_db) * 0.85 + 6.5), 1)

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "delay_and_sum": {
                "num_mics": m_count,
                "steer_azimuth_deg": round(p.steer_azimuth_deg, 1),
                "beamwidth_3db_deg": round(beamwidth_deg, 1),
                "array_directivity_gain_db": array_gain_db,
                "ambient_jammer_suppression_db": round(jammer_atten_db, 1),
                "element_delays_us": np.round(delays_us, 2).tolist(),
                "element_weights": np.round(weights, 4).tolist(),
                "polar_angles_deg": np.round(angles_deg, 1).tolist(),
                "polar_gain_db": np.round(af_db, 2).tolist(),
            },
            "binaural_hrtf": {
                "target_coord_m": {
                    "x": round(p.target_x_m, 2),
                    "y": round(p.target_y_m, 2),
                    "z": round(p.target_z_m, 2),
                },
                "target_range_m": round(full_dist, 2),
                "target_azimuth_deg": round(target_az_deg, 1),
                "itd_us": round(itd_us, 2),
                "broadband_ild_db": round(broadband_ild_db, 2),
                "pinna_notch_hz": round(pinna_notch_hz, 0),
                "spatial_isolation_db": spatial_bleed_isolation_db,
                "voice_pitch_shift_st": p.voice_pitch_shift_st,
                "freqs_hz": np.round(hrtf_freqs, 1).tolist(),
                "ild_db": ild_curve_db,
                "left_ear_tf_db": left_gain_db,
                "right_ear_tf_db": right_gain_db,
            },
            "params": asdict(p),
        }


if __name__ == "__main__":
    p_eng = PilotTonePhaseDemodulator()
    b_eng = SpatialBeamformingCore()
    r1 = p_eng.compute_telemetry(PilotSensingParams())
    r2 = b_eng.compute_telemetry(BeamformingHRTFParams())
    print("Pilot IQ:", r1["metrics"])
    print("Beamforming:", r2["delay_and_sum"]["beamwidth_3db_deg"], "deg | HRTF ITD:", r2["binaural_hrtf"]["itd_us"], "us")
