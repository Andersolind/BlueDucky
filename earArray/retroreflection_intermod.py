#!/usr/bin/env python3
"""
Acoustic Retroreflection and Parametric Intermodulation Engine
==============================================================

Models and detects the acoustic interaction mechanisms within an active
ultrasonic sonar field:

1. Passive Retroreflection Regime (Observer without active hardware):
   - Clothing Layer: Porous absorption + diffuse micro-scatter (low coherence).
   - Body / Torso Layer: Specular impedance boundary with cardiopulmonary
     micro-Doppler sidebands (0.2-0.5 Hz respiration, 1.0-1.8 Hz cardiac).
   - Throat / Vocal Tract Layer: Mechanical surface vibrometry producing
     weak symmetric phase-modulated sidebands around the primary carrier f1.

2. Active Transceiver & Mid-Air Parametric Intermodulation Regime:
   - When an observer introduces a high-sensitivity ultrasonic microphone
     paired with an adjustable ultrasonic transceiver (carrier f2), overlapping
     ultrasonic pressure fields undergo nonlinear Westervelt mixing in mid-air:
       * Difference tone (heterodyne beat): f_diff = |f1 - f2|
       * Sum frequency component:          f_sum  = f1 + f2
       * Cubic intermodulation (IMD3):     2*f1 - f2  and  2*f2 - f1
   - Diagnostic indicators include bicoherence quadratic phase coupling,
     effective reflection gain (Gamma_eff), IMD3 comb ratios, and non-physical
     electronic transceiver loop delay (tau_elec).
"""

import math
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
import numpy as np

try:
    from scipy import signal as scipy_signal
    from scipy.io import wavfile
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# Physical constants for dry air at 20 C
AIR_DENSITY_KGM3 = 1.204
SOUND_SPEED_MS = 343.0
NONLINEARITY_BETA = 1.20  # (gamma + 1) / 2 for diatomic air (gamma = 1.4)
REF_PRESSURE_PA = 20e-6   # 20 uPa reference for dB SPL


@dataclass
class RetroIntermodParams:
    """Simulation and diagnostic configuration for the sonar field & observer."""
    sample_rate: int = 192000
    sonar_freq_hz: float = 20000.0         # Primary active sonar f1 (20 kHz hidden carrier)
    sonar_spl_db: float = 102.0            # Primary emitter level
    observer_distance_m: float = 2.1       # Seated observer range
    observer_azimuth_deg: float = 18.0     # Seated observer angle

    # Passive reflector cross-sections & physiological modulation
    clothing_absorption: float = 0.38      # Fabric absorption factor (0..1)
    clothing_scatter_coeff: float = 0.24   # Diffuse backscatter
    torso_reflectivity: float = 0.72       # Specular body return
    respiration_hz: float = 0.28           # Breathing rate (~17 bpm)
    heart_rate_hz: float = 1.22            # Heart rate (~73 bpm)
    throat_vibration_hz: float = 145.0     # Vocal fold fundamental F0
    throat_modulation_idx: float = 0.08    # Passive vibrometry phase index

    # Observer active ultrasonic mic + adjustable transceiver
    active_transceiver_enabled: bool = True
    transceiver_freq_hz: float = 19000.0   # Opposing pilot f2 (19 kHz -> 1 kHz audible beat)
    transceiver_spl_db: float = 98.0       # Observer transceiver output SPL
    transceiver_gain_db: float = 14.0      # Active mic->tx amplification
    electronic_delay_us: float = 420.0     # Active loop group delay (microseconds)
    phase_lock_jitter_rad: float = 0.06    # Oscillator phase noise


class RetroreflectionIntermodAnalyzer:
    """
    Physics simulator and spectral/bicoherence detector for passive acoustic
    retroreflection vs. active mid-air heterodyne intermodulation.
    """

    def __init__(self, sample_rate: int = 192000):
        self.sample_rate = sample_rate

    @staticmethod
    def spl_to_pascals(spl_db: float) -> float:
        return REF_PRESSURE_PA * (10.0 ** (spl_db / 20.0))

    @staticmethod
    def pascals_to_spl(pressure_pa: float) -> float:
        return 20.0 * math.log10(max(pressure_pa, 1e-12) / REF_PRESSURE_PA)

    @staticmethod
    def atmospheric_alpha_np_per_m(freq_hz: float) -> float:
        """Approximate Stokes-Kirchhoff classical + relaxation absorption in air."""
        return 1.6e-10 * (freq_hz ** 2) + 0.0025 * ((freq_hz / 40000.0) ** 1.3)

    def compute_physics_model(self, params: RetroIntermodParams) -> Dict:
        """
        Compute analytical acoustic field levels, passive reflection zones,
        and Westervelt mid-air parametric intermodulation products.
        """
        f1 = float(params.sonar_freq_hz)
        f2 = float(params.transceiver_freq_hz)
        r = max(0.3, float(params.observer_distance_m))

        p1_0 = self.spl_to_pascals(params.sonar_spl_db)
        alpha1 = self.atmospheric_alpha_np_per_m(f1)

        # Incident pressure at observer location
        p1_obs = (p1_0 / r) * math.exp(-alpha1 * r)

        # 1. Passive reflector components returning to sonar array (round-trip 2*r)
        round_trip_atten = (1.0 / (2.0 * r)) * math.exp(-2.0 * alpha1 * r)
        cloth_factor = (1.0 - params.clothing_absorption) * params.clothing_scatter_coeff
        torso_factor = (1.0 - 0.5 * params.clothing_absorption) * params.torso_reflectivity
        throat_factor = 0.18 * (1.0 + params.throat_modulation_idx)

        p_cloth_ret = p1_0 * round_trip_atten * cloth_factor
        p_torso_ret = p1_0 * round_trip_atten * torso_factor
        p_throat_ret = p1_0 * round_trip_atten * throat_factor
        p_passive_total = math.sqrt(p_cloth_ret**2 + p_torso_ret**2 + p_throat_ret**2)

        tof_acoustic_ms = (2.0 * r / SOUND_SPEED_MS) * 1000.0

        # 2. Active observer microphone + adjustable ultrasonic transceiver
        f_diff = abs(f1 - f2)
        f_sum = f1 + f2
        f_imd3_low = abs(2.0 * min(f1, f2) - max(f1, f2))
        f_imd3_high = abs(2.0 * max(f1, f2) - min(f1, f2))

        if params.active_transceiver_enabled:
            p2_0 = self.spl_to_pascals(params.transceiver_spl_db)
            alpha2 = self.atmospheric_alpha_np_per_m(f2)
            # Mid-air interaction zone centered near midpoint r_mix = 0.5 * r
            r_mix = max(0.25, 0.5 * r)
            p1_mix = (p1_0 / r_mix) * math.exp(-alpha1 * r_mix)
            p2_mix = (p2_0 / r_mix) * math.exp(-alpha2 * r_mix)

            # Westervelt parametric difference-frequency pressure scaling:
            # p_diff ~ (beta * omega_diff^2 * P1 * P2 * V_eff) / (4 * pi * rho0 * c0^4 * r_mix)
            omega_diff = 2.0 * math.pi * max(f_diff, 20.0)
            interaction_length = min(r * 0.75, 1.8)
            beam_radius = 0.14
            interaction_vol = math.pi * (beam_radius ** 2) * interaction_length

            p_diff_pa = (
                NONLINEARITY_BETA
                * (omega_diff ** 2)
                * p1_mix
                * p2_mix
                * interaction_vol
            ) / (4.0 * math.pi * AIR_DENSITY_KGM3 * (SOUND_SPEED_MS ** 4) * r_mix)

            # Boost slightly for near-collinear end-fire phase matching
            endfire_gain = 18.0
            p_diff_pa *= endfire_gain

            # Sum frequency (heavily attenuated by air)
            alpha_sum = self.atmospheric_alpha_np_per_m(f_sum)
            p_sum_pa = p_diff_pa * 0.35 * math.exp(-alpha_sum * r_mix)

            # Active retroreflected carrier component (with observer gain)
            lin_gain = 10.0 ** (params.transceiver_gain_db / 20.0)
            p2_at_array = (p2_0 / r) * math.exp(-alpha2 * r)
            p_active_echo = p1_obs * lin_gain * 0.12 * math.exp(-alpha1 * r)
            p_imd3_pa = 0.08 * math.sqrt(p1_mix * p2_mix) * 0.02

            effective_gamma = (p_active_echo + p2_at_array * 0.35) / max(p_passive_total, 1e-9)
            bicoherence = float(np.clip(0.78 + 0.16 * math.tanh((params.transceiver_spl_db - 90.0) / 10.0) - params.phase_lock_jitter_rad * 0.4, 0.0, 0.99))
            total_delay_ms = tof_acoustic_ms + (params.electronic_delay_us / 1000.0)
            regime = "ACTIVE_HETERODYNE_MIXING"
        else:
            p2_at_array = 0.0
            p_diff_pa = 0.0
            p_sum_pa = 0.0
            p_imd3_pa = 0.0
            effective_gamma = float(np.clip(p_passive_total / max(p1_obs, 1e-9), 0.05, 0.95))
            bicoherence = 0.09
            total_delay_ms = tof_acoustic_ms
            regime = "PASSIVE_RETROREFLECTION"

        # Synthesize display spectrum (0 to 96 kHz, 256 bins)
        max_freq = min(params.sample_rate / 2.0, 96000.0)
        n_bins = 256
        freqs = np.linspace(0.0, max_freq, n_bins)
        noise_floor_db = 18.0
        rng = np.random.default_rng(int(time.time() * 10) % 100000)
        spec_db = noise_floor_db + rng.normal(0.0, 1.1, size=n_bins)

        def add_peak(center_hz: float, level_db: float, width_hz: float = 450.0):
            if center_hz <= 0 or center_hz >= max_freq or level_db <= noise_floor_db:
                return
            profile = (level_db - noise_floor_db) * np.exp(-0.5 * ((freqs - center_hz) / width_hz) ** 2)
            nonlocal spec_db
            spec_db = np.maximum(spec_db, noise_floor_db + profile)

        # Primary sonar return + passive physiological/vocal sidebands
        passive_spl = self.pascals_to_spl(p_passive_total)
        add_peak(f1, passive_spl, 380.0)
        add_peak(f1 - params.throat_vibration_hz, passive_spl - 18.0, 220.0)
        add_peak(f1 + params.throat_vibration_hz, passive_spl - 18.0, 220.0)

        if params.active_transceiver_enabled:
            tx_arr_spl = self.pascals_to_spl(p2_at_array)
            diff_spl = self.pascals_to_spl(p_diff_pa)
            sum_spl = self.pascals_to_spl(p_sum_pa)
            imd3_spl = self.pascals_to_spl(p_imd3_pa)

            add_peak(f2, tx_arr_array_db := tx_arr_spl, 380.0)
            add_peak(f_diff, diff_spl, 320.0)
            add_peak(f_sum, sum_spl, 520.0)
            add_peak(f_imd3_low, imd3_spl, 340.0)
            add_peak(f_imd3_high, imd3_spl, 340.0)
        else:
            tx_arr_array_db = 0.0
            diff_spl = 0.0
            sum_spl = 0.0
            imd3_spl = 0.0

        # Apparent DOA shift of mid-air virtual parametric source
        parametric_doa_deg = (
            params.observer_azimuth_deg * 0.62
            if params.active_transceiver_enabled
            else params.observer_azimuth_deg
        )

        # Confidence score for active heterodyne detection
        active_score = 0.0
        indicators = []
        if params.active_transceiver_enabled:
            if bicoherence > 0.45:
                active_score += 0.38
                indicators.append(f"Quadratic phase coupling (bicoherence={bicoherence:.2f}) between f1={f1:.0f}Hz, f2={f2:.0f}Hz, f_diff={f_diff:.0f}Hz")
            if effective_gamma > 1.05:
                active_score += 0.27
                indicators.append(f"Anomalous retroreflection gain Gamma_eff={effective_gamma:.2f} (>1.0 passive limit)")
            if f_diff < 20000.0 and diff_spl > 24.0:
                active_score += 0.20
                indicators.append(f"Audible/near-audible mid-air heterodyne beat at {f_diff:.0f} Hz ({diff_spl:.1f} dB SPL)")
            if params.electronic_delay_us > 50.0:
                active_score += 0.15
                indicators.append(f"Non-acoustic transceiver group delay (+{params.electronic_delay_us:.0f} us over {tof_acoustic_ms:.2f} ms ToF)")
        else:
            indicators.append("Passive reflection only: diffuse clothing scatter + cardiopulmonary/throat micro-Doppler")

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "regime": regime,
            "active_detection_confidence": round(min(active_score, 1.0), 3),
            "indicators": indicators,
            "frequencies_hz": {
                "f1_sonar": round(f1, 1),
                "f2_transceiver": round(f2, 1) if params.active_transceiver_enabled else None,
                "f_diff_heterodyne": round(f_diff, 1) if params.active_transceiver_enabled else None,
                "f_sum": round(f_sum, 1) if params.active_transceiver_enabled else None,
                "f_imd3_low": round(f_imd3_low, 1) if params.active_transceiver_enabled else None,
                "f_imd3_high": round(f_imd3_high, 1) if params.active_transceiver_enabled else None,
                "is_audible_heterodyne": bool(params.active_transceiver_enabled and 20.0 <= f_diff <= 18000.0),
            },
            "passive_zones": {
                "clothing": {
                    "spl_db": round(self.pascals_to_spl(p_cloth_ret), 1),
                    "absorption": params.clothing_absorption,
                    "scatter_coeff": params.clothing_scatter_coeff,
                    "character": "Diffuse porous scatter (low temporal coherence)",
                },
                "body_torso": {
                    "spl_db": round(self.pascals_to_spl(p_torso_ret), 1),
                    "respiration_hz": params.respiration_hz,
                    "heart_rate_hz": params.heart_rate_hz,
                    "character": "Specular boundary + cardiopulmonary micro-Doppler",
                },
                "throat_vocal": {
                    "spl_db": round(self.pascals_to_spl(p_throat_ret), 1),
                    "fundamental_hz": params.throat_vibration_hz,
                    "modulation_index": params.throat_modulation_idx,
                    "character": "Laryngeal tissue vibrometry (f1 +/- F0 phase sidebands)",
                },
                "combined_passive_spl_db": round(passive_spl, 1),
            },
            "intermodulation_metrics": {
                "transceiver_rx_spl_db": round(tx_arr_array_db, 1),
                "heterodyne_diff_spl_db": round(diff_spl, 1),
                "sum_freq_spl_db": round(sum_spl, 1),
                "imd3_spl_db": round(imd3_spl, 1),
                "effective_reflection_gamma": round(effective_gamma, 3),
                "bicoherence": round(bicoherence, 3),
                "acoustic_tof_ms": round(tof_acoustic_ms, 3),
                "total_loop_delay_ms": round(total_delay_ms, 3),
                "observer_doa_deg": round(params.observer_azimuth_deg, 1),
                "virtual_midair_doa_deg": round(parametric_doa_deg, 1),
            },
            "spectrum": {
                "freqs_hz": np.round(freqs, 1).tolist(),
                "power_db": np.round(spec_db, 2).tolist(),
            },
            "params": asdict(params),
        }

    def analyze_audio_buffer(self, audio: np.ndarray, sample_rate: int) -> Dict:
        """
        Inspect an actual recorded waveform (e.g., from dolphin_forensics/*.wav
        or live microphone input) for dual-carrier intermodulation & bicoherence.
        """
        if audio.ndim > 1:
            mono = np.mean(audio, axis=-1 if audio.shape[-1] <= 8 else 0).astype(np.float64)
        else:
            mono = audio.astype(np.float64)

        mono = mono - np.mean(mono)
        n = len(mono)
        if n < 512:
            return {"detected": False, "reason": "buffer_too_short"}

        nfft = min(8192, 1 << int(math.log2(n)))
        win = np.hanning(nfft)
        X = np.fft.rfft(mono[:nfft] * win)
        freqs = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
        mag = np.abs(X)
        mag_db = 20.0 * np.log10(mag + 1e-12)

        # Search high-frequency / ultrasonic region (> 14 kHz, or top 35% of Nyquist)
        hf_cut = min(14000.0, sample_rate * 0.32)
        hf_mask = freqs >= hf_cut
        if not np.any(hf_mask):
            return {"detected": False, "reason": "sample_rate_too_low"}

        hf_freqs = freqs[hf_mask]
        hf_db = mag_db[hf_mask]
        noise_floor = float(np.percentile(mag_db, 25))

        # Find top 2 separated ultrasonic peaks (candidate f1 and f2)
        order = np.argsort(hf_db)[::-1]
        peaks: List[Tuple[float, float, int]] = []
        for idx in order:
            f_cand = float(hf_freqs[idx])
            p_cand = float(hf_db[idx])
            if p_cand < noise_floor + 8.0:
                break
            if all(abs(f_cand - pf) > 350.0 for pf, _, _ in peaks):
                full_idx = int(np.argmin(np.abs(freqs - f_cand)))
                peaks.append((f_cand, p_cand, full_idx))
            if len(peaks) >= 2:
                break

        if len(peaks) < 2:
            f1 = peaks[0][0] if peaks else 0.0
            return {
                "detected": False,
                "regime": "SINGLE_CARRIER_OR_PASSIVE",
                "f1_hz": round(f1, 1),
                "f2_hz": None,
                "f_diff_hz": None,
                "bicoherence": 0.0,
                "noise_floor_db": round(noise_floor, 2),
            }

        (f1, p1_db, i1), (f2, p2_db, i2) = peaks[0], peaks[1]
        f_diff = abs(f1 - f2)
        i_diff = int(np.argmin(np.abs(freqs - f_diff)))
        p_diff_db = float(mag_db[i_diff])

        # Estimate multi-segment bicoherence at (f1, -f2 -> f_diff)
        seg_len = min(2048, n // 2)
        step = max(256, seg_len // 2)
        num_segs = 0
        bispec_acc = 0.0 + 0.0j
        norm_a = 0.0
        norm_b = 0.0

        f_hi, f_lo = (f1, f2) if f1 >= f2 else (f2, f1)
        w_seg = np.hanning(seg_len)
        seg_freqs = np.fft.rfftfreq(seg_len, 1.0 / sample_rate)
        k_hi = int(np.argmin(np.abs(seg_freqs - f_hi)))
        k_lo = int(np.argmin(np.abs(seg_freqs - f_lo)))
        k_df = int(np.argmin(np.abs(seg_freqs - (f_hi - f_lo))))

        for start in range(0, n - seg_len + 1, step):
            S = np.fft.rfft(mono[start:start + seg_len] * w_seg)
            prod = S[k_lo] * S[k_df] * np.conj(S[k_hi])
            bispec_acc += prod
            norm_a += float(np.abs(S[k_lo] * S[k_df]) ** 2)
            norm_b += float(np.abs(S[k_hi]) ** 2)
            num_segs += 1

        if num_segs >= 2 and norm_a > 0 and norm_b > 0:
            bicoherence = float(np.abs(bispec_acc) / math.sqrt(norm_a * norm_b + 1e-18))
        else:
            bicoherence = 0.0

        diff_snr = p_diff_db - noise_floor
        detected = bool(bicoherence > 0.42 and diff_snr > 6.0)

        return {
            "detected": detected,
            "regime": "ACTIVE_HETERODYNE_MIXING" if detected else "DUAL_TONE_UNCOUPLED",
            "f1_hz": round(f_hi, 1),
            "f1_db": round(max(p1_db, p2_db), 1),
            "f2_hz": round(f_lo, 1),
            "f2_db": round(min(p1_db, p2_db), 1),
            "f_diff_hz": round(f_diff, 1),
            "f_diff_db": round(p_diff_db, 1),
            "diff_snr_db": round(diff_snr, 1),
            "bicoherence": round(float(np.clip(bicoherence, 0.0, 1.0)), 3),
            "noise_floor_db": round(noise_floor, 2),
            "segments_evaluated": num_segs,
        }

    def analyze_wav_file(self, filepath: str) -> Dict:
        if not HAS_SCIPY:
            return {"detected": False, "error": "scipy required"}
        sr, data = wavfile.read(filepath)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        return self.analyze_audio_buffer(data, int(sr))


if __name__ == "__main__":
    engine = RetroreflectionIntermodAnalyzer()
    demo_params = RetroIntermodParams()
    report = engine.compute_physics_model(demo_params)
    import json
    print(json.dumps({k: v for k, v in report.items() if k != "spectrum"}, indent=2))
