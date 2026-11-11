<template>
  <div class="glass-panel p-box">
    <div class="sec-head">
      <div>
        <h3>Dolphin Forensics Vault, Cross-Layer CSV Logs & Workspace Modules</h3>
        <p class="sub">dolphin_forensics/ ({{ totalDetections }} captures) • logs/ CSV runs • Full Python Codebase Inventory</p>
      </div>
      <div class="tab-bar">
        <button class="btn" :class="{ 'btn-active': tab === 'forensics' }" @click="tab = 'forensics'">Forensics Captures</button>
        <button class="btn" :class="{ 'btn-active': tab === 'logs' }" @click="tab = 'logs'">Telemetry CSV Logs</button>
        <button class="btn" :class="{ 'btn-active': tab === 'modules' }" @click="tab = 'modules'">Folder Modules ({{ modules.length }})</button>
      </div>
    </div>

    <!-- DOLPHIN FORENSICS VAULT -->
    <div v-if="tab === 'forensics'" class="vault-grid">
      <div class="list-pane">
        <div class="beacon-pills">
          <span v-for="(cnt, name) in beaconCounts" :key="name" class="pill pill-violet">{{ name.split(' ')[0] }}: {{ cnt }}</span>
        </div>
        <div class="det-list">
          <div
            v-for="d in detections.slice(0, 40)"
            :key="d.file"
            class="det-item"
            :class="{ active: selectedDet?.file === d.file }"
            @click="selectDetection(d)"
          >
            <div class="mono">{{ d.file.replace('.json', '') }}</div>
            <div class="det-meta mono">
              <span>{{ d.dominant_ultrasonic_hz }} Hz ({{ d.dominant_ultrasonic_db }} dB)</span>
              <span class="pill pill-cyan">{{ d.direction }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="detail-pane" v-if="selectedDet">
        <div class="det-header">
          <div>
            <h4 class="mono">{{ selectedDet.file }}</h4>
            <div class="sub">{{ selectedDet.timestamp }} • Dominant: {{ selectedDet.dominant_ultrasonic_hz }} Hz</div>
          </div>
          <button v-if="selectedDet.wav_file" class="btn btn-active" @click="runWavAnalysis(selectedDet.wav_file)">
            Analyze WAV (Replay + Intermod)
          </button>
        </div>

        <audio v-if="selectedDet.wav_file" :src="`/forensics_static/${selectedDet.wav_file}`" controls class="wav-player"></audio>

        <div v-if="wavAnalysis" class="metric-card analysis-box mono">
          <div><strong>Replay Verdict:</strong> {{ wavAnalysis.replay?.threat_level || 'Evaluated' }} (Conf: {{ wavAnalysis.replay?.confidence ?? 0 }})</div>
          <div><strong>Intermod Regime:</strong> {{ wavAnalysis.intermodulation?.regime }} • Bicoherence: {{ wavAnalysis.intermodulation?.bicoherence ?? 0 }}</div>
        </div>

        <img
          v-if="selectedDet.spectrogram_file"
          :src="`/forensics_static/${selectedDet.spectrogram_file}`"
          alt="Spectrogram"
          class="spec-img"
        />
      </div>
    </div>

    <!-- CSV LOGS -->
    <div v-if="tab === 'logs'">
      <div class="log-bar">
        <select v-model="selectedCsv" @change="loadCsv(selectedCsv)">
          <option v-for="f in logFiles" :key="f" :value="f">{{ f }}</option>
        </select>
        <span class="mono sub">Showing {{ csvRows.length }} rows</span>
      </div>
      <div class="csv-scroll" v-if="csvRows.length">
        <table class="ble-tbl mono">
          <thead>
            <tr>
              <th v-for="col in csvCols" :key="col">{{ col }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in csvRows.slice(0, 35)" :key="idx">
              <td v-for="col in csvCols" :key="col">{{ r[col] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- FOLDER MODULES INVENTORY -->
    <div v-if="tab === 'modules'" class="mod-grid">
      <div v-for="m in modules" :key="m.file" class="metric-card mod-card" @click="inspectSource(m.file)">
        <div class="mod-top">
          <span class="mono" style="color:var(--cyan);font-weight:600">{{ m.file }}</span>
          <span class="pill pill-emerald">{{ m.lines }} lines</span>
        </div>
        <div class="mod-title">{{ m.title }}</div>
        <p class="sub">{{ m.summary }}</p>
      </div>
      <pre v-if="sourcePreview" class="src-box mono">{{ sourcePreview }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const tab = ref('forensics')
const totalDetections = ref(0)
const detections = ref([])
const beaconCounts = ref({})
const selectedDet = ref(null)
const wavAnalysis = ref(null)

const logFiles = ref([])
const selectedCsv = ref('')
const csvRows = ref([])
const csvCols = computed(() => (csvRows.value.length ? Object.keys(csvRows.value[0]).slice(0, 10) : []))

const modules = ref([])
const sourcePreview = ref('')

function selectDetection(d) {
  selectedDet.value = d
  wavAnalysis.value = null
}

async function runWavAnalysis(wavFile) {
  try {
    const r = await fetch(`/api/forensics/analyze/${wavFile}`)
    if (r.ok) wavAnalysis.value = await r.json()
  } catch {}
}

async function loadCsv(name) {
  if (!name) return
  try {
    const r = await fetch(`/api/logs/${name}?limit=60`)
    if (r.ok) {
      const d = await r.json()
      csvRows.value = d.rows || []
    }
  } catch {}
}

async function inspectSource(file) {
  try {
    const r = await fetch(`/api/modules/${file}/source`)
    if (r.ok) {
      const d = await r.json()
      sourcePreview.value = `# ${d.file} (${d.size_bytes} bytes)\n\n` + (d.preview || '').slice(0, 3500)
    }
  } catch {}
}

onMounted(async () => {
  try {
    const [fRes, lRes, mRes] = await Promise.all([
      fetch('/api/forensics/summary'),
      fetch('/api/logs'),
      fetch('/api/modules'),
    ])
    if (fRes.ok) {
      const fd = await fRes.json()
      totalDetections.value = fd.total_detection_json_files || 0
      detections.value = fd.detections || []
      beaconCounts.value = fd.beacon_counts || {}
      if (detections.value.length) selectedDet.value = detections.value[0]
    }
    if (lRes.ok) {
      const ld = await lRes.json()
      logFiles.value = ld.files || []
      if (logFiles.value.length) {
        selectedCsv.value = logFiles.value[0]
        loadCsv(selectedCsv.value)
      }
    }
    if (mRes.ok) {
      const md = await mRes.json()
      modules.value = md.modules || []
    }
  } catch {}
})
</script>

<style scoped>
.p-box { padding: 14px; }
.sec-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.sec-head h3 { font-size: 15px; color: #f8fafc; }
.sub { font-size: 11.5px; color: var(--text-muted); }
.tab-bar, .beacon-pills, .log-bar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
.vault-grid { display: grid; grid-template-columns: 300px 1fr; gap: 12px; }
@media (max-width: 900px) { .vault-grid { grid-template-columns: 1fr; } }
.det-list { max-height: 290px; overflow-y: auto; display: flex; flex-direction: column; gap: 5px; }
.det-item { padding: 7px 9px; border-radius: 7px; background: rgba(15,23,42,0.7); border: 1px solid rgba(148,163,184,0.12); cursor: pointer; font-size: 11.5px; }
.det-item.active, .det-item:hover { border-color: var(--cyan); background: rgba(34,211,238,0.1); }
.det-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 3px; font-size: 10.5px; color: var(--text-muted); }
.detail-pane { background: rgba(6,9,17,0.6); border: 1px solid rgba(148,163,184,0.14); border-radius: 8px; padding: 10px; }
.det-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.wav-player { width: 100%; height: 34px; margin-bottom: 8px; }
.analysis-box { margin-bottom: 8px; font-size: 11.5px; }
.spec-img { width: 100%; max-height: 240px; object-fit: contain; border-radius: 6px; background: #000; }
.csv-scroll { max-height: 260px; overflow: auto; background: rgba(6,9,17,0.65); border-radius: 8px; padding: 8px; }
.ble-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.ble-tbl th, .ble-tbl td { padding: 4px 6px; border-bottom: 1px solid rgba(148,163,184,0.1); text-align: left; white-space: nowrap; }
.mod-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 9px; }
.mod-card { cursor: pointer; }
.mod-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.mod-title { font-weight: 600; font-size: 12.5px; margin-bottom: 3px; }
.src-box { grid-column: 1 / -1; max-height: 220px; overflow: auto; background: #05080f; padding: 10px; border-radius: 8px; border: 1px solid var(--border-subtle); font-size: 11px; color: #cbd5e1; }
</style>
