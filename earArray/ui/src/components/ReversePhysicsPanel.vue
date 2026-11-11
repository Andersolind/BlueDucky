<template>
  <div class="glass-panel p-box">
    <div class="sec-head">
      <div>
        <h3>Bidirectional & Reverse-Physics Mechanisms</h3>
        <p class="sub">Mid-Air Heterodyne Downconversion • Receive-Only SDR LO Leakage • Voice-Coil Back-EMF Microphonics</p>
      </div>
      <div class="tab-bar">
        <button class="btn" :class="{ 'btn-active': subTab === 'retro' }" @click="subTab = 'retro'">1. Retro & Intermod</button>
        <button class="btn" :class="{ 'btn-active': subTab === 'lo' }" @click="subTab = 'lo'">2. SDR LO Leakage</button>
        <button class="btn" :class="{ 'btn-active': subTab === 'coil' }" @click="subTab = 'coil'">3. Coil Microphonics</button>
      </div>
    </div>

    <!-- 1. ACOUSTIC RETROREFLECTION & PARAMETRIC INTERMODULATION -->
    <div v-if="subTab === 'retro'" class="grid-2">
      <div class="controls-col">
        <div class="preset-row">
          <button class="btn" :class="{ 'btn-active': rp.active_transceiver_enabled }" @click="toggleActiveTx">
            {{ rp.active_transceiver_enabled ? 'Active Opposing Pilot: ON' : 'Passive Observer Only' }}
          </button>
          <button class="btn" @click="apply20vs19Preset">20 kHz vs 19 kHz -> 1 kHz Preset</button>
          <button class="btn" :class="{ 'btn-active': audioPreviewMode === 'heterodyne' }" @click="toggleAudioPreview('heterodyne')">
            {{ audioPreviewMode === 'heterodyne' ? 'Stop Beat Tone' : 'Audition Beat' }}
          </button>
        </div>

        <div class="ctrl-row">
          <div class="ctrl-label"><span>Primary Sonar Carrier (f1)</span><span class="mono">{{ rp.sonar_freq_hz }} Hz</span></div>
          <input type="range" min="16000" max="45000" step="100" v-model.number="rp.sonar_freq_hz" @input="syncRetro" />
        </div>
        <div class="ctrl-row" v-if="rp.active_transceiver_enabled">
          <div class="ctrl-label"><span>Opposing Pilot Tone (f2)</span><span class="mono">{{ rp.transceiver_freq_hz }} Hz</span></div>
          <input type="range" min="15000" max="45000" step="100" v-model.number="rp.transceiver_freq_hz" @input="syncRetro" />
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Seated Observer Distance & Azimuth</span><span class="mono">{{ rp.observer_distance_m }}m / {{ rp.observer_azimuth_deg }}°</span></div>
          <div class="dual-range">
            <input type="range" min="0.6" max="4.5" step="0.1" v-model.number="rp.observer_distance_m" @input="syncRetro" />
            <input type="range" min="-75" max="75" step="1" v-model.number="rp.observer_azimuth_deg" @input="syncRetro" />
          </div>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Clothing Absorption vs Throat F0</span><span class="mono">{{ rp.clothing_absorption }} / {{ rp.throat_vibration_hz }} Hz</span></div>
          <div class="dual-range">
            <input type="range" min="0.05" max="0.85" step="0.02" v-model.number="rp.clothing_absorption" @input="syncRetro" />
            <input type="range" min="85" max="280" step="5" v-model.number="rp.throat_vibration_hz" @input="syncRetro" />
          </div>
        </div>

        <div class="zone-cards">
          <div class="metric-card">
            <div class="k">Clothing Scatter</div>
            <div class="v mono">{{ retro.passive_zones?.clothing?.spl_db }} dB</div>
          </div>
          <div class="metric-card">
            <div class="k">Torso Micro-Doppler</div>
            <div class="v mono">{{ retro.passive_zones?.body_torso?.spl_db }} dB</div>
          </div>
          <div class="metric-card">
            <div class="k">Throat Vibrometry</div>
            <div class="v mono">{{ retro.passive_zones?.throat_vocal?.spl_db }} dB</div>
          </div>
        </div>
      </div>

      <div class="viz-col">
        <div class="kpi-strip">
          <div class="metric-card">
            <div class="k">Downconverted Beat |f1 - f2|</div>
            <div class="v mono" style="color:var(--rose)">
              {{ retro.frequencies_hz?.f_diff_heterodyne ?? 'None' }} Hz
              <span v-if="retro.frequencies_hz?.is_audible_heterodyne" class="pill pill-rose">AUDIBLE IN ROOM</span>
            </div>
          </div>
          <div class="metric-card">
            <div class="k">Bicoherence / Gain Gamma</div>
            <div class="v mono">{{ retro.intermodulation_metrics?.bicoherence }} / {{ retro.intermodulation_metrics?.effective_reflection_gamma }}x</div>
          </div>
        </div>

        <svg viewBox="0 0 420 135" class="chart-svg">
          <polyline :points="retroSpecPoints" fill="none" stroke="#22d3ee" stroke-width="1.6" />
          <text x="8" y="14" fill="#94a3b8" font-size="10">Acoustic & Ultrasonic Spectrum (0 - 96 kHz)</text>
        </svg>

        <ul class="ind-list">
          <li v-for="(ind, i) in retro.indicators" :key="i">{{ ind }}</li>
        </ul>
      </div>
    </div>

    <!-- 2. LOCAL OSCILLATOR (LO) RADIATION & LEAKAGE -->
    <div v-if="subTab === 'lo'" class="grid-2">
      <div class="controls-col">
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Receive-Only SDR Architecture</span><span class="mono">{{ lp.sdr_architecture }}</span></div>
          <select v-model="lp.sdr_architecture" @change="syncLO">
            <option value="superhet">Superheterodyne (f_LO = f_RF + f_IF)</option>
            <option value="low_if">Low-IF Quadrature</option>
            <option value="zero_if">Zero-IF Direct Conversion (f_LO = f_RF)</option>
          </select>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Tuned RX Frequency & IF</span><span class="mono">{{ lp.tuned_rf_mhz }} / {{ lp.if_freq_mhz }} MHz</span></div>
          <div class="dual-range">
            <input type="range" min="100" max="2400" step="1" v-model.number="lp.tuned_rf_mhz" @input="syncLO" />
            <input type="range" min="0" max="70" step="0.5" v-model.number="lp.if_freq_mhz" @input="syncLO" />
          </div>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>LNA Reverse Isolation & Chassis Shielding</span><span class="mono">{{ lp.lna_reverse_isolation_db }} / {{ lp.chassis_shielding_db }} dB</span></div>
          <div class="dual-range">
            <input type="range" min="10" max="65" step="1" v-model.number="lp.lna_reverse_isolation_db" @input="syncLO" />
            <input type="range" min="5" max="65" step="1" v-model.number="lp.chassis_shielding_db" @input="syncLO" />
          </div>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Directional Probe Distance & Gain</span><span class="mono">{{ lp.scanner_distance_m }}m / {{ lp.scanner_antenna_gain_dbi }} dBi</span></div>
          <div class="dual-range">
            <input type="range" min="0.2" max="5.0" step="0.1" v-model.number="lp.scanner_distance_m" @input="syncLO" />
            <input type="range" min="0" max="22" step="1" v-model.number="lp.scanner_antenna_gain_dbi" @input="syncLO" />
          </div>
        </div>
      </div>

      <div class="viz-col">
        <div class="kpi-strip">
          <div class="metric-card">
            <div class="k">Leaked LO Fundamental</div>
            <div class="v mono" style="color:var(--violet)">{{ lo.frequencies_mhz?.lo_fundamental_mhz }} MHz</div>
          </div>
          <div class="metric-card">
            <div class="k">Scanner SNR / Pinpoint CEP</div>
            <div class="v mono">{{ lo.leakage_budget?.scanner_snr_db }} dB / ±{{ lo.leakage_budget?.localization_cep_m }} m</div>
          </div>
        </div>

        <div class="heatmap-row">
          <div class="heatmap-grid" v-if="lo.spatial_heatmap?.rssi_dbm?.length">
            <div v-for="(row, rIdx) in lo.spatial_heatmap.rssi_dbm" :key="rIdx" class="hm-row">
              <span v-for="(val, cIdx) in row" :key="cIdx" class="hm-cell" :style="{ background: rssiColor(val) }" :title="`${val} dBm`"></span>
            </div>
          </div>
          <svg viewBox="0 0 260 120" class="chart-svg flex-1">
            <polyline :points="loSpecPoints" fill="none" stroke="#a855f7" stroke-width="1.6" />
            <text x="8" y="14" fill="#94a3b8" font-size="10">Near-Field RF Sweep (dBm)</text>
          </svg>
        </div>
      </div>
    </div>

    <!-- 3. SPEAKER COIL MICROPHONICS (TRANSDUCER REVERSIBILITY) -->
    <div v-if="subTab === 'coil'" class="grid-2">
      <div class="controls-col">
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Amplifier Load State</span><span class="mono">{{ mp.amp_powered_state }}</span></div>
          <select v-model="mp.amp_powered_state" @change="syncMicro">
            <option value="active_powered">Active Powered (Low Z_out Damping)</option>
            <option value="unpowered_wired">Unpowered Wired Rack</option>
            <option value="standby_relay_open">Standby Open Relay (High Back-EMF)</option>
          </select>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Voice-Coil Force Factor (B·l) & Resonance Fs</span><span class="mono">{{ mp.bl_force_factor_tm }} T·m / {{ mp.resonance_freq_hz }} Hz</span></div>
          <div class="dual-range">
            <input type="range" min="1.5" max="14.0" step="0.2" v-model.number="mp.bl_force_factor_tm" @input="syncMicro" />
            <input type="range" min="40" max="250" step="2" v-model.number="mp.resonance_freq_hz" @input="syncMicro" />
          </div>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Injected Room Impulse SPL & Pitch</span><span class="mono">{{ mp.impulse_spl_db }} dB / {{ mp.impulse_center_hz }} Hz</span></div>
          <div class="dual-range">
            <input type="range" min="55" max="115" step="1" v-model.number="mp.impulse_spl_db" @input="syncMicro" />
            <input type="range" min="30" max="400" step="5" v-model.number="mp.impulse_center_hz" @input="syncMicro" />
          </div>
        </div>
      </div>

      <div class="viz-col">
        <div class="kpi-strip">
          <div class="metric-card">
            <div class="k">Induced Open-Circuit Back-EMF</div>
            <div class="v mono" style="color:var(--amber)">{{ micro.electromechanical_metrics?.open_circuit_back_emf_uv }} uV</div>
          </div>
          <div class="metric-card">
            <div class="k">Cable Terminal / Rail Ripple</div>
            <div class="v mono">{{ micro.electromechanical_metrics?.cable_terminal_voltage_uv }} uV / {{ micro.electromechanical_metrics?.power_rail_modulation_uv }} uV</div>
          </div>
        </div>

        <svg viewBox="0 0 420 125" class="chart-svg">
          <polyline :points="microWavePoints" fill="none" stroke="#f59e0b" stroke-width="1.6" />
          <text x="8" y="14" fill="#94a3b8" font-size="10">Reverse Induction Transient Pulse on Speaker Line (80 ms, uV)</text>
        </svg>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry, audioPreviewMode, postPhysicsUpdate, toggleAudioPreview } = useTelemetry()
const subTab = ref('retro')

const retro = computed(() => telemetry.retro_intermod || {})
const rp = computed(() => telemetry.retro_intermod.params)
const lo = computed(() => telemetry.lo_leakage || {})
const lp = computed(() => telemetry.lo_leakage.params)
const micro = computed(() => telemetry.speaker_microphonics || {})
const mp = computed(() => telemetry.speaker_microphonics.params)

function syncRetro() { postPhysicsUpdate('retro', rp.value) }
function syncLO() { postPhysicsUpdate('lo', lp.value) }
function syncMicro() { postPhysicsUpdate('microphonics', mp.value) }

function toggleActiveTx() {
  rp.value.active_transceiver_enabled = !rp.value.active_transceiver_enabled
  syncRetro()
}
function apply20vs19Preset() {
  rp.value.active_transceiver_enabled = true
  rp.value.sonar_freq_hz = 20000
  rp.value.transceiver_freq_hz = 19000
  syncRetro()
}

function toPolyline(arr, w, h, minV, maxV) {
  if (!arr || !arr.length) return ''
  const span = Math.max(maxV - minV, 1e-6)
  return arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * (w - 16) + 8
    const y = h - 10 - ((v - minV) / span) * (h - 28)
    return `${x.toFixed(1)},${Math.min(Math.max(y, 16), h - 6).toFixed(1)}`
  }).join(' ')
}

const retroSpecPoints = computed(() => toPolyline(retro.value.spectrum?.power_db, 420, 135, 15, 100))
const loSpecPoints = computed(() => toPolyline(lo.value.rf_spectrum?.power_dbm, 260, 120, -125, -45))
const microWavePoints = computed(() => {
  const arr = micro.value.transient_waveform?.voltage_uv || []
  const pk = Math.max(...arr.map(Math.abs), 10)
  return toPolyline(arr, 420, 125, -pk, pk)
})

function rssiColor(dbm) {
  const norm = Math.min(Math.max((dbm + 105) / 55, 0), 1)
  return `rgba(168, 85, 247, ${(0.12 + norm * 0.85).toFixed(2)})`
}
</script>

<style scoped>
.p-box { padding: 14px; }
.sec-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.sec-head h3 { font-size: 15px; color: #f8fafc; }
.sub { font-size: 11.5px; color: var(--text-muted); }
.tab-bar, .preset-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1.15fr; gap: 14px; }
@media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
.dual-range { display: flex; gap: 8px; }
.zone-cards, .kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-bottom: 10px; }
.k { font-size: 11px; color: var(--text-muted); }
.v { font-size: 13px; font-weight: 600; margin-top: 2px; }
.chart-svg { width: 100%; background: rgba(6, 9, 17, 0.72); border: 1px solid rgba(56, 189, 248, 0.14); border-radius: 8px; }
.ind-list { margin-top: 8px; padding-left: 16px; font-size: 11.5px; color: #cbd5e1; }
.heatmap-row { display: flex; gap: 10px; align-items: center; }
.heatmap-grid { display: flex; flex-direction: column; gap: 2px; padding: 6px; background: rgba(6, 9, 17, 0.8); border-radius: 6px; }
.hm-row { display: flex; gap: 2px; }
.hm-cell { width: 8px; height: 8px; border-radius: 1px; }
.flex-1 { flex: 1; }
</style>
