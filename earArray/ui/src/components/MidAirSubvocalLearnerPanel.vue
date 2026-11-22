<template>
  <section class="glass-panel subvocal-panel">
    <div class="panel-header">
      <div>
        <div class="section-title">
          00A // ZERO-EQUIPMENT MID-AIR SUBVOCAL &amp; PLUTOSDR SELF-LEARNING ENGINE (`ollama run andersolind/nightsweep-sigint`)
        </div>
        <h2>
          Pure Mid-Air 20 kHz Laryngeal Phase Recovery (`Δφ = 4π·δx/λ`), 32-Tap NLMS Clutter Nulling, Acoustic↔PlutoSDR Coherence Gate (`γ² ≥ τ`) &amp; Online 6-Class Self-Learner
        </h2>
      </div>
      <div class="header-badges">
        <span class="pill pill-emerald mono">ZERO PHYSICAL EQUIPMENT</span>
        <span class="pill pill-cyan mono">δx = {{ ma.skin_displacement_um }} µm ({{ ma.audible_spl_db }} dB SPL)</span>
        <span class="pill pill-violet mono">γ² = {{ pl.cross_modal_coherence_gamma2 }} | Acc {{ sl.self_convergence_accuracy_pct }}%</span>
        <span class="pill pill-amber mono">TX: {{ pl.last_transmitted_phrase }}</span>
        <button class="btn btn-active" @click="runAdvise" :disabled="busy">
          🧠 {{ busy ? 'Querying andersolind/nightsweep-sigint...' : 'Ask andersolind/nightsweep-sigint' }}
        </button>
      </div>
    </div>

    <div class="subvocal-grid">
      <!-- Column 1: Pure Mid-Air Ultrasonic Subvocal Phase & 32-Tap NLMS Multipath Nulling -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">1. PURE MID-AIR ULTRASONIC SUBVOCAL PHASE &amp; 32-TAP NLMS</span>
          <span class="mono val-emerald">NLMS Null: -{{ ma.lms_clutter_suppression_db }} dB</span>
        </div>

        <div class="metric-strip mono">
          <div class="m-item">
            <span class="m-lbl">Pilot f_p / λ</span>
            <span class="val-cyan">{{ (ma.pilot_freq_hz / 1000).toFixed(1) }} kHz / {{ ma.wavelength_mm }} mm</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">Unwrapped Δφ</span>
            <span class="val-emerald">{{ ma.unwrapped_phase_rad }} rad ({{ ma.skin_displacement_um }} µm)</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">Subvocal Ceiling</span>
            <span :class="ma.is_sublevel_silent ? 'val-emerald' : 'val-rose'">
              {{ ma.audible_spl_db }} / {{ ma.audible_spl_ceiling_db }} dB SPL
            </span>
          </div>
        </div>

        <!-- Mid-Air Subvocal Phase Envelope Waveform SVG -->
        <svg viewBox="0 0 300 76" class="wave-svg">
          <line x1="0" y1="38" x2="300" y2="38" stroke="rgba(148,163,184,0.2)" stroke-dasharray="3 2" />
          <polyline :points="waveformPoints(300, 76)" fill="none" stroke="#22d3ee" stroke-width="1.8" />
          <text x="8" y="14" fill="#94a3b8" font-size="8" font-family="monospace">
            NLMS-Isolated Mid-Air Subvocal Envelope (32 taps, µ={{ ma.lms_mu }})
          </text>
        </svg>

        <div class="ctrl-group">
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Mid-Air Ultrasonic Pilot Carrier f_p (Hz)</span>
              <span class="val">{{ ma.pilot_freq_hz }} Hz</span>
            </div>
            <input type="range" min="18500" max="23000" step="250" :value="sv.params.pilot_freq_hz"
              @input="e => runStep({ pilot_freq_hz: +e.target.value, epochs: 4 })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>32-Tap NLMS Adaptation Step (µ)</span>
              <span class="val">{{ sv.params.lms_mu }}</span>
            </div>
            <input type="range" min="0.005" max="0.080" step="0.005" :value="sv.params.lms_mu"
              @input="e => runStep({ lms_mu: +e.target.value, epochs: 4 })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Acoustic↔PlutoSDR Coherence Gate (τ_coh)</span>
              <span class="val">{{ sv.params.coherence_gate_threshold }}</span>
            </div>
            <input type="range" min="0.40" max="0.90" step="0.02" :value="sv.params.coherence_gate_threshold"
              @input="e => runStep({ coherence_gate_threshold: +e.target.value, epochs: 4 })" />
          </div>
        </div>
      </div>

      <!-- Column 2: Self-Supervised Teacher-Student Loop & 6-Class Softmax + EMA Prototypes -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">2. ONLINE SELF-SUPERVISED 6-CLASS SUBVOCAL LEARNER</span>
          <span class="mono val-cyan">
            Updates: {{ sl.self_supervised_updates }}/{{ sl.total_frames }} (Loss {{ sl.rolling_cross_entropy_loss }})
          </span>
        </div>

        <div class="prob-list mono">
          <div v-for="(prob, cls) in sl.class_probabilities" :key="cls" class="prob-row">
            <span class="cls-name" :class="{ active: cls === sl.predicted_class }">{{ shortClass(cls) }}</span>
            <div class="prob-bar-bg">
              <div class="prob-bar-fill" :style="{ width: `${Math.round(prob * 100)}%` }"></div>
            </div>
            <span class="cls-pct">{{ (prob * 100).toFixed(1) }}%</span>
          </div>
        </div>

        <!-- Rolling Self-Supervised Cross-Entropy Loss Curve -->
        <svg viewBox="0 0 300 58" class="wave-svg">
          <polyline :points="lossPoints(300, 58)" fill="none" stroke="#10b981" stroke-width="1.8" />
          <text x="8" y="13" fill="#6ee7b7" font-size="8" font-family="monospace">
            Self-Supervised Cross-Entropy Loss Convergence • Acc {{ sl.self_convergence_accuracy_pct }}%
          </text>
        </svg>

        <div class="preset-btns">
          <button class="btn btn-active" @click="runStep({ epochs: 20 })">⚡ Self-Learn +20 Epochs</button>
          <button class="btn" @click="runInject('ALPHA_LOCK')">🗣️ Subvocal: ALPHA_LOCK</button>
          <button class="btn" @click="runInject('SILENT_RELAY')">🗣️ Subvocal: SILENT_RELAY</button>
          <button class="btn" @click="runInject('PHASE_NULL')">🗣️ Subvocal: PHASE_NULL</button>
        </div>
      </div>

      <!-- Column 3: PlutoSDR Digital Twin IQ & andersolind/nightsweep-sigint Advisor -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">3. PLUTOSDR DIGITAL TWIN &amp; `andersolind/nightsweep-sigint`</span>
          <span class="mono val-amber">{{ pl.rx_freq_mhz }} / {{ pl.tx_freq_mhz }} MHz NBFM</span>
        </div>

        <div class="pluto-row">
          <svg viewBox="0 0 92 92" class="iq-svg">
            <circle cx="46" cy="46" r="36" fill="none" stroke="rgba(56,189,248,0.25)" stroke-dasharray="2 2" />
            <line x1="46" y1="4" x2="46" y2="88" stroke="rgba(148,163,184,0.2)" />
            <line x1="4" y1="46" x2="88" y2="46" stroke="rgba(148,163,184,0.2)" />
            <circle v-for="(pt, idx) in pl.iq_constellation_preview" :key="idx"
              :cx="46 + pt.i * 34" :cy="46 - pt.q * 34" r="2.2" fill="#10b981" />
          </svg>
          <div class="pluto-meta mono">
            <div>Mode: <span class="val-emerald">PURE MID-AIR DIGITAL TWIN</span></div>
            <div>Coherence Gate: <span class="val-cyan">γ² = {{ pl.cross_modal_coherence_gamma2 }} ({{ pl.coherence_locked ? 'LOCKED' : 'GATED' }})</span></div>
            <div>Token Window: <span class="val-amber">{{ (sl.token_window || []).map(shortClass).join(' → ') || 'IDLE' }}</span></div>
            <div>CLI: <code class="cli-badge">ollama run andersolind/nightsweep-sigint</code></div>
          </div>
        </div>

        <div class="advisor-box mono">
          <div class="advisor-head">
            <span class="val-cyan">🧠 {{ advisorModel }} ({{ advisorSource }})</span>
            <button class="btn" style="padding:2px 7px;font-size:10px" @click="runAdvise" :disabled="busy">
              🔄 Refresh AI Critique
            </button>
          </div>
          <pre class="advisor-pre">{{ advisorText }}</pre>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry, postSubvocalLearner } = useTelemetry()
const sv = computed(() => telemetry.subvocal_learner || {})
const ma = computed(() => sv.value.midair_acoustics || {})
const pl = computed(() => sv.value.pluto_sdr || {})
const sl = computed(() => sv.value.self_learning || {})

const busy = ref(false)
const localAdvice = ref('')
const localModel = ref('andersolind/nightsweep-sigint')
const localSource = ref('ready')

const advisorText = computed(() => {
  return (
    localAdvice.value ||
    sv.value.ollama_advisor?.last_advice ||
    'Click "Ask andersolind/nightsweep-sigint" to evaluate zero-equipment mid-air 20 kHz subvocal phase demodulation, 32-tap NLMS multipath clutter suppression, Acoustic-PlutoSDR coherence gating, and online 6-class self-learning convergence.'
  )
})
const advisorModel = computed(() => localModel.value || sv.value.ollama_advisor?.last_model_used || 'andersolind/nightsweep-sigint')
const advisorSource = computed(() => localSource.value || sv.value.ollama_advisor?.last_source || 'ready')

function shortClass(c) {
  return String(c || '').replace('SUBVOCAL_', '').replace('AMBIENT_', '')
}

function waveformPoints(w, h) {
  const arr = ma.value.waveform_preview || []
  if (!arr.length) return `0,${h / 2} ${w},${h / 2}`
  return arr
    .map((v, i) => {
      const x = (i / Math.max(1, arr.length - 1)) * w
      const y = h / 2 - Math.max(-1, Math.min(1, v * 1.4)) * (h * 0.38)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function lossPoints(w, h) {
  const arr = sl.value.loss_history || []
  if (!arr.length) return `0,${h / 2} ${w},${h / 2}`
  const maxL = Math.max(0.6, ...arr)
  return arr
    .map((v, i) => {
      const x = (i / Math.max(1, arr.length - 1)) * w
      const y = h - 8 - (Math.min(maxL, Math.max(0, v)) / maxL) * (h - 20)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function runStep(payload) {
  postSubvocalLearner('step', payload)
}

function runInject(token) {
  postSubvocalLearner('inject', { token })
}

async function runAdvise() {
  busy.value = true
  try {
    const res = await postSubvocalLearner('ollama-advise', { model: 'andersolind/nightsweep-sigint' })
    if (res && res.response) {
      localAdvice.value = res.response
      localModel.value = res.model_used || 'andersolind/nightsweep-sigint'
      localSource.value = res.source || 'ollama_live'
    }
  } catch {}
  busy.value = false
}
</script>

<style scoped>
.subvocal-panel { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; border: 1px solid rgba(16, 185, 129, 0.35); }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; }
.panel-header h2 { font-size: 13.5px; font-weight: 600; color: #f8fafc; }
.header-badges { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.subvocal-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 1150px) { .subvocal-grid { grid-template-columns: 1fr; } }
.sub-card { background: rgba(15, 23, 42, 0.75); border: 1px solid var(--border-glass); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 9px; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.card-tag { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-muted); }
.val-cyan { color: var(--cyan); font-size: 11px; }
.val-emerald { color: var(--emerald); font-size: 11px; }
.val-amber { color: var(--amber); font-size: 11px; }
.val-rose { color: var(--rose); font-size: 11px; }
.metric-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.m-item { background: rgba(2, 6, 23, 0.6); padding: 6px 7px; border-radius: 6px; border: 1px solid rgba(148, 163, 184, 0.12); display: flex; flex-direction: column; gap: 2px; font-size: 10px; }
.m-lbl { color: var(--text-muted); font-size: 9.5px; }
.wave-svg { width: 100%; height: 68px; background: rgba(2, 6, 23, 0.75); border-radius: 6px; border: 1px solid rgba(56, 189, 248, 0.18); }
.ctrl-group { display: flex; flex-direction: column; gap: 6px; }
.prob-list { display: flex; flex-direction: column; gap: 5px; font-size: 10px; }
.prob-row { display: grid; grid-template-columns: 115px 1fr 42px; align-items: center; gap: 6px; }
.cls-name { color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cls-name.active { color: #10b981; font-weight: 700; }
.prob-bar-bg { height: 7px; background: rgba(2, 6, 23, 0.8); border-radius: 4px; overflow: hidden; }
.prob-bar-fill { height: 100%; background: linear-gradient(90deg, #06b6d4, #10b981); transition: width 0.2s ease; }
.cls-pct { text-align: right; color: #e2e8f0; }
.preset-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.pluto-row { display: flex; gap: 10px; align-items: center; background: rgba(2, 6, 23, 0.55); padding: 7px; border-radius: 8px; }
.iq-svg { width: 84px; height: 84px; flex-shrink: 0; background: rgba(2, 6, 23, 0.9); border-radius: 6px; border: 1px solid rgba(16, 185, 129, 0.28); }
.pluto-meta { display: flex; flex-direction: column; gap: 4px; font-size: 10.5px; color: #cbd5e1; }
.cli-badge { background: rgba(15, 23, 42, 0.95); padding: 2px 5px; border-radius: 4px; color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 9.5px; }
.advisor-box { flex: 1; background: rgba(2, 6, 23, 0.78); border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.advisor-head { display: flex; justify-content: space-between; align-items: center; font-size: 10.5px; }
.advisor-pre { white-space: pre-wrap; font-size: 10.5px; color: #e2e8f0; max-height: 118px; overflow-y: auto; line-height: 1.42; margin: 0; }
</style>
