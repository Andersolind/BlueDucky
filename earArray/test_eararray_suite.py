#!/usr/bin/env python3
"""
EarArray End-to-End Physics, Spatial TOF Calibration, Pluto Neural Bridge & API Test Suite
==========================================================================================
Validates:
1. Multi-Node Ultrasonic TOF Self-Calibration (`execute_hardware_self_calibration`) &
   10m x 10m Spatial Trajectory Quadrant Overlay (`compute_spatial_trajectory_overlay`).
2. Acoustic Retroreflection & Parametric Westervelt Intermodulation (`retroreflection_intermod.py`).
3. Receive-Only SDR Local Oscillator (LO) Leakage & Speaker Coil Microphonics (`reverse_physics_suite.py`).
4. Pilot-Tone IQ Vibrometry & Delay-and-Sum + Binaural HRTF Beamforming (`sensing_and_beamforming.py`).
5. ADALM-Pluto Neural Adaptive Bridge, Softmax ANN, REAPER OSC & Breath-to-Morse (`pluto_neural_bridge.py`).
6. FastAPI & WebSocket Telemetry Server + Ollama `eararray-sigint` Modelfile & Diagnostics (`backend/server.py`).
"""

import unittest
from fastapi.testclient import TestClient

from spatial_tof_calibration import (
    execute_hardware_self_calibration,
    compute_spatial_trajectory_overlay,
    SpatialTofCalibrationEngine,
)
from retroreflection_intermod import RetroIntermodParams, RetroreflectionIntermodAnalyzer
from reverse_physics_suite import (
    LOLeakageParams,
    LOLeakageAnalyzer,
    SpeakerMicrophonicsParams,
    SpeakerMicrophonicsAnalyzer,
)
from sensing_and_beamforming import (
    PilotSensingParams,
    PilotTonePhaseDemodulator,
    BeamformingHRTFParams,
    SpatialBeamformingCore,
)
from pluto_neural_bridge import PlutoBridgeConfig, PlutoNeuralAdaptiveBridge
from midair_subvocal_pluto_learner import (
    MidAirSubvocalConfig,
    MidAirSubvocalPlutoLearner,
    SUBVOCAL_CLASSES,
)
from audible_enclave_prototype import (
    AudibleEnclaveConfig,
    AudibleEnclaveEngine,
    ENCLAVE_MODES,
)
from backend.server import app


class TestEarArraySuite(unittest.TestCase):
    def test_spatial_tof_self_calibration_and_quadrants(self):
        # 1. Baseline 10m x 10m chime (~0.0291545 s @ 343 m/s)
        geom = execute_hardware_self_calibration(10.0 / 343.0, 10.0 / 343.0)
        self.assertAlmostEqual(float(geom["NODE_1"][0]), 0.0, places=2)
        self.assertAlmostEqual(float(geom["NODE_1"][1]), 10.0, places=2)
        self.assertAlmostEqual(float(geom["NODE_2"][1]), 0.0, places=1)
        self.assertAlmostEqual(float(geom["NODE_3"][0]), 10.0, places=1)

        # 2. Shifted node calibration (tof_12 = 0.020 s -> 6.86 m, tof_13 = 0.025 s -> 8.575 m)
        eng = SpatialTofCalibrationEngine()
        snap = eng.recalibrate(0.020, 0.025)
        self.assertAlmostEqual(snap["calibrated_baselines_m"]["dist_12_m"], 6.86, places=1)
        self.assertAlmostEqual(snap["calibrated_baselines_m"]["dist_13_m"], 8.58, places=1)
        self.assertGreater(snap["calibrated_baselines_m"]["area_m2"], 25.0)
        self.assertGreaterEqual(len(snap["calibration_logs"]), 2)

        # 3. Verify all four 10m x 10m room architectural quadrants
        ne = compute_spatial_trajectory_overlay(7.5, 8.0)
        nw = compute_spatial_trajectory_overlay(2.5, 8.0)
        se = compute_spatial_trajectory_overlay(7.5, 2.0)
        sw = compute_spatial_trajectory_overlay(2.5, 2.0)

        self.assertIn("NORTHEAST_QUADRANT", ne["zone_descriptor"])
        self.assertEqual(ne["x_map_pct"], "75.0%")
        self.assertEqual(ne["y_map_pct"], "80.0%")
        self.assertIn("NORTHWEST_QUADRANT", nw["zone_descriptor"])
        self.assertIn("SOUTHEAST_QUADRANT", se["zone_descriptor"])
        self.assertIn("SOUTHWEST_QUADRANT", sw["zone_descriptor"])

    def test_retroreflection_and_reverse_physics(self):
        retro = RetroreflectionIntermodAnalyzer().compute_physics_model(RetroIntermodParams())
        self.assertEqual(retro["frequencies_hz"]["f_diff_heterodyne"], 1000.0)
        self.assertIn("intermodulation_metrics", retro)

        lo = LOLeakageAnalyzer().compute_model(LOLeakageParams())
        self.assertGreater(lo["frequencies_mhz"]["lo_fundamental_mhz"], 400.0)
        self.assertIn("received_at_scanner_dbm", lo["leakage_budget"])

        micro = SpeakerMicrophonicsAnalyzer().compute_model(SpeakerMicrophonicsParams())
        self.assertGreater(micro["electromechanical_metrics"]["open_circuit_back_emf_uv"], 0.0)

    def test_pilot_sensing_and_hrtf_beamforming(self):
        pilot = PilotTonePhaseDemodulator().compute_telemetry(PilotSensingParams())
        self.assertGreater(pilot["metrics"]["peak_displacement_um"], 0.0)

        beam = SpatialBeamformingCore().compute_telemetry(BeamformingHRTFParams())
        self.assertEqual(len(beam["delay_and_sum"]["polar_angles_deg"]), 181)
        self.assertIn("itd_us", beam["binaural_hrtf"])

    def test_pluto_neural_adaptive_bridge(self):
        bridge = PlutoNeuralAdaptiveBridge(PlutoBridgeConfig(), connect_hw=False)
        bridge.push_breath_token("INHALE")
        bridge.push_breath_token("INHALE")
        res = bridge.push_breath_token("EXHALE")
        self.assertEqual(res["biomacro_morse"]["last_dispatched_morse"], "CQ")

    def test_zero_equipment_midair_subvocal_pluto_self_learner(self):
        learner = MidAirSubvocalPlutoLearner(MidAirSubvocalConfig())
        snap = learner.run_self_learning_epoch(steps=18)

        # Verify pure mid-air 20 kHz phase demodulation & <= 28 dB SPL subvocal ceiling
        self.assertEqual(snap["midair_acoustics"]["pilot_freq_hz"], 20000.0)
        self.assertLessEqual(snap["midair_acoustics"]["audible_spl_db"], 28.0)
        self.assertGreater(snap["midair_acoustics"]["lms_clutter_suppression_db"], 6.0)
        self.assertGreater(snap["midair_acoustics"]["skin_displacement_um"], 5.0)

        # Verify autonomous self-supervised updates & 6-class probabilities
        self.assertGreaterEqual(snap["self_learning"]["self_supervised_updates"], 10)
        self.assertEqual(len(snap["self_learning"]["class_probabilities"]), len(SUBVOCAL_CLASSES))

        # Verify 3-token subvocal phrase injection -> PlutoSDR NBFM synthesis
        inj = learner.inject_subvocal_utterance("ALPHA_LOCK")
        self.assertEqual(inj["pluto_sdr"]["last_transmitted_phrase"], "ALPHA_LOCK")
        self.assertEqual(len(inj["pluto_sdr"]["iq_constellation_preview"]), 24)

    def test_self_bending_ultrasonic_audible_enclave_prototype(self):
        eng = AudibleEnclaveEngine(AudibleEnclaveConfig())
        snap = eng.compute_telemetry()

        # Verify inaudible ultrasonic carriers (40 kHz & 39 kHz) -> 1000 Hz audible enclave beat
        self.assertEqual(snap["frequencies_hz"]["f1_ultrasonic_hz"], 40000.0)
        self.assertEqual(snap["frequencies_hz"]["f2_ultrasonic_hz"], 39000.0)
        self.assertEqual(snap["frequencies_hz"]["audible_enclave_beat_hz"], 1000.0)
        self.assertTrue(snap["frequencies_hz"]["carriers_inaudible"])
        self.assertTrue(snap["frequencies_hz"]["enclave_in_human_band"])

        # Verify obstacle bypass and high privacy isolation (> 30 dB between enclave & bystander)
        self.assertTrue(snap["obstacle_bypass"]["self_bending_bypasses_obstacle"])
        self.assertTrue(snap["obstacle_bypass"]["conventional_straight_beam_blocked"])
        self.assertGreater(snap["enclave_metrics"]["peak_enclave_spl_db"], 55.0)
        self.assertGreater(snap["enclave_metrics"]["privacy_isolation_db"], 30.0)
        self.assertEqual(len(snap["ultrabroadband_octaves"]["octave_freqs_hz"]), 6)
        self.assertEqual(snap["metasurface"]["num_channels"], 32)

        # Verify Active Noise Cancellation (ANC) destructive phase nulling
        anc_snap = eng.compute_telemetry(
            AudibleEnclaveConfig(mode="ACTIVE_NOISE_CANCEL", anc_phase_align_deg=180.0)
        )
        self.assertTrue(anc_snap["active_noise_cancellation"]["enabled"])
        self.assertGreater(anc_snap["active_noise_cancellation"]["anc_suppression_db"], 6.0)

        # Verify all 7 Tactical Audio Stack capabilities
        ts = snap["tactical_stack"]

        # (1) 20 kHz Non-Contact Vocal Reconstruction & (3) Adaptive LMS Echo Cancellation
        voc = ts["non_contact_vocal_lms"]
        self.assertEqual(voc["sonar_carrier_hz"], 20000.0)
        self.assertGreater(voc["throat_displacement_mm"], 0.05)
        self.assertGreater(voc["lms_echo_canceller"]["erle_suppression_db"], 15.0)

        # (2) Dynamic Anti-Intercept Shielding (GPS-UTC 100m Grid Square FHSS)
        fhss = ts["fhss_anti_intercept"]
        self.assertTrue(fhss["fhss_enabled"])
        self.assertTrue(fhss["observer_inside_100m_grid"])
        self.assertEqual(len(fhss["hop_sequence_preview_hz"]), 16)
        out_snap = eng.compute_telemetry(
            AudibleEnclaveConfig(observer_lat_deg=40.7980, observer_lon_deg=-77.8650)
        )
        self.assertFalse(out_snap["tactical_stack"]["fhss_anti_intercept"]["observer_inside_100m_grid"])
        self.assertGreaterEqual(
            out_snap["tactical_stack"]["fhss_anti_intercept"]["outside_spectral_flatness"], 0.88
        )

        # (4) Cognitive Loop Delivery (250 Hz / 261 Hz -> 11.0 Hz Alpha Binaural Monologue)
        cog = ts["cognitive_loop_binaural"]
        self.assertEqual(cog["left_ear_carrier_hz"], 250.0)
        self.assertEqual(cog["right_ear_carrier_hz"], 261.0)
        self.assertEqual(cog["binaural_beat_hz"], 11.0)
        self.assertIn("ALPHA", cog["neural_band"])

        # (5) Headphone-Free Spatial Targeting (Living-Room Wall-Bounce TOF Convergence)
        wb = ts["wall_bounce_targeting"]
        self.assertEqual(wb["target_phase_alignment_skew_ms"], 0.0)
        self.assertGreater(wb["couch_bystander_skew_ms"], 1.0)
        self.assertEqual(wb["couch_bystander_status"], "DISJOINTED_MULTIPATH_SCRAMBLED")
        self.assertEqual(len(wb["multipath_streams"]), 4)

        # (6) Wideband Signal Interception (0-24,000 Hz Parallel Goertzel Decoder)
        gz_dtmf = eng.decode_wideband_goertzel("KEYPAD_BURST")
        self.assertEqual(gz_dtmf["nyquist_limit_hz"], 24000)
        self.assertEqual("".join(gz_dtmf["decoded_symbols"]), "*9142#")
        gz_fax = eng.decode_wideband_goertzel("FAX_HANDSHAKE")
        self.assertIn("FAX_T30_CED_2100HZ", gz_fax["decoded_plain_text"])

        # (7) Spatial-Temporal Database Journaling (SQLite Priority Write Gate)
        move_snap = eng.compute_telemetry(
            AudibleEnclaveConfig(target_x_m=0.28, target_z_m=1.05, active_intercept_preset="FAX_HANDSHAKE")
        )
        db_info = move_snap["tactical_stack"]["sqlite_spatial_journal"]
        self.assertTrue(db_info["wrote_on_this_frame"])
        self.assertGreaterEqual(db_info["total_committed_rows"], 1)
        self.assertGreaterEqual(len(db_info["recent_events"]), 1)

    def test_fastapi_endpoints_and_ollama_advise(self):
        client = TestClient(app)
        mods = client.get("/api/modules").json()
        self.assertGreaterEqual(len(mods["modules"]), 13)

        tof_res = client.post("/api/spatial-tof/calibrate", json={"tof_12": 0.022, "tof_13": 0.026}).json()
        self.assertIn("node_geometry", tof_res)
        self.assertIn("calibration_logs", tof_res)

        traj_res = client.post(
            "/api/spatial-tof/trajectory",
            json={"x_coord": 8.2, "y_coord": 1.8, "auto_orbit_target": False},
        ).json()
        self.assertIn("SOUTHEAST_QUADRANT", traj_res["current_overlay"]["zone_descriptor"])

        sv_step = client.post("/api/subvocal-learner/step", json={"epochs": 10}).json()
        self.assertEqual(sv_step["mode"], "ZERO_EQUIPMENT_MIDAIR_SUBVOCAL_PLUTO")
        self.assertEqual(sv_step["ollama_model"], "andersolind/nightsweep-sigint")

        sv_inj = client.post("/api/subvocal-learner/inject", json={"token": "PHASE_NULL"}).json()
        self.assertEqual(sv_inj["pluto_sdr"]["last_transmitted_phrase"], "PHASE_NULL")

        mf = client.get("/api/modelfile").json()
        self.assertTrue(mf["exists"])
        self.assertEqual(mf["primary_model"], "andersolind/nightsweep-sigint")
        self.assertIn("andersolind/nightsweep-sigint", mf["content"])

        ol_st = client.get("/api/ollama/status").json()
        self.assertIn("online", ol_st)

        adv = client.post("/api/subvocal-learner/ollama-advise", json={"model": "andersolind/nightsweep-sigint"}).json()
        self.assertTrue(adv["ok"])
        self.assertTrue(len(adv["response"]) > 40)

        # Verify Self-Bending Audible Enclave REST API & WAV synthesis endpoints
        enc_get = client.get("/api/enclave").json()
        self.assertEqual(enc_get["frequencies_hz"]["audible_enclave_beat_hz"], 1000.0)

        enc_cfg = client.post(
            "/api/enclave/config",
            json={"mode": "MULTI_TRACK_CROWD", "f1_carrier_hz": 40000.0, "f2_carrier_hz": 38800.0},
        ).json()
        self.assertEqual(enc_cfg["mode"], "MULTI_TRACK_CROWD")
        self.assertEqual(enc_cfg["frequencies_hz"]["audible_enclave_beat_hz"], 1200.0)

        enc_wav = client.post("/api/enclave/export-wav", json={"duration_s": 0.5}).json()
        self.assertTrue(enc_wav["ok"])
        self.assertTrue(enc_wav["ultrasonic_wav"].endswith("enclave_ultrasonic_carriers_192k.wav"))
        self.assertTrue(enc_wav["audible_comparison_wav"].endswith("enclave_audible_comparison_48k.wav"))
        self.assertTrue(enc_wav["binaural_alpha_wav"].endswith("cognitive_binaural_alpha_48k.wav"))

        enc_int = client.post("/api/enclave/intercept", json={"preset": "FAX_HANDSHAKE"}).json()
        self.assertIn(
            "FAX_T30_CED_2100HZ",
            enc_int["tactical_stack"]["wideband_goertzel_intercept"]["decoded_plain_text"],
        )

        enc_j = client.get("/api/enclave/journal").json()
        self.assertGreaterEqual(enc_j["total_committed_rows"], 1)


if __name__ == "__main__":
    unittest.main()
