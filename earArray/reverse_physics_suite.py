#!/usr/bin/env python3
"""
Reverse-Physics & Counter-Observation Telemetry Suite
=====================================================

Covers the three bidirectional physical interaction mechanisms:
1. Acoustic Retroreflection & Parametric Intermodulation (via retroreflection_intermod.py)
   - Passive clothing/body/throat reflection vs. opposing pilot tone (e.g. 19 kHz vs 20 kHz
     producing an audible 1 kHz mid-air difference tone).
2. Local Oscillator (LO) Radiation & Unintentional EM Leakage
   - Models internal SDR receive-only mixer LO generation (f_LO = f_RF +/- f_IF),
     reverse mixer/LNA port isolation (S12), PCB/chassis slot radiation, and
     spatial RSSI heatmap vulnerability to near-field or high-gain directional sweeps.
3. Acoustic Speaker Coil Microphonics (Transducer Reversibility)
   - Models Faraday electromagnetic induction (V_emf = B * l * v_cone) when an external
     acoustic impulse or targeted room vibration strikes unpowered or active speaker
     cones, sending micro-volt back-EMF pulses onto speaker cables and amplifier rails.
"""

import math
import time
from dataclasses import dataclass, asdict
from typing import Dict, List
import numpy as np

from retroreflection_intermod import (
    RetroIntermodParams,
    RetroreflectionIntermodAnalyzer,
)

LIGHT_SPEED_MS = 299_792_458.0


# =============================================================================
# 2. LOCAL OSCILLATOR (LO) RADIATION & LEAKAGE ENGINE
# =============================================================================

@dataclass
class LOLeakageParams:
    sdr_architecture: str = "superhet"       # "superhet" | "zero_if" | "low_if"
    tuned_rf_mhz: float = 433.92             # Receive-only observation frequency
    if_freq_mhz: float = 21.4                # Intermediate frequency (0 for zero_if)
    lo_drive_dbm: float = 7.0                # Internal PLL/VCO mixer drive level
    mixer_lo_rf_isolation_db: float = 42.0   # Mixer port isolation
    lna_reverse_isolation_db: float = 28.0   # LNA S12 reverse isolation (RX mode)
    chassis_shielding_db: float = 24.0       # Enclosure SE (plastic=5, anodized Al=35, EMI gasket=60)
    rf_preselector_atten_db: float = 12.0    # Front-end bandpass attenuation at f_LO
    # Sweeping observer probe parameters
    scanner_distance_m: float = 1.8          # Third-party probe range
    scanner_azimuth_deg: float = -35.0       # Probe angle relative to SDR
    scanner_antenna_gain_dbi: float = 11.0   # Directional log-periodic / Yagi gain
    scanner_noise_floor_dbm: float = -118.0  # Narrowband RBW=100Hz spectrum analyzer floor
    sdr_pos_x: float = 0.0                   # Hardware coordinate X (m)
    sdr_pos_z: float = 0.0                   # Hardware coordinate Z (m)


class LOLeakageAnalyzer:
    """Evaluates receive-only SDR Local Oscillator leakage and spatial pinpointing risk."""

    def compute_model(self, p: LOLeakageParams) -> Dict:
        if p.sdr_architecture == "zero_if":
            if_eff = 0.0
        elif p.sdr_architecture == "low_if":
            if_eff = min(p.if_freq_mhz, 2.0)
        else:
            if_eff = p.if_freq_mhz

        lo_freq_mhz = p.tuned_rf_mhz + if_eff
        lo_2x_mhz = lo_freq_mhz * 2.0
        lo_3x_mhz = lo_freq_mhz * 3.0
        wavelength_m = LIGHT_SPEED_MS / (lo_freq_mhz * 1e6)

        # Conducted leakage backward out of RX antenna port
        port_leakage_dbm = (
            p.lo_drive_dbm
            - p.mixer_lo_rf_isolation_db
            - p.lna_reverse_isolation_db
            - p.rf_preselector_atten_db
        )

        # Direct PCB trace / seam slot radiation through device casing
        pcb_coupling_loss_db = 32.0
        chassis_leakage_dbm = p.lo_drive_dbm - pcb_coupling_loss_db - p.chassis_shielding_db

        # Combine incoherent port + chassis effective radiated power
        p_port_mw = 10.0 ** (port_leakage_dbm / 10.0)
        p_chas_mw = 10.0 ** (chassis_leakage_dbm / 10.0)
        total_eirp_mw = p_port_mw + p_chas_mw
        total_eirp_dbm = 10.0 * math.log10(max(total_eirp_mw, 1e-18))

        # Free-space + near-field reactive coupling path loss at scanner distance
        d = max(0.15, p.scanner_distance_m)
        fspl_db = 20.0 * math.log10(4.0 * math.pi * d / max(wavelength_m, 1e-4))
        # Near-field reactive enhancement when d < lambda / (2*pi)
        near_field_boundary_m = wavelength_m / (2.0 * math.pi)
        nf_boost_db = 6.0 * math.log10(near_field_boundary_m / d) if d < near_field_boundary_m else 0.0

        received_lo_dbm = total_eirp_dbm - fspl_db + nf_boost_db + p.scanner_antenna_gain_dbi
        snr_at_scanner_db = received_lo_dbm - p.scanner_noise_floor_dbm

        # Coordinate pinpointing CEP (Circular Error Probable in meters)
        if snr_at_scanner_db > 3.0:
            cep_m = max(0.04, (d * 0.35) / math.sqrt(10.0 ** (min(snr_at_scanner_db, 40.0) / 10.0)))
            detectable = True
        else:
            cep_m = 99.9
            detectable = False

        if snr_at_scanner_db >= 20.0:
            risk_level = "CRITICAL_PINPOINTABLE"
        elif snr_at_scanner_db >= 8.0:
            risk_level = "HIGH_DETECTABLE"
        elif snr_at_scanner_db >= 0.0:
            risk_level = "MARGINAL_NEARFIELD"
        else:
            risk_level = "CONCEALED_BELOW_FLOOR"

        # Generate 9x9 spatial leakage heatmap around SDR (4m x 4m grid)
        grid_coords = np.linspace(-3.0, 3.0, 13)
        heatmap = []
        for gz in grid_coords:
            row = []
            for gx in grid_coords:
                dist = math.hypot(gx - p.sdr_pos_x, gz - p.sdr_pos_z)
                dist_clamped = max(0.18, dist)
                pl = 20.0 * math.log10(4.0 * math.pi * dist_clamped / max(wavelength_m, 1e-4))
                rx = total_eirp_dbm - pl + p.scanner_antenna_gain_dbi
                row.append(round(rx, 1))
            heatmap.append(row)

        # Synthesize narrowband RF sweep spectrum around f_LO
        span_mhz = max(60.0, if_eff * 3.0)
        f_start = p.tuned_rf_mhz - span_mhz * 0.35
        f_stop = lo_freq_mhz + span_mhz * 0.65
        rf_freqs = np.linspace(f_start, f_stop, 160)
        rng = np.random.default_rng(int(time.time() * 8) % 100000)
        rf_spec = p.scanner_noise_floor_dbm + rng.normal(0.0, 1.2, size=160)

        def inject_spur(freq_mhz: float, level_dbm: float, bw_mhz: float = 0.45):
            nonlocal rf_spec
            if f_start <= freq_mhz <= f_stop and level_dbm > p.scanner_noise_floor_dbm:
                spur = (level_dbm - p.scanner_noise_floor_dbm) * np.exp(
                    -0.5 * ((rf_freqs - freq_mhz) / bw_mhz) ** 2
                )
                rf_spec = np.maximum(rf_spec, p.scanner_noise_floor_dbm + spur)

        inject_spur(lo_freq_mhz, received_lo_dbm, 0.35)
        inject_spur(p.tuned_rf_mhz, p.scanner_noise_floor_dbm + 6.0, 0.9)  # Ambient RX band activity
        inject_spur(lo_freq_mhz - if_eff * 2.0, received_lo_dbm - 26.0, 0.35)  # Image spur

        mitigations = []
        if p.lna_reverse_isolation_db < 35.0:
            mitigations.append("Insert high-reverse-isolation Ferrite Isolator or cascaded LNA stage at antenna port")
        if p.chassis_shielding_db < 40.0:
            mitigations.append("Upgrade enclosure to CNC-milled aluminum with conductive EMI seam gaskets")
        if p.sdr_architecture == "zero_if":
            mitigations.append("Zero-IF places f_LO directly on f_RF; use Low-IF/Superhet + steep RF preselector filter")

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "risk_level": risk_level,
            "detectable_by_sweep": detectable,
            "frequencies_mhz": {
                "tuned_rf_mhz": round(p.tuned_rf_mhz, 3),
                "if_freq_mhz": round(if_eff, 3),
                "lo_fundamental_mhz": round(lo_freq_mhz, 3),
                "lo_2nd_harmonic_mhz": round(lo_2x_mhz, 3),
                "lo_3rd_harmonic_mhz": round(lo_3x_mhz, 3),
                "wavelength_m": round(wavelength_m, 3),
                "reactive_nearfield_m": round(near_field_boundary_m, 3),
            },
            "leakage_budget": {
                "port_conducted_dbm": round(port_leakage_dbm, 2),
                "chassis_radiated_dbm": round(chassis_leakage_dbm, 2),
                "total_effective_eirp_dbm": round(total_eirp_dbm, 2),
                "received_at_scanner_dbm": round(received_lo_dbm, 2),
                "scanner_snr_db": round(snr_at_scanner_db, 2),
                "localization_cep_m": round(cep_m, 3),
            },
            "spatial_heatmap": {
                "coords_m": np.round(grid_coords, 2).tolist(),
                "rssi_dbm": heatmap,
            },
            "rf_spectrum": {
                "freqs_mhz": np.round(rf_freqs, 2).tolist(),
                "power_dbm": np.round(rf_spec, 2).tolist(),
            },
            "mitigations": mitigations,
            "params": asdict(p),
        }


# =============================================================================
# 3. ACOUSTIC SPEAKER COIL MICROPHONICS (TRANSDUCER REVERSIBILITY) ENGINE
# =============================================================================

@dataclass
class SpeakerMicrophonicsParams:
    transducer_type: str = "dynamic_voice_coil"  # "dynamic_voice_coil" | "parametric_piezo_array"
    num_array_elements: int = 8                  # Number of wired transducers in space
    bl_force_factor_tm: float = 6.8              # Magnetic B*l product (Tesla-meters)
    cone_area_cm2: float = 135.0                 # Effective diaphragm area Sd
    moving_mass_g: float = 11.5                  # Mms (grams)
    resonance_freq_hz: float = 92.0              # Mechanical resonance Fs (Hz)
    mechanical_qms: float = 4.2                  # Mechanical Q factor at resonance
    coil_dc_resistance_ohm: float = 6.4          # Re (Ohms)
    amp_output_impedance_ohm: float = 0.08       # Powered Class-AB/D Z_out (or high-Z standby)
    amp_powered_state: str = "active_powered"    # "active_powered" | "standby_relay_open" | "unpowered_wired"
    cable_length_m: float = 4.5                  # Speaker wire length
    # External observer acoustic impulse / vibration probe
    impulse_spl_db: float = 94.0                 # Injected acoustic impulse or chirp SPL
    impulse_center_hz: float = 95.0              # Targeted vibration frequency
    line_probe_noise_uv: float = 2.5             # Differential current/voltage probe floor (uV)


class SpeakerMicrophonicsAnalyzer:
    """
    Models reverse electromagnetic induction (V_emf = B * l * v_cone) when external
    sound waves or vibrations excite output speakers, leaking micro-volt signals
    onto speaker cables and amplifier feedback / power rails.
    """

    def compute_model(self, p: SpeakerMicrophonicsParams) -> Dict:
        p_ref = 20e-6
        incident_pa = p_ref * (10.0 ** (p.impulse_spl_db / 20.0))
        sd_m2 = p.cone_area_cm2 * 1e-4
        mms_kg = p.moving_mass_g * 1e-3
        fs = max(15.0, p.resonance_freq_hz)
        omega_0 = 2.0 * math.pi * fs
        omega = 2.0 * math.pi * max(10.0, p.impulse_center_hz)

        # Mechanical impedance Zm(omega) = Rms + j*(omega*Mms - Kms/omega)
        rms_mech = (omega_0 * mms_kg) / max(p.mechanical_qms, 0.2)
        kms = (omega_0 ** 2) * mms_kg

        # Electrical load impedance seen looking back into amplifier + cable
        r_cable = p.cable_length_m * 0.022  # ~16 AWG loop resistance
        if p.amp_powered_state == "standby_relay_open":
            z_load = 10000.0  # Open relay / bleed resistor
        elif p.amp_powered_state == "unpowered_wired":
            z_load = 47.0 + r_cable
        else:
            z_load = p.amp_output_impedance_ohm + r_cable

        # Electromagnetic damping reflected into mechanical domain: Bl^2 / (Re + Z_load)
        if p.transducer_type == "parametric_piezo_array":
            bl_eff = p.bl_force_factor_tm * 0.28
            sd_eff = sd_m2 * 0.18 * math.sqrt(max(1, p.num_array_elements))
        else:
            bl_eff = p.bl_force_factor_tm * math.sqrt(max(1, p.num_array_elements) * 0.45)
            sd_eff = sd_m2

        r_total_elec = p.coil_dc_resistance_ohm + z_load
        em_damping = (bl_eff ** 2) / max(r_total_elec, 0.1)

        reactance_mech = omega * mms_kg - (kms / omega)
        z_mech_mag = math.hypot(rms_mech + em_damping, reactance_mech)

        # Acoustic force F = P_incident * Sd -> Cone peak velocity v = F / |Z_mech|
        acoustic_force_n = incident_pa * sd_eff
        cone_velocity_ms = acoustic_force_n / max(z_mech_mag, 1e-6)
        cone_displacement_um = (cone_velocity_ms / omega) * 1e6

        # Open-circuit Faraday back-EMF: V_emf = B * l * v_cone
        open_circuit_emf_uv = bl_eff * cone_velocity_ms * 1e6

        # Terminal voltage developed across amplifier / cable node & loop current
        terminal_voltage_uv = open_circuit_emf_uv * (z_load / r_total_elec)
        back_current_ua = (open_circuit_emf_uv / r_total_elec)  # micro-amps

        # Power-supply rail modulation coupling (via Class-AB/D output stage body diodes / feedback)
        psrr_coupling = 0.08 if p.amp_powered_state == "active_powered" else 0.015
        power_line_ripple_uv = open_circuit_emf_uv * psrr_coupling

        # Detection metric against line probe noise floor
        effective_sensed_uv = max(terminal_voltage_uv, back_current_ua * 0.85)
        probe_snr_db = 20.0 * math.log10(max(effective_sensed_uv, 1e-4) / max(p.line_probe_noise_uv, 0.1))
        damping_factor = p.coil_dc_resistance_ohm / max(z_load, 0.005)

        array_verified = probe_snr_db > 6.0
        if probe_snr_db >= 20.0:
            status = "ARRAY_SIGNATURE_EXPOSED"
        elif probe_snr_db >= 6.0:
            status = "MICROPHONIC_PULSE_DETECTABLE"
        else:
            status = "DAMPED_BELOW_THRESHOLD"

        # Synthesize 80 ms transient back-EMF ringdown waveform (160 samples)
        t_ms = np.linspace(0.0, 80.0, 160)
        t_s = t_ms / 1000.0
        decay_tau = (2.0 * mms_kg) / max(rms_mech + em_damping, 1e-4)
        decay_tau = float(np.clip(decay_tau, 0.004, 0.045))
        envelope = np.where(t_s >= 0.006, np.exp(-(t_s - 0.006) / decay_tau), 0.0)
        rng = np.random.default_rng(int(time.time() * 9) % 100000)
        ring_freq = fs if abs(p.impulse_center_hz - fs) < 35.0 else p.impulse_center_hz
        waveform_uv = (
            effective_sensed_uv * envelope * np.sin(2.0 * math.pi * ring_freq * (t_s - 0.006))
            + rng.normal(0.0, p.line_probe_noise_uv * 0.35, size=160)
        )

        # Mechanical transfer curve across 20 Hz - 1000 Hz
        sweep_hz = np.geomspace(20.0, 1000.0, 80)
        resp_uv = []
        for f_test in sweep_hz:
            w = 2.0 * math.pi * f_test
            xm = w * mms_kg - (kms / w)
            zm = math.hypot(rms_mech + em_damping, xm)
            v_test = (incident_pa * sd_eff) / max(zm, 1e-6)
            emf_t = bl_eff * v_test * 1e6
            resp_uv.append(round(emf_t, 2))

        mitigations = [
            "Install common-mode toroidal EMI chokes & LC low-pass filters on speaker leads",
            "Use optical/galvanically isolated power supplies for active ultrasonic emitter stages",
            "Short unused voice coils via low-Ron MOSFET crowbar switch during silent intervals",
        ]

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": status,
            "transducer_verified_by_observer": array_verified,
            "electromechanical_metrics": {
                "open_circuit_back_emf_uv": round(open_circuit_emf_uv, 2),
                "cable_terminal_voltage_uv": round(terminal_voltage_uv, 2),
                "reverse_coil_current_ua": round(back_current_ua, 2),
                "power_rail_modulation_uv": round(power_line_ripple_uv, 2),
                "cone_peak_velocity_mms": round(cone_velocity_ms * 1000.0, 4),
                "cone_displacement_um": round(cone_displacement_um, 3),
                "damping_factor": round(damping_factor, 1),
                "probe_snr_db": round(probe_snr_db, 2),
                "ringdown_tau_ms": round(decay_tau * 1000.0, 2),
            },
            "transient_waveform": {
                "time_ms": np.round(t_ms, 2).tolist(),
                "voltage_uv": np.round(waveform_uv, 2).tolist(),
            },
            "frequency_sensitivity": {
                "freqs_hz": np.round(sweep_hz, 1).tolist(),
                "open_emf_uv": resp_uv,
            },
            "mitigations": mitigations,
            "params": asdict(p),
        }


class ReversePhysicsCoordinator:
    """Unified coordinator for all three bidirectional interaction models."""

    def __init__(self):
        self.retro_params = RetroIntermodParams()
        self.lo_params = LOLeakageParams()
        self.micro_params = SpeakerMicrophonicsParams()

        self.retro_engine = RetroreflectionIntermodAnalyzer()
        self.lo_engine = LOLeakageAnalyzer()
        self.micro_engine = SpeakerMicrophonicsAnalyzer()

    def snapshot_all(self) -> Dict:
        return {
            "retro_intermod": self.retro_engine.compute_physics_model(self.retro_params),
            "lo_leakage": self.lo_engine.compute_model(self.lo_params),
            "speaker_microphonics": self.micro_engine.compute_model(self.micro_params),
        }


if __name__ == "__main__":
    coord = ReversePhysicsCoordinator()
    snap = coord.snapshot_all()
    print("1. Retro/Intermod:", snap["retro_intermod"]["regime"], "f_diff=", snap["retro_intermod"]["frequencies_hz"]["f_diff_heterodyne"], "Hz")
    print("2. LO Leakage:", snap["lo_leakage"]["risk_level"], "f_LO=", snap["lo_leakage"]["frequencies_mhz"]["lo_fundamental_mhz"], "MHz")
    print("3. Microphonics:", snap["speaker_microphonics"]["status"], "Back-EMF=", snap["speaker_microphonics"]["electromechanical_metrics"]["open_circuit_back_emf_uv"], "uV")
