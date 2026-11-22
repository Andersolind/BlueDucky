import { reactive, ref } from 'vue'

const wsConnected = ref(false)
const audioPreviewMode = ref(null) // null | 'heterodyne' | 'hrtf'

let audioCtx = null
let activeOsc = null
let activeOscRight = null
let activePanner = null
let activeGain = null

const telemetry = reactive({
  tick: 0,
  timestamp: '00:00:00',
  ear_defence: {
    status: 'ANOMALY_CONFIRMED',
    direction: 'Right',
    svm_confidence: 0.87,
    left_power: 0.48,
    right_power: 0.94,
    range_bp: 0.49,
    imbalance_ratio: 1.96,
    correlation: 0.34,
    spectral_flatness: 0.08,
    temporal_consistency: '4/5 windows',
    baseline_calibrated: true,
  },
  replay_detector: {
    confidence: 0.82,
    carrier_hz: 20000,
    modulation_depth: 0.24,
    thd_ratio: 0.072,
    verdict: 'SYNTHETIC_MODULATED_CARRIER',
  },
  vehicle_ble: {
    devices: [],
    parking_sensor_40_48khz: true,
    subaru_harman_576w_ready: true,
    speaker_resonances_db: { subwoofer: 24.2, door_woofer: 19.6, dash_tweeter: 28.4 },
  },
  cross_layer: {
    gesture: 'talking',
    csi_subcarriers_64: Array.from({ length: 64 }, (_, i) => 1 + 0.15 * Math.sin(i * 0.2)),
    csi_motion: 0.142,
    csi_rate_hz: 48.5,
    doa_deg: 11.2,
    tdoa_us: 45.1,
    doa_conf: 0.86,
    voice_ratio: 0.68,
    hf_z: 7.4,
    sub_5hz_presence: true,
    fp_hash: 'a94c110fe8203d1b',
    bands_16: Array.from({ length: 16 }, () => 0.0625),
    active_rules: ['voice_present', 'hf_appears', 'ble_close_hf', 'heterodyne_midair_beat'],
  },
  retro_intermod: {
    regime: 'ACTIVE_HETERODYNE_MIXING',
    active_detection_confidence: 0.96,
    indicators: [
      'Opposing 19 kHz pilot colliding with 20 kHz sonar -> 1000 Hz audible mid-air tone',
      'Quadratic phase coupling bicoherence = 0.86',
    ],
    frequencies_hz: {
      f1_sonar: 20000,
      f2_transceiver: 19000,
      f_diff_heterodyne: 1000,
      f_sum: 39000,
      f_imd3_low: 18000,
      f_imd3_high: 21000,
      is_audible_heterodyne: true,
    },
    passive_zones: {
      clothing: { spl_db: 63.6, absorption: 0.38, scatter_coeff: 0.24, character: 'Diffuse porous scatter' },
      body_torso: { spl_db: 75.4, respiration_hz: 0.28, heart_rate_hz: 1.22, character: 'Specular cardiopulmonary micro-Doppler' },
      throat_vocal: { spl_db: 65.9, fundamental_hz: 145, modulation_index: 0.08, character: 'Laryngeal vibrometry sidebands' },
      combined_passive_spl_db: 76.2,
    },
    intermodulation_metrics: {
      transceiver_rx_spl_db: 91.2,
      heterodyne_diff_spl_db: 48.5,
      sum_freq_spl_db: 29.1,
      imd3_spl_db: 36.4,
      effective_reflection_gamma: 2.84,
      bicoherence: 0.86,
      acoustic_tof_ms: 12.24,
      total_loop_delay_ms: 12.66,
      observer_doa_deg: 18.0,
      virtual_midair_doa_deg: 11.2,
    },
    spectrum: { freqs_hz: [], power_db: [] },
    params: {
      sonar_freq_hz: 20000,
      sonar_spl_db: 102,
      observer_distance_m: 2.1,
      observer_azimuth_deg: 18,
      clothing_absorption: 0.38,
      throat_vibration_hz: 145,
      active_transceiver_enabled: true,
      transceiver_freq_hz: 19000,
      transceiver_spl_db: 98,
      transceiver_gain_db: 14,
      electronic_delay_us: 420,
    },
  },
  lo_leakage: {
    risk_level: 'CRITICAL_PINPOINTABLE',
    detectable_by_sweep: true,
    frequencies_mhz: {
      tuned_rf_mhz: 433.92,
      if_freq_mhz: 21.4,
      lo_fundamental_mhz: 455.32,
      lo_2nd_harmonic_mhz: 910.64,
      lo_3rd_harmonic_mhz: 1365.96,
      wavelength_m: 0.658,
      reactive_nearfield_m: 0.105,
    },
    leakage_budget: {
      port_conducted_dbm: -75.0,
      chassis_radiated_dbm: -49.0,
      total_effective_eirp_dbm: -48.99,
      received_at_scanner_dbm: -68.7,
      scanner_snr_db: 49.3,
      localization_cep_m: 0.04,
    },
    spatial_heatmap: { coords_m: [], rssi_dbm: [] },
    rf_spectrum: { freqs_mhz: [], power_dbm: [] },
    mitigations: [],
    params: {
      sdr_architecture: 'superhet',
      tuned_rf_mhz: 433.92,
      if_freq_mhz: 21.4,
      lna_reverse_isolation_db: 28,
      chassis_shielding_db: 24,
      scanner_distance_m: 1.8,
      scanner_azimuth_deg: -35,
      scanner_antenna_gain_dbi: 11,
    },
  },
  speaker_microphonics: {
    status: 'ARRAY_SIGNATURE_EXPOSED',
    transducer_verified_by_observer: true,
    electromechanical_metrics: {
      open_circuit_back_emf_uv: 6493.2,
      cable_terminal_voltage_uv: 180.4,
      reverse_coil_current_ua: 986.5,
      power_rail_modulation_uv: 519.4,
      cone_peak_velocity_mms: 0.45,
      cone_displacement_um: 0.76,
      damping_factor: 35.7,
      probe_snr_db: 51.9,
      ringdown_tau_ms: 14.2,
    },
    transient_waveform: { time_ms: [], voltage_uv: [] },
    frequency_sensitivity: { freqs_hz: [], open_emf_uv: [] },
    mitigations: [],
    params: {
      transducer_type: 'dynamic_voice_coil',
      num_array_elements: 8,
      bl_force_factor_tm: 6.8,
      resonance_freq_hz: 92,
      amp_powered_state: 'active_powered',
      impulse_spl_db: 94,
      impulse_center_hz: 95,
    },
  },
  pilot_sensing: {
    mode: 'NON_CONTACT_PILOT_IQ',
    metrics: {
      pilot_wavelength_mm: 14.29,
      phase_sensitivity_rad_mm: 0.879,
      max_phase_rad: 0.18,
      peak_displacement_um: 422.0,
      tracking_rms_error_um: 8.4,
      coherence_quality: 0.96,
    },
    waveform: { time_ms: [], displacement_um: [], phase_rad: [] },
    iq_constellation: [],
    params: {
      pilot_freq_hz: 24000,
      target_range_m: 1.45,
      laryngeal_f0_hz: 132,
      laryngeal_disp_um: 42,
      gesture_disp_um: 380,
      snr_db: 28,
    },
  },
  beamforming_hrtf: {
    delay_and_sum: {
      num_mics: 8,
      steer_azimuth_deg: -24,
      beamwidth_3db_deg: 28,
      array_directivity_gain_db: 9.03,
      ambient_jammer_suppression_db: 24.6,
      element_delays_us: [],
      polar_angles_deg: [],
      polar_gain_db: [],
    },
    binaural_hrtf: {
      target_coord_m: { x: -1.15, y: 1.2, z: 2.4 },
      target_range_m: 2.66,
      target_azimuth_deg: -25.6,
      itd_us: -224.2,
      broadband_ild_db: -6.8,
      pinna_notch_hz: 7960,
      spatial_isolation_db: 21.3,
      voice_pitch_shift_st: -2.5,
      freqs_hz: [],
      ild_db: [],
      left_ear_tf_db: [],
      right_ear_tf_db: [],
    },
    params: {
      num_mics: 8,
      element_spacing_m: 0.042,
      center_freq_hz: 3200,
      steer_azimuth_deg: -24,
      null_jammer_deg: 42,
      window_taper: 'hamming',
      target_x_m: -1.15,
      target_y_m: 1.2,
      target_z_m: 2.4,
      voice_pitch_shift_st: -2.5,
    },
  },
  pluto_bridge: {
    hardware: {
      pluto_connected: false,
      jack_connected: false,
      mode: 'PLUTO_DIGITAL_TWIN',
      rx_freq_mhz: 144.3,
      tx_freq_mhz: 144.8,
      rf_sample_rate_msps: 2.0,
      squelch_open: true,
      rf_power_db: -48.2,
    },
    neural_net: {
      predicted_state: 'STANDING',
      confidence: 0.78,
      probabilities: { STABLE_IDLE: 0.06, SITTING: 0.16, STANDING: 0.52, ROOM_MOVEMENT: 0.26 },
      features: { rf_variance: 0.56, audio_rms_x100: 1.27, zero_crossings: 0.036 },
      weights: [],
      train_steps: 0,
    },
    automation_osc: {
      reaper_endpoint: '127.0.0.1:8000',
      jack_ports: ['sdr_demod_to_reaper', 'reaper_fx_to_sdr'],
      is_reaper_track_armed: true,
      is_rf_carrier_precharged: false,
      recent_osc_packets: [],
    },
    biomacro_morse: {
      breath_queue: [],
      predicted_macro_intent: 'NONE',
      last_dispatched_morse: '',
      last_morse_symbols: '',
    },
    earworm: { buffer_fill_s: 4.2, max_s: 10.0, saved_snapshots: [] },
    rf_history_db: [],
    params: {
      rx_freq: 144300000,
      tx_freq: 144800000,
      rx_gain: 45,
      tx_atten: 45,
      squelch_threshold_db: -55,
      learning_rate: 0.01,
      sim_rf_activity: 0.35,
      sim_audio_rms: 0.018,
    },
  },
  spatial_tof: {
    room_limits_m: { width: 10.0, height: 10.0, sound_speed_m_s: 343.0 },
    node_geometry: {
      NODE_1: [0.0, 10.0],
      NODE_2: [0.0, 0.0],
      NODE_3: [10.0, 0.0],
    },
    calibrated_baselines_m: { dist_12_m: 10.0, dist_13_m: 10.0, area_m2: 50.0 },
    target_ranges_m: { NODE_1: 7.36, NODE_2: 9.9, NODE_3: 7.88 },
    target_tofs_ms: { NODE_1: 21.46, NODE_2: 28.86, NODE_3: 22.97 },
    current_overlay: {
      x_coord_m: 6.8,
      y_coord_m: 7.2,
      x_map_pct: '68.0%',
      y_map_pct: '72.0%',
      zone_descriptor: 'NORTHEAST_QUADRANT (Living Room Window Path)',
      timestamp: '20:27:10',
    },
    calibration_logs: [],
    trajectory_trail: [],
    params: {
      tof_12_sec: 0.029155,
      tof_13_sec: 0.029155,
      target_x_m: 6.8,
      target_y_m: 7.2,
      auto_orbit_target: true,
    },
  },
  subvocal_learner: {
    mode: 'ZERO_EQUIPMENT_MIDAIR_SUBVOCAL_PLUTO',
    ollama_model: 'andersolind/nightsweep-sigint',
    midair_acoustics: {
      pilot_freq_hz: 20000.0,
      parametric_aux_freq_hz: 19000.0,
      heterodyne_beat_hz: 1000.0,
      wavelength_mm: 17.15,
      target_distance_m: 1.35,
      skin_displacement_um: 46.5,
      unwrapped_phase_rad: 0.034,
      audible_spl_db: 19.4,
      audible_spl_ceiling_db: 28.0,
      is_sublevel_silent: true,
      lms_taps: 32,
      lms_mu: 0.025,
      lms_clutter_suppression_db: 16.8,
      waveform_preview: [],
    },
    pluto_sdr: {
      hardware_mode: 'PURE_MIDAIR_DIGITAL_TWIN (Zero Physical Equipment)',
      rx_freq_mhz: 144.3,
      tx_freq_mhz: 144.8,
      sample_rate_msps: 2.0,
      nbfm_deviation_hz: 5000.0,
      cross_modal_coherence_gamma2: 0.88,
      coherence_gate_threshold: 0.62,
      coherence_locked: true,
      last_transmitted_phrase: 'SILENT_RELAY',
      iq_constellation_preview: [],
    },
    self_learning: {
      total_frames: 12,
      self_supervised_updates: 10,
      rejected_clutter_frames: 2,
      predicted_class: 'SUBVOCAL_VOWEL_GLIDE',
      confidence: 0.89,
      rolling_cross_entropy_loss: 0.19,
      self_convergence_accuracy_pct: 91.7,
      loss_history: [0.42, 0.36, 0.31, 0.27, 0.24, 0.21, 0.19],
      token_window: ['SUBVOCAL_NASAL_M_N', 'SUBVOCAL_VOWEL_GLIDE', 'SUBVOCAL_COMMAND_SYNC'],
      class_probabilities: {
        AMBIENT_SILENCE: 0.02,
        SUBVOCAL_PLOSIVE_P_T_K: 0.04,
        SUBVOCAL_NASAL_M_N: 0.06,
        SUBVOCAL_FRICATIVE_S_F: 0.03,
        SUBVOCAL_VOWEL_GLIDE: 0.79,
        SUBVOCAL_COMMAND_SYNC: 0.06,
      },
      feature_vector_6d: {
        rms_disp_norm: 0.64,
        dom_freq_norm: 0.38,
        zcr_env: 0.28,
        burst_dur_norm: 0.82,
        coherence_gamma2: 0.91,
        spectral_centroid_norm: 0.42,
      },
      recent_updates: [],
    },
    ollama_advisor: {
      configured_model: 'andersolind/nightsweep-sigint',
      cli_command: 'ollama run andersolind/nightsweep-sigint',
      last_model_used: 'andersolind/nightsweep-sigint',
      last_source: 'ready',
      last_advice: '',
    },
    params: {
      pilot_freq_hz: 20000.0,
      parametric_aux_freq_hz: 19000.0,
      lms_mu: 0.025,
      coherence_gate_threshold: 0.62,
      learning_rate: 0.045,
      auto_self_learn: true,
      ollama_model: 'andersolind/nightsweep-sigint',
    },
  },
  audible_enclave: {
    mode: 'PRIVATE_ENCLAVE',
    paper_reference: 'Zhong et al., PNAS (2025) - Audible enclaves crafted by nonlinear self-bending ultrasonic beams',
    frequencies_hz: {
      f1_ultrasonic_hz: 40000.0,
      f2_ultrasonic_hz: 39000.0,
      audible_enclave_beat_hz: 1000.0,
      sum_ultrasonic_hz: 79000.0,
      carriers_inaudible: true,
      enclave_in_human_band: true,
      secondary_enclave_beat_hz: null,
    },
    enclave_metrics: {
      peak_enclave_spl_db: 66.3,
      bystander_outside_spl_db: 22.0,
      beam_path_audible_leak_db: 22.8,
      beam_path_ultrasonic_spl_db: 104.2,
      privacy_isolation_db: 44.3,
      enclave_width_cm: 9.4,
      enclave_depth_cm: 10.8,
      target_coord_m: { x: 0.0, y: 1.2, z: 0.85 },
      secondary_coord_m: null,
    },
    obstacle_bypass: {
      obstacle_enabled: true,
      obstacle_x_m: 0.0,
      obstacle_z_m: 0.42,
      obstacle_radius_cm: 9.5,
      min_beam_clearance_cm: 7.93,
      self_bending_bypasses_obstacle: true,
      conventional_straight_beam_blocked: true,
    },
    active_noise_cancellation: {
      enabled: false,
      ambient_noise_spl_db: 61.5,
      phase_alignment_deg: 180.0,
      residual_enclave_spl_db: 61.5,
      anc_suppression_db: 0.0,
    },
    ultrabroadband_octaves: {
      octave_freqs_hz: [125, 250, 500, 1000, 2000, 4000],
      enclave_spl_db: [55.4, 58.9, 62.1, 65.1, 63.8, 56.2],
      bandwidth_label: '125 Hz - 4 kHz (6 Octaves)',
    },
    trajectories: {
      z_m: Array.from({ length: 32 }, (_, i) => +(i * 0.04).toFixed(3)),
      beam1_x_m: Array.from({ length: 32 }, (_, i) => {
        const u = (i * 0.04) / 0.85
        return +(-0.18 * (1 - u) - 0.087 * 4 * u * (1 - u)).toFixed(4)
      }),
      beam2_x_m: Array.from({ length: 32 }, (_, i) => {
        const u = (i * 0.04) / 0.85
        return +(0.18 * (1 - u) + 0.087 * 4 * u * (1 - u)).toFixed(4)
      }),
      straight_x_m: Array.from({ length: 32 }, () => 0.0),
      source1_x_m: -0.18,
      source2_x_m: 0.18,
    },
    spatial_field_2d: {
      nx: 36,
      nz: 36,
      x_grid_m: [],
      z_grid_m: [],
      audible_spl_db: [],
      ultrasonic_spl_db: [],
    },
    metasurface: {
      num_channels: 32,
      aperture_width_mm: 160.0,
      subwavelength_pitch_mm: 5.0,
      wavelength_f1_mm: 8.575,
      wavelength_f2_mm: 8.795,
      airy_scale_x0_mm: 52.17,
      x_Element_mm: [],
      phase_f1_rad: [],
      phase_f2_rad: [],
      channel_length_f1_mm: [],
      channel_length_f2_mm: [],
    },
    tactical_stack: {
      non_contact_vocal_lms: {
        sonar_carrier_hz: 20000.0,
        sonar_wavelength_mm: 17.15,
        throat_displacement_mm: 0.18,
        throat_displacement_um: 180.0,
        peak_phase_rad: 0.132,
        sensor_mode: 'NON_CONTACT_20KHZ_SONAR (Zero sEMG Electrodes)',
        reconstructed_f0_hz: 138.0,
        voice_changed_f0_hz: 119.4,
        lms_echo_canceller: {
          filter_taps: 32,
          step_size_mu: 0.032,
          tv_background_spl_db: 72.0,
          erle_suppression_db: 24.8,
          residual_clutter_spl_db: 47.2,
          vocal_reconstruction_fidelity: 0.986,
        },
        isolated_vocal_waveform: [],
      },
      fhss_anti_intercept: {
        fhss_enabled: true,
        grid_square_id: 'GRID100M_+45280_-65115',
        utc_epoch_slot: 4416200,
        hop_rate_hz: 25.0,
        num_hop_channels: 32,
        current_hop_freq_hz: 21460.0,
        hop_sequence_preview_hz: [21460, 19270, 23120, 20100, 22630, 18930, 21960, 20770],
        processing_gain_db: 15.05,
        observer_distance_m: 23.8,
        observer_inside_100m_grid: true,
        outside_grid_appearance: 'SYNCHRONIZED_DECODE_LOCKED',
        outside_spectral_flatness: 0.93,
        outside_intercept_snr_db: -11.4,
      },
      cognitive_loop_binaural: {
        left_ear_carrier_hz: 250.0,
        right_ear_carrier_hz: 261.0,
        binaural_beat_hz: 11.0,
        neural_band: 'ALPHA_CORTICAL_BAND (8-13 Hz Relaxed Focus / Internal Monologue)',
        cortical_target: 'Superior Olivary Complex -> Central Auditory Cortex',
        voice_pitch_shift_st: -2.5,
        alpha_envelope_preview: [],
      },
      wall_bounce_targeting: {
        room_dimensions_m: { width: 4.8, length: 5.6 },
        target_convergence_arrival_ms: 29.8,
        target_phase_alignment_skew_ms: 0.0,
        couch_bystander_offset_m: 0.65,
        couch_bystander_skew_ms: 3.68,
        couch_bystander_status: 'DISJOINTED_MULTIPATH_SCRAMBLED',
        multipath_streams: [
          { path_name: 'DIRECT_PATH', path_length_m: 0.85, raw_tof_ms: 2.478, pre_delay_compensation_ms: 27.32, arrival_at_target_ms: 29.8, arrival_at_couch_bystander_ms: 30.45 },
          { path_name: 'LEFT_WALL_BOUNCE', path_length_m: 4.875, raw_tof_ms: 14.213, pre_delay_compensation_ms: 15.59, arrival_at_target_ms: 29.8, arrival_at_couch_bystander_ms: 31.67 },
          { path_name: 'RIGHT_WALL_BOUNCE', path_length_m: 4.875, raw_tof_ms: 14.213, pre_delay_compensation_ms: 15.59, arrival_at_target_ms: 29.8, arrival_at_couch_bystander_ms: 27.99 },
          { path_name: 'REAR_WALL_BOUNCE', path_length_m: 10.35, raw_tof_ms: 30.175, pre_delay_compensation_ms: 0.0, arrival_at_target_ms: 29.8, arrival_at_couch_bystander_ms: 30.23 },
        ],
      },
      wideband_goertzel_intercept: {
        sample_rate_hz: 48000,
        nyquist_limit_hz: 24000,
        active_preset: 'KEYPAD_BURST',
        transmission_type: 'DTMF_KEYPAD_BURST',
        detected_tones_hz: [941.0, 1209.0],
        decoded_symbols: ['*', '9', '1', '4', '2', '#'],
        decoded_plain_text: 'KEYPAD_DTMF: *9142# [TACTICAL_DOOR_UNLOCK]',
        goertzel_filterbank_db: {},
      },
      sqlite_spatial_journal: {
        db_path: 'logs/tactical_spatial_journal.sqlite',
        wrote_on_this_frame: true,
        last_trigger_reason: 'INITIAL_OR_MANUAL_SNAPSHOT',
        priority_level: 'MEDIUM',
        spatial_delta_m: 0.0,
        movement_threshold_m: 0.12,
        total_committed_rows: 1,
        throttled_routine_ticks: 0,
        recent_events: [],
      },
    },
    params: {
      mode: 'PRIVATE_ENCLAVE',
      f1_carrier_hz: 40000.0,
      f2_carrier_hz: 39000.0,
      source_spl_db: 112.0,
      source_separation_m: 0.36,
      target_x_m: 0.0,
      target_y_m: 1.2,
      target_z_m: 0.85,
      bend_curvature: 0.92,
      beam_waist_m: 0.085,
      obstacle_enabled: true,
      obstacle_x_m: 0.0,
      obstacle_z_m: 0.42,
      obstacle_radius_m: 0.095,
      anc_ambient_spl_db: 61.5,
      anc_phase_align_deg: 180.0,
      secondary_target_x_m: 0.24,
      secondary_target_z_m: 0.92,
      secondary_beat_hz: 660.0,
      vocal_sonar_freq_hz: 20000.0,
      throat_disp_mm: 0.18,
      vocal_formant_f0_hz: 138.0,
      voice_pitch_shift_st: -2.5,
      fhss_enabled: true,
      gps_lat_deg: 40.7934,
      gps_lon_deg: -77.86,
      observer_lat_deg: 40.7936,
      observer_lon_deg: -77.8599,
      fhss_hop_rate_hz: 25.0,
      lms_taps: 32,
      lms_mu: 0.032,
      tv_noise_spl_db: 72.0,
      binaural_left_hz: 250.0,
      binaural_right_hz: 261.0,
      room_width_m: 4.8,
      room_length_m: 5.6,
      couch_bystander_offset_m: 0.65,
      active_intercept_preset: 'KEYPAD_BURST',
      journal_movement_threshold_m: 0.12,
    },
  },
})

let socket = null
let reconnectTimer = null

function connectWebSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${window.location.host}/ws/telemetry`
  try {
    socket = new WebSocket(url)
    socket.onopen = () => { wsConnected.value = true }
    socket.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        Object.assign(telemetry, data)
        syncWebAudioParams()
      } catch {}
    }
    socket.onclose = () => {
      wsConnected.value = false
      clearTimeout(reconnectTimer)
      reconnectTimer = setTimeout(connectWebSocket, 2000)
    }
  } catch {
    wsConnected.value = false
  }
}

async function postPhysicsUpdate(endpoint, payload) {
  try {
    const res = await fetch(`/api/physics/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const updated = await res.json()
      const mapKey = {
        retro: 'retro_intermod',
        lo: 'lo_leakage',
        microphonics: 'speaker_microphonics',
        pilot: 'pilot_sensing',
        beamforming: 'beamforming_hrtf',
      }[endpoint]
      if (mapKey) telemetry[mapKey] = updated
      syncWebAudioParams()
    }
  } catch {}
}

function stopAudioPreview() {
  if (activeOsc) {
    try { activeOsc.stop() } catch {}
    activeOsc.disconnect()
    activeOsc = null
  }
  if (activeOscRight) {
    try { activeOscRight.stop() } catch {}
    activeOscRight.disconnect()
    activeOscRight = null
  }
  activePanner = null
  activeGain = null
  audioPreviewMode.value = null
}

function toggleAudioPreview(mode) {
  if (audioPreviewMode.value === mode) {
    stopAudioPreview()
    return
  }
  stopAudioPreview()
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!audioCtx) audioCtx = new AudioContextClass()
  if (audioCtx.state === 'suspended') audioCtx.resume()

  activeOsc = audioCtx.createOscillator()
  activeGain = audioCtx.createGain()
  activeGain.gain.value = 0.12

  if (mode === 'heterodyne') {
    const fDiff = telemetry.retro_intermod.frequencies_hz.f_diff_heterodyne || 1000
    activeOsc.type = 'sine'
    activeOsc.frequency.value = Math.min(Math.max(fDiff, 80), 14000)
    activeOsc.connect(activeGain).connect(audioCtx.destination)
  } else if (mode === 'hrtf') {
    activePanner = audioCtx.createPanner()
    activePanner.panningModel = 'HRTF'
    activePanner.distanceModel = 'inverse'
    const c = telemetry.beamforming_hrtf.binaural_hrtf.target_coord_m
    activePanner.positionX.value = c.x
    activePanner.positionY.value = c.y - 1.2
    activePanner.positionZ.value = -c.z
    activeOsc.type = 'triangle'
    activeOsc.frequency.value = 260 * Math.pow(2, (telemetry.beamforming_hrtf.binaural_hrtf.voice_pitch_shift_st || 0) / 12)
    activeOsc.connect(activePanner).connect(activeGain).connect(audioCtx.destination)
  } else if (mode === 'enclave_inside' || mode === 'enclave_outside') {
    const fBeat = telemetry.audible_enclave?.frequencies_hz?.audible_enclave_beat_hz || 1000
    const isoDb = telemetry.audible_enclave?.enclave_metrics?.privacy_isolation_db || 36
    activeOsc.type = 'sine'
    activeOsc.frequency.value = Math.min(Math.max(fBeat, 100), 8000)
    activeGain.gain.value = mode === 'enclave_inside' ? 0.14 : Math.max(0.0015, 0.14 * Math.pow(10, -isoDb / 20))
    activeOsc.connect(activeGain).connect(audioCtx.destination)
  } else if (mode === 'binaural_alpha') {
    const cog = telemetry.audible_enclave?.tactical_stack?.cognitive_loop_binaural || {}
    const fLeft = cog.left_ear_carrier_hz || 250
    const fRight = cog.right_ear_carrier_hz || 261
    const merger = audioCtx.createChannelMerger(2)
    activeOsc.type = 'sine'
    activeOsc.frequency.value = fLeft
    activeOscRight = audioCtx.createOscillator()
    activeOscRight.type = 'sine'
    activeOscRight.frequency.value = fRight
    activeOsc.connect(merger, 0, 0)
    activeOscRight.connect(merger, 0, 1)
    merger.connect(activeGain).connect(audioCtx.destination)
    activeOscRight.start()
  }

  activeOsc.start()
  audioPreviewMode.value = mode
}

function syncWebAudioParams() {
  if (!activeOsc || !audioCtx) return
  if (audioPreviewMode.value === 'heterodyne') {
    const fDiff = telemetry.retro_intermod.frequencies_hz.f_diff_heterodyne || 1000
    activeOsc.frequency.setTargetAtTime(Math.min(Math.max(fDiff, 80), 14000), audioCtx.currentTime, 0.05)
  } else if (audioPreviewMode.value === 'hrtf' && activePanner) {
    const c = telemetry.beamforming_hrtf.binaural_hrtf.target_coord_m
    activePanner.positionX.setTargetAtTime(c.x, audioCtx.currentTime, 0.05)
    activePanner.positionY.setTargetAtTime(c.y - 1.2, audioCtx.currentTime, 0.05)
    activePanner.positionZ.setTargetAtTime(-c.z, audioCtx.currentTime, 0.05)
    const fVoice = 260 * Math.pow(2, (telemetry.beamforming_hrtf.binaural_hrtf.voice_pitch_shift_st || 0) / 12)
    activeOsc.frequency.setTargetAtTime(fVoice, audioCtx.currentTime, 0.05)
  }
}

function playMorseSidetone(symbols) {
  if (!symbols) return
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!audioCtx) audioCtx = new AudioContextClass()
  if (audioCtx.state === 'suspended') audioCtx.resume()

  let cursor = audioCtx.currentTime + 0.03
  const unit = 0.075
  for (const ch of symbols) {
    if (ch === '.' || ch === '-') {
      const dur = ch === '.' ? unit : unit * 3
      const osc = audioCtx.createOscillator()
      const g = audioCtx.createGain()
      osc.frequency.value = 680
      g.gain.setValueAtTime(0.11, cursor)
      g.gain.setValueAtTime(0.0001, cursor + dur)
      osc.connect(g).connect(audioCtx.destination)
      osc.start(cursor)
      osc.stop(cursor + dur + 0.01)
      cursor += dur + unit
    } else if (ch === ' ') {
      cursor += unit * 2
    }
  }
}

async function postPlutoAction(subpath, payload = {}) {
  try {
    const res = await fetch(`/api/pluto/${subpath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json()
      if (subpath !== 'earworm') {
        const prevMorse = telemetry.pluto_bridge?.biomacro_morse?.last_morse_symbols
        telemetry.pluto_bridge = data
        const nextMorse = data?.biomacro_morse?.last_morse_symbols
        if (nextMorse && (subpath === 'breath' && data?.biomacro_morse?.predicted_macro_intent?.startsWith('DISPATCH:'))) {
          playMorseSidetone(nextMorse)
        } else if (nextMorse && nextMorse !== prevMorse) {
          playMorseSidetone(nextMorse)
        }
      }
      return data
    }
  } catch {}
  return null
}

async function postSpatialTof(subpath, payload = {}) {
  try {
    const res = await fetch(`/api/spatial-tof/${subpath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json()
      telemetry.spatial_tof = data
      return data
    }
  } catch {}
  return null
}

async function postSubvocalLearner(subpath, payload = {}) {
  try {
    const res = await fetch(`/api/subvocal-learner/${subpath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.telemetry) {
        telemetry.subvocal_learner = data.telemetry
      } else {
        telemetry.subvocal_learner = data
      }
      return data
    }
  } catch {}
  return null
}

async function postAudibleEnclave(subpath = 'config', payload = {}) {
  try {
    const res = await fetch(`/api/enclave/${subpath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json()
      if (subpath === 'config' || subpath === 'intercept') {
        telemetry.audible_enclave = data
        syncWebAudioParams()
      }
      return data
    }
  } catch {}
  return null
}

export function useTelemetry() {
  return {
    telemetry,
    wsConnected,
    audioPreviewMode,
    connectWebSocket,
    postPhysicsUpdate,
    postPlutoAction,
    postSpatialTof,
    postSubvocalLearner,
    postAudibleEnclave,
    playMorseSidetone,
    toggleAudioPreview,
    stopAudioPreview,
  }
}
