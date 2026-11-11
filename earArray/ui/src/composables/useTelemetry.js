import { reactive, ref } from 'vue'

const wsConnected = ref(false)
const audioPreviewMode = ref(null) // null | 'heterodyne' | 'hrtf'

let audioCtx = null
let activeOsc = null
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

export function useTelemetry() {
  return {
    telemetry,
    wsConnected,
    audioPreviewMode,
    connectWebSocket,
    postPhysicsUpdate,
    postPlutoAction,
    playMorseSidetone,
    toggleAudioPreview,
    stopAudioPreview,
  }
}
