<template>
  <div class="glass-panel p-box">
    <div class="sec-head">
      <div>
        <h3>Sensing Core & Target Delivery Beamforming</h3>
        <p class="sub">1. Non-Contact Pilot-Tone IQ Phase Demodulation • 5. Delay-and-Sum Array + Binaural HRTF ITD/ILD Targeting</p>
      </div>
      <div class="tab-bar">
        <button class="btn" :class="{ 'btn-active': mode === 'pilot' }" @click="mode = 'pilot'">1. Pilot-Tone IQ Sensing</button>
        <button class="btn" :class="{ 'btn-active': mode === 'beam' }" @click="mode = 'beam'">5. Delay&Sum + Binaural HRTF</button>
      </div>
    </div>

    <!-- 1. PILOT-TONE PHASE DEMODULATION -->
    <div v-if="mode === 'pilot'" class="grid-2">
      <div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Ultrasonic CW Pilot Frequency</span><span class="mono">{{ pp.pilot_freq_hz }} Hz (λ={{ ps.metrics?.pilot_wavelength_mm }} mm)</span></div>
          <input type="range" min="18000" max="44000" step="200" v-model.number="pp.pilot_freq_hz" @input="syncPilot" />
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Non-Contact Subject Range & Baseband SNR</span><span class="mono">{{ pp.target_range_m }}m / {{ pp.snr_db }} dB</span></div>
          <div class="dual-range">
            <input type="range" min="0.4" max="3.5" step="0.05" v-model.number="pp.target_range_m" @input="syncPilot" />
            <input type="range" min="10" max="45" step="1" v-model.number="pp.snr_db" @input="syncPilot" />
          </div>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>Vocal Laryngeal F0 & Micro-Motion (um)</span><span class="mono">{{ pp.laryngeal_f0_hz }} Hz / {{ pp.laryngeal_disp_um }} um</span></div>
          <div class="dual-range">
            <input type="range" min="80" max="280" step="2" v-model.number="pp.laryngeal_f0_hz" @input="syncPilot" />
            <input type="range" min="5" max="150" step="1" v-model.number="pp.laryngeal_disp_um" @input="syncPilot" />
          </div>
        </div>
        <div class="kpi-strip">
          <div class="metric-card">
            <div class="k">Phase Sensitivity</div>
            <div class="v mono" style="color:var(--cyan)">{{ ps.metrics?.phase_sensitivity_rad_mm }} rad/mm</div>
          </div>
          <div class="metric-card">
            <div class="k">IQ Coherence / Peak Excursion</div>
            <div class="v mono">{{ ps.metrics?.coherence_quality }} / {{ ps.metrics?.peak_displacement_um }} um</div>
          </div>
        </div>
      </div>

      <div class="viz-split">
        <svg viewBox="0 0 130 130" class="iq-svg">
          <circle cx="65" cy="65" r="50" fill="none" stroke="rgba(148,163,184,0.2)" stroke-dasharray="3,3" />
          <line x1="65" y1="8" x2="65" y2="122" stroke="rgba(148,163,184,0.18)" />
          <line x1="8" y1="65" x2="122" y2="65" stroke="rgba(148,163,184,0.18)" />
          <circle v-for="(pt, idx) in ps.iq_constellation" :key="idx" :cx="65 + pt.i * 42" :cy="65 - pt.q * 42" r="1.8" fill="#22d3ee" />
          <text x="6" y="13" fill="#94a3b8" font-size="9">I/Q Phasor Arc</text>
        </svg>

        <svg viewBox="0 0 280 130" class="chart-svg flex-1">
          <polyline :points="pilotDispPoints" fill="none" stroke="#10b981" stroke-width="1.6" />
          <text x="8" y="14" fill="#94a3b8" font-size="10">Unwrapped Phase -> Non-Contact Displacement (um)</text>
        </svg>
      </div>
    </div>

    <!-- 5. DELAY-AND-SUM BEAMFORMING + BINAURAL HRTF TARGETING -->
    <div v-if="mode === 'beam'" class="grid-2">
      <div>
        <div class="preset-row">
          <button class="btn" :class="{ 'btn-active': audioPreviewMode === 'hrtf' }" @click="toggleAudioPreview('hrtf')">
            {{ audioPreviewMode === 'hrtf' ? 'Stop 3D Binaural HRTF' : 'Audition 3D HRTF Target' }}
          </button>
          <select v-model="bp.window_taper" @change="syncBeam">
            <option value="hamming">Hamming Taper</option>
            <option value="uniform">Uniform Weights</option>
            <option value="chebyshev_like">Low-Sidelobe Blackman</option>
          </select>
        </div>

        <div class="ctrl-row">
          <div class="ctrl-label"><span>Delay-and-Sum Mics (M) & Look-Angle θ₀</span><span class="mono">{{ bp.num_mics }} ch / {{ bp.steer_azimuth_deg }}°</span></div>
          <div class="dual-range">
            <input type="range" min="2" max="24" step="2" v-model.number="bp.num_mics" @input="syncBeam" />
            <input type="range" min="-75" max="75" step="1" v-model.number="bp.steer_azimuth_deg" @input="syncBeam" />
          </div>
        </div>
        <div class="ctrl-row">
          <div class="ctrl-label"><span>HRTF Target Coordinate (X, Z) & Pitch Shift</span><span class="mono">({{ bp.target_x_m }}m, {{ bp.target_z_m }}m) / {{ bp.voice_pitch_shift_st }} st</span></div>
          <div class="dual-range">
            <input type="range" min="-3.0" max="3.0" step="0.1" v-model.number="bp.target_x_m" @input="syncBeam" />
            <input type="range" min="0.5" max="4.5" step="0.1" v-model.number="bp.target_z_m" @input="syncBeam" />
            <input type="range" min="-8" max="8" step="0.5" v-model.number="bp.voice_pitch_shift_st" @input="syncBeam" />
          </div>
        </div>

        <div class="kpi-strip">
          <div class="metric-card">
            <div class="k">3dB Beamwidth / Nulling</div>
            <div class="v mono" style="color:var(--emerald)">{{ bf.delay_and_sum?.beamwidth_3db_deg }}° / -{{ bf.delay_and_sum?.ambient_jammer_suppression_db }} dB</div>
          </div>
          <div class="metric-card">
            <div class="k">Binaural ITD / ILD</div>
            <div class="v mono">{{ bf.binaural_hrtf?.itd_us }} us / {{ bf.binaural_hrtf?.broadband_ild_db }} dB</div>
          </div>
          <div class="metric-card">
            <div class="k">Spatial Isolation</div>
            <div class="v mono">{{ bf.binaural_hrtf?.spatial_isolation_db }} dB</div>
          </div>
        </div>
      </div>

      <div class="viz-split">
        <svg viewBox="0 0 150 135" class="iq-svg">
          <path d="M 15 120 A 60 60 0 0 1 135 120" fill="none" stroke="rgba(148,163,184,0.2)" />
          <polygon :points="polarBeamPoly" fill="rgba(16,185,129,0.24)" stroke="#10b981" stroke-width="1.4" />
          <text x="8" y="13" fill="#94a3b8" font-size="9">Delay&Sum Polar</text>
        </svg>

        <svg viewBox="0 0 260 135" class="chart-svg flex-1">
          <polyline :points="leftEarPoints" fill="none" stroke="#22d3ee" stroke-width="1.5" />
          <polyline :points="rightEarPoints" fill="none" stroke="#f43f5e" stroke-width="1.5" />
          <text x="8" y="14" fill="#94a3b8" font-size="10">HRTF L (cyan) vs R (coral) + Pinna Notch</text>
        </svg>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry, audioPreviewMode, postPhysicsUpdate, toggleAudioPreview } = useTelemetry()
const mode = ref('beam')

const ps = computed(() => telemetry.pilot_sensing || {})
const pp = computed(() => telemetry.pilot_sensing.params)
const bf = computed(() => telemetry.beamforming_hrtf || {})
const bp = computed(() => telemetry.beamforming_hrtf.params)

function syncPilot() { postPhysicsUpdate('pilot', pp.value) }
function syncBeam() { postPhysicsUpdate('beamforming', bp.value) }

function linePts(arr, w, h, lo, hi) {
  if (!arr || !arr.length) return ''
  const span = Math.max(hi - lo, 1e-6)
  return arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * (w - 16) + 8
    const y = h - 10 - ((v - lo) / span) * (h - 28)
    return `${x.toFixed(1)},${Math.min(Math.max(y, 16), h - 6).toFixed(1)}`
  }).join(' ')
}

const pilotDispPoints = computed(() => {
  const arr = ps.value.waveform?.displacement_um || []
  const m = Math.max(...arr.map(Math.abs), 20)
  return linePts(arr, 280, 130, -m, m)
})

const polarBeamPoly = computed(() => {
  const angs = bf.value.delay_and_sum?.polar_angles_deg || []
  const gains = bf.value.delay_and_sum?.polar_gain_db || []
  if (!angs.length) return '75,120'
  const pts = ['75,120']
  for (let i = 0; i < angs.length; i += 2) {
    const r = Math.max(0, (gains[i] + 35) / 35) * 92
    const rad = ((angs[i] - 90) * Math.PI) / 180
    pts.push(`${(75 + Math.cos(rad) * r).toFixed(1)},${(120 + Math.sin(rad) * r).toFixed(1)}`)
  }
  return pts.join(' ')
})

const leftEarPoints = computed(() => linePts(bf.value.binaural_hrtf?.left_ear_tf_db, 260, 135, -18, 12))
const rightEarPoints = computed(() => linePts(bf.value.binaural_hrtf?.right_ear_tf_db, 260, 135, -18, 12))
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
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin-top: 6px; }
.k { font-size: 11px; color: var(--text-muted); }
.v { font-size: 13px; font-weight: 600; margin-top: 2px; }
.viz-split { display: flex; gap: 10px; align-items: stretch; }
.iq-svg, .chart-svg { background: rgba(6, 9, 17, 0.75); border: 1px solid rgba(56, 189, 248, 0.14); border-radius: 8px; }
.iq-svg { width: 140px; flex-shrink: 0; }
.flex-1 { flex: 1; width: 100%; }
</style>
