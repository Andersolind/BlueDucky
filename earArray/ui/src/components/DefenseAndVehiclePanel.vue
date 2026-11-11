<template>
  <div class="glass-panel p-box">
    <div class="sec-head">
      <div>
        <h3>Multi-Layer Ultrasonic, BLE, Vehicle & CSI Fusion</h3>
        <p class="sub">earDefence • sniitch4ears • benine4u • carDefender • 4snitichingcars (Subaru STARLINK) • toneSnicher2026</p>
      </div>
      <div class="badges">
        <span class="pill" :class="ed.status === 'ANOMALY_CONFIRMED' ? 'pill-rose' : 'pill-emerald'">{{ ed.status }}</span>
        <span class="pill pill-cyan">DOA: {{ cl.doa_deg }}° ({{ cl.tdoa_us }} us)</span>
        <span class="pill pill-amber">Gesture: {{ cl.gesture }}</span>
      </div>
    </div>

    <div class="top-cards">
      <div class="metric-card">
        <div class="k">EarDefence + Sniitch4Ears</div>
        <div class="v mono">Conf {{ (ed.svm_confidence * 100).toFixed(0) }}% • Dir {{ ed.direction }}</div>
        <div class="tiny mono">Imbalance {{ ed.imbalance_ratio }}x • Corr {{ ed.correlation }} • {{ ed.temporal_consistency }}</div>
      </div>

      <div class="metric-card">
        <div class="k">Benine4u Replay Detector</div>
        <div class="v mono">{{ rp.verdict }}</div>
        <div class="tiny mono">Carrier {{ rp.carrier_hz }} Hz • Mod {{ rp.modulation_depth }} • THD {{ (rp.thd_ratio * 100).toFixed(1) }}%</div>
      </div>

      <div class="metric-card">
        <div class="k">MotionDeluxe CSI + SHA1 Fingerprint</div>
        <div class="v mono">CSI Motion {{ cl.csi_motion }} @ {{ cl.csi_rate_hz }} Hz</div>
        <div class="tiny mono">SHA1: {{ cl.fp_hash }} • HF-Z: {{ cl.hf_z }}</div>
      </div>

      <div class="metric-card">
        <div class="k">Subaru STARLINK / Vehicle Transducers</div>
        <div class="v mono">Harman Kardon 576W (12-spk)</div>
        <div class="tiny mono">40-48 kHz Sensors: {{ vb.parking_sensor_40_48khz ? 'ACTIVE' : 'IDLE' }} • Tweeter {{ vb.speaker_resonances_db?.dash_tweeter }} dB</div>
      </div>
    </div>

    <div class="bottom-split">
      <!-- BLE + Live Listen + Subaru Table -->
      <div class="ble-table-wrap">
        <div class="mini-title">BLE Distance, Live Listen A2DP & Vehicle OUI Scanner</div>
        <table class="ble-tbl mono">
          <thead>
            <tr>
              <th>Device</th>
              <th>Type / System</th>
              <th>Dist</th>
              <th>RSSI</th>
              <th>LiveListen</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in vb.devices" :key="d.address">
              <td>{{ d.name }}</td>
              <td><span class="pill" :class="riskClass(d.risk_level)">{{ d.device_type }}</span> {{ d.gen }}</td>
              <td>{{ d.distance_m }}m</td>
              <td>{{ d.rssi }}dBm</td>
              <td>{{ Math.round(d.live_listen_score * 100) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 16-Band Audio Fingerprint + Active Cross-Layer Rules -->
      <div class="fp-col">
        <div class="mini-title">16-Band Geometric Audio Fingerprint & Active Cross-Layer Rules</div>
        <div class="bars-16">
          <div v-for="(b, idx) in cl.bands_16" :key="idx" class="b-col">
            <div class="b-fill" :style="{ height: `${Math.min(100, b * 650)}%` }"></div>
          </div>
        </div>
        <div class="rules-wrap">
          <span v-for="r in cl.active_rules" :key="r" class="pill pill-cyan">{{ r }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry } = useTelemetry()
const ed = computed(() => telemetry.ear_defence || {})
const rp = computed(() => telemetry.replay_detector || {})
const vb = computed(() => telemetry.vehicle_ble || { devices: [] })
const cl = computed(() => telemetry.cross_layer || { bands_16: [], active_rules: [] })

function riskClass(r) {
  if (r === 'HIGH') return 'pill-rose'
  if (r === 'MEDIUM') return 'pill-amber'
  return 'pill-emerald'
}
</script>

<style scoped>
.p-box { padding: 14px; }
.sec-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.sec-head h3 { font-size: 15px; color: #f8fafc; }
.sub { font-size: 11.5px; color: var(--text-muted); }
.badges { display: flex; gap: 6px; flex-wrap: wrap; }
.top-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 9px; margin-bottom: 12px; }
.k { font-size: 11px; color: var(--text-muted); }
.v { font-size: 12.5px; font-weight: 600; margin: 3px 0; color: #f1f5f9; }
.tiny { font-size: 10.5px; color: var(--text-dim); }
.bottom-split { display: grid; grid-template-columns: 1.35fr 1fr; gap: 12px; }
@media (max-width: 900px) { .bottom-split { grid-template-columns: 1fr; } }
.mini-title { font-size: 11.5px; font-weight: 600; color: #94a3b8; margin-bottom: 6px; }
.ble-table-wrap { overflow-x: auto; background: rgba(6, 9, 17, 0.55); border-radius: 8px; padding: 8px; border: 1px solid rgba(148,163,184,0.12); }
.ble-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.ble-tbl th { text-align: left; color: var(--text-dim); padding-bottom: 5px; border-bottom: 1px solid rgba(148,163,184,0.15); }
.ble-tbl td { padding: 5px 4px; border-bottom: 1px solid rgba(148,163,184,0.07); }
.fp-col { background: rgba(6, 9, 17, 0.55); border-radius: 8px; padding: 8px 10px; border: 1px solid rgba(148,163,184,0.12); display: flex; flex-direction: column; justify-content: space-between; }
.bars-16 { display: flex; align-items: flex-end; gap: 4px; height: 74px; padding: 6px 0; }
.b-col { flex: 1; height: 100%; background: rgba(30,41,59,0.5); border-radius: 3px; display: flex; align-items: flex-end; overflow: hidden; }
.b-fill { width: 100%; background: linear-gradient(180deg, #22d3ee, #3b82f6); border-radius: 3px; transition: height 0.18s ease; }
.rules-wrap { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 6px; }
</style>
