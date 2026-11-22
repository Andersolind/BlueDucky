<template>
  <section class="glass-panel tof-panel">
    <div class="panel-header">
      <div>
        <div class="section-title">00 // MULTI-NODE ULTRASONIC TOF SELF-CALIBRATION & 10m×10m TRAJECTORY ENGINE</div>
        <h2>Ultrasonic Chime TOF Baseline Matrix (`execute_hardware_self_calibration`) & Sector Schematic (`compute_spatial_trajectory_overlay`)</h2>
      </div>
      <div class="header-badges">
        <span class="pill pill-cyan mono">c = {{ tof.room_limits_m.sound_speed_m_s }} m/s</span>
        <span class="pill pill-emerald mono">{{ tof.current_overlay.x_map_pct }} × {{ tof.current_overlay.y_map_pct }}</span>
        <span class="pill pill-violet mono">{{ shortZone }}</span>
        <button class="btn btn-active" @click="openModal">
          🛰️ Open Calibration & AI Model Modal
        </button>
      </div>
    </div>

    <div class="tof-grid">
      <!-- Left: TOF Chime Self-Calibration Controls -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">SELF-CALIBRATION MATRIX</span>
          <span class="mono val-cyan">Area {{ tof.calibrated_baselines_m.area_m2 }} m²</span>
        </div>

        <div class="node-list mono">
          <div class="node-row">
            <span class="n-tag">NODE_1 (Fixed Master Anchor)</span>
            <span class="val-emerald">[{{ fmtCoord(tof.node_geometry.NODE_1) }}] m</span>
            <span class="n-tof">TOF→Tgt: {{ tof.target_tofs_ms.NODE_1 }} ms</span>
          </div>
          <div class="node-row">
            <span class="n-tag">NODE_2 (Calibrated Y Offset)</span>
            <span class="val-cyan">[{{ fmtCoord(tof.node_geometry.NODE_2) }}] m</span>
            <span class="n-tof">d₁₂={{ tof.calibrated_baselines_m.dist_12_m }}m</span>
          </div>
          <div class="node-row">
            <span class="n-tag">NODE_3 (Calibrated X Offset)</span>
            <span class="val-amber">[{{ fmtCoord(tof.node_geometry.NODE_3) }}] m</span>
            <span class="n-tof">d₁₃={{ tof.calibrated_baselines_m.dist_13_m }}m</span>
          </div>
        </div>

        <div class="ctrl-group">
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Chime TOF₁₂ (Node 1 → Node 2)</span>
              <span class="val">{{ (tof.params.tof_12_sec * 1000).toFixed(2) }} ms ({{ tof.params.tof_12_sec.toFixed(5) }} s)</span>
            </div>
            <input type="range" min="0.004" max="0.030" step="0.0005" :value="tof.params.tof_12_sec"
              @input="e => runCalibrate({ tof_12: +e.target.value })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Chime TOF₁₃ (Node 1 → Node 3)</span>
              <span class="val">{{ (tof.params.tof_13_sec * 1000).toFixed(2) }} ms ({{ tof.params.tof_13_sec.toFixed(5) }} s)</span>
            </div>
            <input type="range" min="0.004" max="0.030" step="0.0005" :value="tof.params.tof_13_sec"
              @input="e => runCalibrate({ tof_13: +e.target.value })" />
          </div>
        </div>

        <div class="preset-btns">
          <button class="btn" @click="runCalibrate({ tof_12: 10/343, tof_13: 10/343 })">Full 10m×10m Baseline</button>
          <button class="btn" @click="runCalibrate({ tof_12: 0.021, tof_13: 0.024 })">Shifted Node Chime</button>
          <button class="btn" :class="{ 'btn-active': tof.params.auto_orbit_target }"
            @click="runTrajectory({ auto_orbit_target: !tof.params.auto_orbit_target })">
            {{ tof.params.auto_orbit_target ? 'Auto-Orbit: ON' : 'Manual Click Mode' }}
          </button>
        </div>
      </div>

      <!-- Center: Interactive 10m x 10m Room Schematic SVG -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">10m × 10m ROOM QUADRANT SCHEMATIC (CLICK TO SET TARGET)</span>
          <span class="mono val-amber">({{ tof.current_overlay.x_coord_m }}m, {{ tof.current_overlay.y_coord_m }}m)</span>
        </div>

        <svg viewBox="0 0 320 220" class="room-svg" @click="onSvgClick($event, 320, 220)">
          <!-- 4 Quadrant Backgrounds -->
          <rect x="20" y="10" width="140" height="95" fill="rgba(56,189,248,0.06)" stroke="rgba(148,163,184,0.2)" />
          <rect x="160" y="10" width="140" height="95" fill="rgba(16,185,129,0.07)" stroke="rgba(148,163,184,0.2)" />
          <rect x="20" y="105" width="140" height="95" fill="rgba(168,85,247,0.06)" stroke="rgba(148,163,184,0.2)" />
          <rect x="160" y="105" width="140" height="95" fill="rgba(245,158,11,0.06)" stroke="rgba(148,163,184,0.2)" />

          <!-- Quadrant Labels -->
          <text x="26" y="24" fill="#7dd3fc" font-size="7.5">NW: Hallway Entry</text>
          <text x="166" y="24" fill="#6ee7b7" font-size="7.5">NE: Living Room Window</text>
          <text x="26" y="194" fill="#d8b4fe" font-size="7.5">SW: Bedroom Perimeter</text>
          <text x="166" y="194" fill="#fcd34d" font-size="7.5">SE: Staircase Corridor</text>

          <!-- Calibrated Node Triangle -->
          <polygon :points="trianglePoints(320, 220)" fill="rgba(34,211,238,0.08)" stroke="#22d3ee" stroke-dasharray="3 2" />

          <!-- Trajectory Trail -->
          <polyline :points="trailPoints(320, 220)" fill="none" stroke="#f43f5e" stroke-width="1.5" opacity="0.65" />

          <!-- Nodes -->
          <g v-for="(coord, key) in tof.node_geometry" :key="key">
            <circle :cx="mapX(coord[0], 320)" :cy="mapY(coord[1], 220)" r="5" fill="#10b981" stroke="#0f172a" stroke-width="1.5" />
            <text :x="mapX(coord[0], 320) + 7" :y="mapY(coord[1], 220) + 3" fill="#e2e8f0" font-size="8" font-family="monospace">{{ key }}</text>
          </g>

          <!-- Active Target -->
          <circle :cx="mapX(tof.current_overlay.x_coord_m, 320)" :cy="mapY(tof.current_overlay.y_coord_m, 220)"
            r="6" fill="#f43f5e" stroke="#fff" stroke-width="1.5" />
        </svg>

        <div class="zone-banner mono">
          <span>{{ tof.current_overlay.zone_descriptor }}</span>
          <span class="val-cyan">{{ tof.current_overlay.timestamp }}</span>
        </div>
      </div>

      <!-- Right: Coordinate Sliders & Calibration Log -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">SPATIAL TRAJECTORY OVERLAY LOG</span>
          <span class="mono val-emerald">{{ tof.current_overlay.x_map_pct }} / {{ tof.current_overlay.y_map_pct }}</span>
        </div>

        <div class="ctrl-group">
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Target X Coordinate (m)</span>
              <span class="val">{{ tof.current_overlay.x_coord_m }} m ({{ tof.current_overlay.x_map_pct }})</span>
            </div>
            <input type="range" min="0" max="10" step="0.1" :value="tof.current_overlay.x_coord_m"
              @input="e => runTrajectory({ x_coord: +e.target.value, auto_orbit_target: false })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Target Y Coordinate (m)</span>
              <span class="val">{{ tof.current_overlay.y_coord_m }} m ({{ tof.current_overlay.y_map_pct }})</span>
            </div>
            <input type="range" min="0" max="10" step="0.1" :value="tof.current_overlay.y_coord_m"
              @input="e => runTrajectory({ y_coord: +e.target.value, auto_orbit_target: false })" />
          </div>
        </div>

        <div class="log-box mono">
          <div v-for="(entry, idx) in tof.calibration_logs" :key="idx" class="log-line">
            <span class="val-cyan">[{{ entry.timestamp }}]</span>
            <span>N2={{ entry.NODE_2 }} N3={{ entry.NODE_3 }} (d₁₂={{ entry.dist_12_m }}m, d₁₃={{ entry.dist_13_m }}m)</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Interactive Calibration & AI Model Modal -->
    <div v-if="showModal" class="modal-backdrop" @click.self="showModal = false">
      <div class="modal-window glass-panel">
        <div class="modal-header">
          <div>
            <div class="section-title">INTERACTIVE CALIBRATION &amp; AI MODEL MODAL (`ollama run andersolind/nightsweep-sigint`)</div>
            <h3>Multi-Node Ultrasonic TOF Matrix, 10m×10m Quadrant Schematic &amp; Zero-Equipment Mid-Air Subvocal + PlutoSDR AI</h3>
          </div>
          <div class="modal-tabs">
            <button class="btn" :class="{ 'btn-active': modalTab === 'schematic' }" @click="modalTab = 'schematic'">
              🛰️ Calibration &amp; Quadrant Matrix
            </button>
            <button class="btn" :class="{ 'btn-active': modalTab === 'modelfile' }" @click="loadModelfile">
              🧠 Ollama Model (`andersolind/nightsweep-sigint`)
            </button>
            <button class="btn" @click="showModal = false">✕ Close</button>
          </div>
        </div>

        <div v-if="modalTab === 'schematic'" class="modal-body-grid">
          <div>
            <svg viewBox="0 0 420 300" class="room-svg modal-svg" @click="onSvgClick($event, 420, 300)">
              <rect x="20" y="10" width="190" height="140" fill="rgba(56,189,248,0.08)" stroke="rgba(148,163,184,0.28)" />
              <rect x="210" y="10" width="190" height="140" fill="rgba(16,185,129,0.08)" stroke="rgba(148,163,184,0.28)" />
              <rect x="20" y="150" width="190" height="140" fill="rgba(168,85,247,0.08)" stroke="rgba(148,163,184,0.28)" />
              <rect x="210" y="150" width="190" height="140" fill="rgba(245,158,11,0.08)" stroke="rgba(148,163,184,0.28)" />
              <text x="28" y="28" fill="#7dd3fc" font-size="9">NORTHWEST_QUADRANT (Hallway Entry Transition Line)</text>
              <text x="218" y="28" fill="#6ee7b7" font-size="9">NORTHEAST_QUADRANT (Living Room Window Path)</text>
              <text x="28" y="282" fill="#d8b4fe" font-size="9">SOUTHWEST_QUADRANT (Dampened Bedroom Perimeter)</text>
              <text x="218" y="282" fill="#fcd34d" font-size="9">SOUTHEAST_QUADRANT (Staircase Ascent Access Corridor)</text>
              <polygon :points="trianglePoints(420, 300)" fill="rgba(34,211,238,0.1)" stroke="#22d3ee" stroke-width="1.5" />
              <polyline :points="trailPoints(420, 300)" fill="none" stroke="#f43f5e" stroke-width="2" />
              <g v-for="(coord, key) in tof.node_geometry" :key="key">
                <circle :cx="mapX(coord[0], 420)" :cy="mapY(coord[1], 300)" r="6.5" fill="#10b981" stroke="#fff" />
                <text :x="mapX(coord[0], 420) + 9" :y="mapY(coord[1], 300) + 4" fill="#fff" font-size="10" font-family="monospace">
                  {{ key }} [{{ fmtCoord(coord) }}]
                </text>
              </g>
              <circle :cx="mapX(tof.current_overlay.x_coord_m, 420)" :cy="mapY(tof.current_overlay.y_coord_m, 300)"
                r="7.5" fill="#f43f5e" stroke="#fff" stroke-width="2" />
            </svg>
          </div>
          <div class="modal-meta mono">
            <div class="meta-block">
              <div class="card-tag">ACTIVE OVERLAY PACKET (`compute_spatial_trajectory_overlay`)</div>
              <pre>{{ JSON.stringify(tof.current_overlay, null, 2) }}</pre>
            </div>
            <div class="meta-block">
              <div class="card-tag">CALIBRATED NODE GEOMETRY (`NODE_GEOMETRY`)</div>
              <pre>{{ JSON.stringify(tof.node_geometry, null, 2) }}</pre>
            </div>
          </div>
        </div>

        <div v-else class="modal-modelfile mono">
          <div class="modelfile-bar">
            <span>Path: {{ modelfilePath }} • <code>ollama run andersolind/nightsweep-sigint</code></span>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <span class="pill" :class="ollamaOnline ? 'pill-emerald' : 'pill-amber'">
                {{ ollamaOnline ? 'Ollama Online (andersolind/nightsweep-sigint)' : 'Deterministic Engine Ready' }}
              </span>
              <button class="btn" @click="buildOllamaModel" :disabled="ollamaBusy">
                🔨 {{ ollamaBusy ? 'Working...' : 'Build andersolind/nightsweep-sigint in Ollama' }}
              </button>
              <button class="btn btn-active" @click="runOllamaAdvise" :disabled="ollamaBusy">
                ⚡ Run Mid-Air Subvocal + PlutoSDR AI Diagnostics
              </button>
            </div>
          </div>
          <div v-if="aiResponse" class="meta-block" style="margin-bottom:10px;border-color:rgba(16,185,129,0.45)">
            <div class="card-tag" style="color:#10b981">LIVE ANDERSOLIND/NIGHTSWEEP-SIGINT DIAGNOSTICS ({{ aiSource }})</div>
            <pre>{{ aiResponse }}</pre>
          </div>
          <pre class="modelfile-pre">{{ modelfileContent }}</pre>
        </div>
      </div>
    </div>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry, postSpatialTof } = useTelemetry()
const tof = computed(() => telemetry.spatial_tof)

const showModal = ref(false)
const modalTab = ref('schematic')
const modelfilePath = ref('/home/anders/HackRf/BlueDucky/earArray/Modelfile')
const modelfileContent = ref('Loading Modelfile...')
const ollamaOnline = ref(false)
const ollamaBusy = ref(false)
const aiResponse = ref('')
const aiSource = ref('eararray-sigint')

const shortZone = computed(() => {
  const z = tof.value.current_overlay.zone_descriptor || ''
  return z.split(' ')[0] || 'QUADRANT'
})

function fmtCoord(arr) {
  if (!arr || arr.length < 2) return '0.0, 0.0'
  return `${Number(arr[0]).toFixed(2)}, ${Number(arr[1]).toFixed(2)}`
}

function mapX(xm, w) {
  const pad = 20
  return pad + (Math.min(10, Math.max(0, xm)) / 10) * (w - pad * 2)
}

function mapY(ym, h) {
  const pad = 10
  return (h - pad) - (Math.min(10, Math.max(0, ym)) / 10) * (h - pad * 2)
}

function trianglePoints(w, h) {
  const g = tof.value.node_geometry
  return [g.NODE_1, g.NODE_2, g.NODE_3]
    .map(c => `${mapX(c[0], w).toFixed(1)},${mapY(c[1], h).toFixed(1)}`)
    .join(' ')
}

function trailPoints(w, h) {
  return (tof.value.trajectory_trail || [])
    .map(p => `${mapX(p.x_coord_m, w).toFixed(1)},${mapY(p.y_coord_m, h).toFixed(1)}`)
    .join(' ')
}

function runCalibrate(payload) {
  postSpatialTof('calibrate', payload)
}

function runTrajectory(payload) {
  postSpatialTof('trajectory', payload)
}

function onSvgClick(ev, w, h) {
  const rect = ev.currentTarget.getBoundingClientRect()
  const sx = ((ev.clientX - rect.left) / rect.width) * w
  const sy = ((ev.clientY - rect.top) / rect.height) * h
  const padX = 20
  const padY = 10
  const x_coord = Math.min(10, Math.max(0, ((sx - padX) / (w - padX * 2)) * 10))
  const y_coord = Math.min(10, Math.max(0, (((h - padY) - sy) / (h - padY * 2)) * 10))
  runTrajectory({ x_coord: +x_coord.toFixed(2), y_coord: +y_coord.toFixed(2), auto_orbit_target: false })
}

async function loadModelfile() {
  modalTab.value = 'modelfile'
  try {
    const [mfRes, stRes] = await Promise.all([
      fetch('/api/modelfile'),
      fetch('/api/ollama/status'),
    ])
    if (mfRes.ok) {
      const data = await mfRes.json()
      modelfilePath.value = data.path
      modelfileContent.value = data.content
    }
    if (stRes.ok) {
      const st = await stRes.json()
      ollamaOnline.value = !!(st.online && st.eararray_registered)
    }
  } catch {}
}

async function buildOllamaModel() {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: 'andersolind/nightsweep-sigint' }),
    })
    if (res.ok) {
      const d = await res.json()
      ollamaOnline.value = !!d.ok
      aiSource.value = 'ollama create'
      aiResponse.value = d.ok
        ? `✅ Built andersolind/nightsweep-sigint in Ollama\n${d.stdout || ''}`
        : `⚠️ Build note: ${d.stderr || d.error || 'Failed'}`
    }
  } catch {}
  ollamaBusy.value = false
}

async function runOllamaAdvise() {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/advise', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'andersolind/nightsweep-sigint' }),
    })
    if (res.ok) {
      const d = await res.json()
      aiSource.value = `${d.model} • ${d.source}`
      aiResponse.value = d.response
    }
  } catch {}
  ollamaBusy.value = false
}

function openModal() {
  showModal.value = true
  loadModelfile()
  modalTab.value = 'schematic'
}
</script>

<style scoped>
.tof-panel { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; }
.panel-header h2 { font-size: 14px; font-weight: 600; color: #f8fafc; }
.header-badges { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.tof-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 1150px) { .tof-grid { grid-template-columns: 1fr; } }
.sub-card { background: rgba(15, 23, 42, 0.72); border: 1px solid var(--border-glass); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 9px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.card-tag { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-muted); }
.val-cyan { color: var(--cyan); font-size: 11px; }
.val-emerald { color: var(--emerald); font-size: 11px; }
.val-amber { color: var(--amber); font-size: 11px; }
.node-list { display: flex; flex-direction: column; gap: 5px; font-size: 11px; }
.node-row { display: flex; justify-content: space-between; align-items: center; background: rgba(2, 6, 23, 0.55); padding: 5px 8px; border-radius: 6px; border: 1px solid rgba(148, 163, 184, 0.12); }
.n-tag { color: #cbd5e1; font-size: 10px; }
.n-tof { color: var(--text-muted); font-size: 10px; }
.ctrl-group { display: flex; flex-direction: column; gap: 6px; }
.preset-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.room-svg { width: 100%; height: 175px; background: rgba(2, 6, 23, 0.78); border-radius: 8px; border: 1px solid rgba(56, 189, 248, 0.22); cursor: crosshair; }
.zone-banner { display: flex; justify-content: space-between; align-items: center; font-size: 10.5px; background: rgba(15, 23, 42, 0.9); padding: 6px 9px; border-radius: 6px; border-left: 3px solid var(--cyan); }
.log-box { max-height: 92px; overflow-y: auto; background: rgba(2, 6, 23, 0.65); border-radius: 6px; padding: 6px 8px; font-size: 10px; display: flex; flex-direction: column; gap: 4px; }
.log-line { display: flex; gap: 6px; color: #cbd5e1; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(2, 6, 23, 0.82); backdrop-filter: blur(8px); z-index: 999; display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal-window { width: min(1040px, 95vw); max-height: 88vh; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px; border: 1px solid rgba(56, 189, 248, 0.4); }
.modal-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.modal-header h3 { font-size: 15px; color: #f8fafc; }
.modal-tabs { display: flex; gap: 8px; }
.modal-body-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; }
.modal-svg { height: 290px; }
.modal-meta { display: flex; flex-direction: column; gap: 10px; }
.meta-block { background: rgba(2, 6, 23, 0.75); padding: 10px; border-radius: 8px; border: 1px solid var(--border-glass); font-size: 11px; }
.meta-block pre, .modelfile-pre { margin-top: 6px; white-space: pre-wrap; color: #e2e8f0; font-size: 11px; max-height: 320px; overflow-y: auto; }
.modelfile-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 11px; }
</style>
