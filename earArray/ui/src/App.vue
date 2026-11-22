<template>
  <div class="app-shell">
    <!-- Top Mission Telemetry Header -->
    <header class="top-nav glass-panel">
      <div class="brand">
        <div class="pulse-dot" :class="{ online: wsConnected }"></div>
        <div>
          <h1>EARARRAY // SPATIAL SONAR, RF, TOF CALIBRATION & HRTF TELEMETRY SUITE</h1>
          <div class="sub mono">
            Vue 3 + Three.js • Ultrasonic TOF Self-Calibration • 10m×10m Quadrant Trajectory • PlutoSDR ANN • Mid-Air Heterodyne • LO Leakage • HRTF
          </div>
        </div>
      </div>

      <div class="nav-right mono">
        <span class="pill" :class="wsConnected ? 'pill-emerald' : 'pill-amber'">
          {{ wsConnected ? `LIVE STREAM #${telemetry.tick}` : 'LOCAL ENGINE' }}
        </span>
        <span class="pill pill-cyan">{{ telemetry.timestamp }}</span>
      </div>
    </header>

    <!-- Main 3D Arena + Modular Control Deck -->
    <main class="deck-grid">
      <SpatialArena3D />
      <AudibleEnclavePanel />
      <MidAirSubvocalLearnerPanel />
      <SpatialTofCalibrationPanel />
      <PlutoNeuralPanel />
      <ReversePhysicsPanel />
      <SensingBeamformingPanel />
      <DefenseAndVehiclePanel />
      <ForensicsAndLogsVault />
    </main>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import { useTelemetry } from './composables/useTelemetry'
import SpatialArena3D from './components/SpatialArena3D.vue'
import AudibleEnclavePanel from './components/AudibleEnclavePanel.vue'
import MidAirSubvocalLearnerPanel from './components/MidAirSubvocalLearnerPanel.vue'
import SpatialTofCalibrationPanel from './components/SpatialTofCalibrationPanel.vue'
import PlutoNeuralPanel from './components/PlutoNeuralPanel.vue'
import ReversePhysicsPanel from './components/ReversePhysicsPanel.vue'
import SensingBeamformingPanel from './components/SensingBeamformingPanel.vue'
import DefenseAndVehiclePanel from './components/DefenseAndVehiclePanel.vue'
import ForensicsAndLogsVault from './components/ForensicsAndLogsVault.vue'

const { telemetry, wsConnected, connectWebSocket, stopAudioPreview } = useTelemetry()

onMounted(() => {
  connectWebSocket()
})

onBeforeUnmount(() => {
  stopAudioPreview()
})
</script>

<style scoped>
.app-shell {
  max-width: 1560px;
  margin: 0 auto;
  padding: 12px 16px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.top-nav {
  padding: 11px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand h1 {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #f8fafc;
}

.sub {
  font-size: 11px;
  color: var(--text-muted);
}

.pulse-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--amber);
  box-shadow: 0 0 10px var(--amber);
}
.pulse-dot.online {
  background: var(--emerald);
  box-shadow: 0 0 12px var(--emerald);
}

.nav-right {
  display: flex;
  gap: 8px;
  align-items: center;
}

.deck-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
</style>
