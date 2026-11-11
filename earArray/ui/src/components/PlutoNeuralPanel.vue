<template>
  <div class="glass-panel p-box">
    <div class="sec-head">
      <div>
        <h3>ADALM-Pluto Neural Adaptive Bridge (JACK + REAPER OSC + Bio-Macro Morse)</h3>
        <p class="sub">
          PlutoSDR {{ hw.rx_freq_mhz }} / {{ hw.tx_freq_mhz }} MHz • Online Softmax ANN Backprop • 10s Earworm WAV • Breath-to-Morse PTT
        </p>
      </div>
      <div class="badges">
        <span class="pill pill-cyan">{{ hw.mode }}</span>
        <span class="pill" :class="osc.is_reaper_track_armed ? 'pill-emerald' : 'pill-amber'">
          REAPER: {{ osc.is_reaper_track_armed ? 'TRACK ARMED' : 'MUTED' }}
        </span>
        <span class="pill" :class="osc.is_rf_carrier_precharged ? 'pill-rose' : 'pill-violet'">
          PTT: {{ osc.is_rf_carrier_precharged ? 'RF PRECHARGED' : 'STANDBY' }}
        </span>
      </div>
    </div>

    <div class="pluto-grid">
      <!-- Column 1: Pluto RF + JACK/REAPER OSC + Earworm -->
      <div class="col-box">
        <div class="mini-title">Pluto Transceiver, Squelch & 10s Earworm Buffer</div>

        <div class="ctrl-row">
          <div class="ctrl-label">
            <span>RX / TX Freq (MHz)</span>
            <span class="mono">{{ (pp.rx_freq / 1e6).toFixed(3) }} / {{ (pp.tx_freq / 1e6).toFixed(3) }}</span>
          </div>
          <div class="dual-range">
            <input type="range" min="70000000" max="440000000" step="100000" v-model.number="pp.rx_freq" @change="syncCfg" />
            <input type="range" min="70000000" max="440000000" step="100000" v-model.number="pp.tx_freq" @change="syncCfg" />
          </div>
        </div>

        <div class="ctrl-row">
          <div class="ctrl-label">
            <span>Simulated RF Variance & Audio Drive</span>
            <span class="mono">{{ pp.sim_rf_activity }} / {{ pp.sim_audio_rms }}</span>
          </div>
          <div class="dual-range">
            <input type="range" min="0.02" max="1.0" step="0.02" v-model.number="pp.sim_rf_activity" @input="syncCfg" />
            <input type="range" min="0.001" max="0.08" step="0.002" v-model.number="pp.sim_audio_rms" @input="syncCfg" />
          </div>
        </div>

        <div class="btn-strip">
          <button class="btn" @click="postPlutoAction('automation', { action: 'ARM_AUDIO' })">OSC Arm Track</button>
          <button class="btn" @click="postPlutoAction('automation', { action: 'PRECHARGE_RF' })">Precharge TX</button>
          <button class="btn" @click="postPlutoAction('automation', { action: 'DISARM_AND_RESET' })">Reset</button>
          <button class="btn btn-active" @click="saveEarworm">Export 10s Earworm ({{ ew.buffer_fill_s }}s)</button>
        </div>

        <div v-if="lastSaved" class="saved-note mono">Saved WAV -> logs/{{ lastSaved }}</div>
        <div class="osc-feed mono">
          <div>JACK: sdr_demod_to_reaper ⇄ reaper_fx_to_sdr | OSC UDP {{ osc.reaper_endpoint }}</div>
          <div v-for="(pkt, idx) in osc.recent_osc_packets" :key="idx" class="osc-line">
            [{{ pkt.ts }}] {{ pkt.address }} -> {{ pkt.value }}
          </div>
        </div>
      </div>

      <!-- Column 2: Online Softmax ANN Presence Classifier & Backprop -->
      <div class="col-box">
        <div class="mini-title">
          Online Softmax ANN ({{ nn.predicted_state }} • {{ Math.round((nn.confidence || 0) * 100) }}% • Steps: {{ nn.train_steps }})
        </div>

        <div class="prob-list">
          <div v-for="(prob, cls) in nn.probabilities" :key="cls" class="prob-row">
            <span class="mono cls-lbl">{{ cls }}</span>
            <div class="prob-track">
              <div class="prob-fill" :style="{ width: `${Math.round(prob * 100)}%` }"></div>
            </div>
            <span class="mono pct">{{ Math.round(prob * 100) }}%</span>
          </div>
        </div>

        <div class="feat-strip mono">
          <span>RF_Var: {{ nn.features?.rf_variance }}</span>
          <span>Audio_RMS×100: {{ nn.features?.audio_rms_x100 }}</span>
          <span>ZCR: {{ nn.features?.zero_crossings }}</span>
        </div>

        <div class="mini-title" style="margin-top:8px">Live Backpropagation Train Step (online_train_step)</div>
        <div class="btn-strip">
          <button v-for="cls in ['STABLE_IDLE', 'SITTING', 'STANDING', 'ROOM_MOVEMENT']" :key="cls" class="btn" @click="postPlutoAction('train', { target_class: cls })">
            Train {{ cls.split('_')[0] }}
          </button>
        </div>
      </div>

      <!-- Column 3: Breath Bio-Macro Tracker & Telegraphic Morse Engine -->
      <div class="col-box">
        <div class="mini-title">Breath Gesture Bio-Macro -> Preemptive Morse Engine</div>

        <div class="btn-strip">
          <button class="btn btn-active" @click="postPlutoAction('breath', { token: 'INHALE' })">+ INHALE</button>
          <button class="btn btn-active" @click="postPlutoAction('breath', { token: 'EXHALE' })">+ EXHALE</button>
          <button class="btn" @click="postPlutoAction('breath', { token: 'CLEAR' })">Clear Queue</button>
        </div>

        <div class="metric-card" style="margin-bottom:8px">
          <div class="k">Gesture Sequence & Forecasted Macro Intent</div>
          <div class="v mono" style="color:var(--cyan)">
            [ {{ (bm.breath_queue || []).join(' -> ') || 'REST' }} ] ➔ {{ bm.predicted_macro_intent }}
          </div>
        </div>

        <div class="metric-card" v-if="bm.last_dispatched_morse">
          <div class="k">Outbound Telegraphic Morse Dispatched</div>
          <div class="v mono" style="color:var(--emerald);display:flex;justify-content:space-between;align-items:center">
            <span>{{ bm.last_dispatched_morse }} ({{ bm.last_morse_symbols }})</span>
            <button class="btn" @click="playMorseSidetone(bm.last_morse_symbols)">Replay CW</button>
          </div>
        </div>

        <div class="macro-legend mono">
          <div>INHALE · INHALE · EXHALE ➔ CQ (-.-. --.-)</div>
          <div>EXHALE · EXHALE · INHALE ➔ READY (.-. . .- -.. -.--)</div>
          <div>INHALE · EXHALE · INHALE ➔ OK (--- -.-)</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry, postPlutoAction, playMorseSidetone } = useTelemetry()
const lastSaved = ref('')

const pb = computed(() => telemetry.pluto_bridge || {})
const hw = computed(() => pb.value.hardware || {})
const nn = computed(() => pb.value.neural_net || { probabilities: {} })
const osc = computed(() => pb.value.automation_osc || { recent_osc_packets: [] })
const bm = computed(() => pb.value.biomacro_morse || {})
const ew = computed(() => pb.value.earworm || {})
const pp = computed(() => pb.value.params || {})

function syncCfg() {
  postPlutoAction('config', pp.value)
}

async function saveEarworm() {
  const res = await postPlutoAction('earworm')
  if (res?.file) lastSaved.value = res.file
}
</script>

<style scoped>
.p-box { padding: 14px; }
.sec-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.sec-head h3 { font-size: 15px; color: #f8fafc; }
.sub { font-size: 11.5px; color: var(--text-muted); }
.badges, .btn-strip { display: flex; gap: 6px; flex-wrap: wrap; }
.btn-strip { margin: 6px 0; }
.pluto-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 1100px) { .pluto-grid { grid-template-columns: 1fr; } }
.col-box { background: rgba(6, 9, 17, 0.58); border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 9px; padding: 10px 12px; }
.mini-title { font-size: 11.5px; font-weight: 600; color: #94a3b8; margin-bottom: 8px; }
.dual-range { display: flex; gap: 8px; }
.prob-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.prob-row { display: flex; align-items: center; gap: 8px; font-size: 11px; }
.cls-lbl { width: 108px; color: #cbd5e1; }
.prob-track { flex: 1; height: 8px; background: rgba(30, 41, 59, 0.7); border-radius: 4px; overflow: hidden; }
.prob-fill { height: 100%; background: linear-gradient(90deg, #10b981, #22d3ee); transition: width 0.2s ease; }
.pct { width: 34px; text-align: right; color: var(--cyan); }
.feat-strip { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-dim); padding-top: 4px; border-top: 1px solid rgba(148,163,184,0.1); }
.osc-feed { margin-top: 6px; font-size: 10.5px; color: var(--text-muted); max-height: 76px; overflow-y: auto; }
.osc-line { color: #67e8f9; }
.saved-note { font-size: 11px; color: var(--emerald); margin-top: 4px; }
.macro-legend { font-size: 10.5px; color: var(--text-dim); margin-top: 8px; line-height: 1.55; }
.k { font-size: 11px; color: var(--text-muted); }
.v { font-size: 12px; font-weight: 600; margin-top: 3px; }
</style>
