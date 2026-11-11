<template>
  <div class="arena-wrap glass-panel">
    <div class="arena-hud-top">
      <div class="hud-left">
        <span class="pill pill-cyan">3D SPATIAL ACOUSTIC & RF ARENA</span>
        <span class="pill" :class="retroActive ? 'pill-rose' : 'pill-emerald'">
          {{ retroActive ? `HETERODYNE BEAT: ${fDiff} Hz` : 'PASSIVE RETROREFLECTION' }}
        </span>
        <span class="pill pill-violet">LO: {{ loFreq }} MHz</span>
        <span class="pill pill-amber">HRTF ITD: {{ itdUs }} us</span>
        <span class="pill pill-emerald">PLUTO ANN: {{ plutoState }}</span>
      </div>
      <div class="hud-right">
        <button class="btn" :class="{ 'btn-active': showLOField }" @click="showLOField = !showLOField">LO Field</button>
        <button class="btn" :class="{ 'btn-active': showBeams }" @click="showBeams = !showBeams">Beams & HRTF</button>
        <button class="btn" @click="resetCam">Reset View</button>
      </div>
    </div>
    <div ref="canvasHost" class="arena-canvas"></div>
    <div class="arena-legend mono">
      <span><i style="background:#22d3ee"></i>f1 Sonar + CSI</span>
      <span><i style="background:#f43f5e"></i>f2 Pilot & Mid-Air Mix</span>
      <span><i style="background:#a855f7"></i>SDR LO Leakage</span>
      <span><i style="background:#f59e0b"></i>Coil Back-EMF</span>
      <span><i style="background:#10b981"></i>Delay&Sum / HRTF Target</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry } = useTelemetry()
const canvasHost = ref(null)
const showLOField = ref(true)
const showBeams = ref(true)

const retroActive = computed(() => telemetry.retro_intermod?.params?.active_transceiver_enabled)
const fDiff = computed(() => Math.round(telemetry.retro_intermod?.frequencies_hz?.f_diff_heterodyne || 0))
const loFreq = computed(() => telemetry.lo_leakage?.frequencies_mhz?.lo_fundamental_mhz || 455.3)
const itdUs = computed(() => telemetry.beamforming_hrtf?.binaural_hrtf?.itd_us || 0)
const plutoState = computed(() => telemetry.pluto_bridge?.neural_net?.predicted_state || 'STANDING')

let renderer, scene, camera, controls, animId
let observerGroup, mixSphere, loRings = [], sonarRings = [], pilotRings = []
let steerCone, hrtfTargetMesh, hrtfLine, scannerProbe, csiLine, emfPulse, plutoBeacon

function resetCam() {
  if (!camera || !controls) return
  camera.position.set(3.8, 3.2, 4.6)
  controls.target.set(0, 0.7, 1.1)
  controls.update()
}

onMounted(() => {
  const el = canvasHost.value
  scene = new THREE.Scene()
  scene.fog = new THREE.FogExp2(0x060911, 0.08)

  camera = new THREE.PerspectiveCamera(48, el.clientWidth / el.clientHeight, 0.1, 60)
  camera.position.set(3.8, 3.2, 4.6)

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setSize(el.clientWidth, el.clientHeight)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  el.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.target.set(0, 0.7, 1.1)

  scene.add(new THREE.AmbientLight(0x94a3b8, 0.9))
  const dirLight = new THREE.DirectionalLight(0x38bdf8, 1.4)
  dirLight.position.set(4, 7, 3)
  scene.add(dirLight)

  const grid = new THREE.GridHelper(10, 20, 0x1e3a5f, 0x0f172a)
  scene.add(grid)

  // Central EarArray 8-mic bar + Receive-Only SDR Chassis + Speaker Cones
  const sdrBox = new THREE.Mesh(
    new THREE.BoxGeometry(0.46, 0.14, 0.3),
    new THREE.MeshStandardMaterial({ color: 0x1e293b, emissive: 0x3b0764, emissiveIntensity: 0.5 })
  )
  sdrBox.position.set(0, 0.75, 0)
  scene.add(sdrBox)

  // ADALM-Pluto VHF Whip Antenna & Preemptive PTT Beacon
  const whip = new THREE.Mesh(
    new THREE.CylinderGeometry(0.01, 0.012, 0.55, 10),
    new THREE.MeshBasicMaterial({ color: 0x38bdf8 })
  )
  whip.position.set(-0.18, 1.08, -0.08)
  scene.add(whip)
  plutoBeacon = new THREE.Mesh(
    new THREE.SphereGeometry(0.055, 14, 14),
    new THREE.MeshBasicMaterial({ color: 0x10b981 })
  )
  plutoBeacon.position.set(-0.18, 1.38, -0.08)
  scene.add(plutoBeacon)

  for (let i = 0; i < 8; i++) {
    const mic = new THREE.Mesh(
      new THREE.CylinderGeometry(0.018, 0.018, 0.06, 12),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee })
    )
    mic.position.set((i - 3.5) * 0.065, 0.85, 0)
    scene.add(mic)
  }

  // Speaker cable + microphonics back-EMF pulse sphere
  const cablePts = [new THREE.Vector3(0.23, 0.72, 0), new THREE.Vector3(0.65, 0.05, -0.4), new THREE.Vector3(1.1, 0.05, -0.7)]
  const cableGeo = new THREE.BufferGeometry().setFromPoints(cablePts)
  scene.add(new THREE.Line(cableGeo, new THREE.LineBasicMaterial({ color: 0x64748b })))
  emfPulse = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 12), new THREE.MeshBasicMaterial({ color: 0xf59e0b }))
  scene.add(emfPulse)

  // Seated Observer (Clothing shell + Torso + Throat node + Active Transceiver)
  observerGroup = new THREE.Group()
  const clothMesh = new THREE.Mesh(
    new THREE.CylinderGeometry(0.24, 0.28, 0.68, 18),
    new THREE.MeshStandardMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.28, wireframe: true })
  )
  clothMesh.position.y = 0.65
  const torsoMesh = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.17, 0.36, 8, 16),
    new THREE.MeshStandardMaterial({ color: 0x0ea5e9, emissive: 0x0284c7, emissiveIntensity: 0.35 })
  )
  torsoMesh.position.y = 0.68
  const throatMesh = new THREE.Mesh(
    new THREE.SphereGeometry(0.065, 14, 14),
    new THREE.MeshBasicMaterial({ color: 0x34d399 })
  )
  throatMesh.position.y = 1.04
  const headMesh = new THREE.Mesh(
    new THREE.SphereGeometry(0.13, 16, 16),
    new THREE.MeshStandardMaterial({ color: 0x94a3b8 })
  )
  headMesh.position.y = 1.22
  const txRig = new THREE.Mesh(
    new THREE.ConeGeometry(0.08, 0.18, 14),
    new THREE.MeshBasicMaterial({ color: 0xf43f5e })
  )
  txRig.rotation.x = -Math.PI / 2
  txRig.position.set(0, 0.92, -0.24)
  txRig.name = 'txRig'
  observerGroup.add(clothMesh, torsoMesh, throatMesh, headMesh, txRig)
  scene.add(observerGroup)

  // Mid-air Westervelt Heterodyne Mixing Zone
  mixSphere = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.24, 2),
    new THREE.MeshBasicMaterial({ color: 0xf43f5e, wireframe: true, transparent: true, opacity: 0.85 })
  )
  scene.add(mixSphere)

  // Wavefront rings (Sonar f1, Opposing Pilot f2, SDR LO Leakage)
  for (let i = 0; i < 4; i++) {
    const r1 = new THREE.Mesh(new THREE.RingGeometry(0.18, 0.205, 32), new THREE.MeshBasicMaterial({ color: 0x22d3ee, side: THREE.DoubleSide, transparent: true, opacity: 0.6 }))
    sonarRings.push(r1); scene.add(r1)
    const r2 = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.185, 32), new THREE.MeshBasicMaterial({ color: 0xf43f5e, side: THREE.DoubleSide, transparent: true, opacity: 0.65 }))
    pilotRings.push(r2); scene.add(r2)
    const rLo = new THREE.Mesh(new THREE.RingGeometry(0.3 + i * 0.55, 0.33 + i * 0.55, 40), new THREE.MeshBasicMaterial({ color: 0xa855f7, side: THREE.DoubleSide, transparent: true, opacity: 0.3 }))
    rLo.rotation.x = -Math.PI / 2; rLo.position.y = 0.02
    loRings.push(rLo); scene.add(rLo)
  }

  // Sweeping Third-Party LO Directional Antenna Probe
  scannerProbe = new THREE.Mesh(
    new THREE.ConeGeometry(0.12, 0.32, 8),
    new THREE.MeshBasicMaterial({ color: 0xc084fc, wireframe: true })
  )
  scene.add(scannerProbe)

  // Delay-and-Sum Beam Cone + Binaural HRTF Target Coordinate
  steerCone = new THREE.Mesh(
    new THREE.ConeGeometry(0.55, 2.8, 24, 1, true),
    new THREE.MeshBasicMaterial({ color: 0x10b981, transparent: true, opacity: 0.16, side: THREE.DoubleSide })
  )
  steerCone.geometry.translate(0, -1.4, 0)
  steerCone.rotation.x = -Math.PI / 2
  steerCone.position.set(0, 0.82, 0)
  scene.add(steerCone)

  hrtfTargetMesh = new THREE.Mesh(
    new THREE.OctahedronGeometry(0.13, 1),
    new THREE.MeshBasicMaterial({ color: 0x10b981, wireframe: true })
  )
  scene.add(hrtfTargetMesh)
  hrtfLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0.82, 0), new THREE.Vector3(-1.1, 1.2, 2.4)]),
    new THREE.LineDashedMaterial({ color: 0x10b981, dashSize: 0.1, gapSize: 0.06 })
  )
  scene.add(hrtfLine)

  // 64-Subcarrier Wi-Fi CSI 3D Ribbon
  const csiGeo = new THREE.BufferGeometry().setFromPoints(Array.from({ length: 64 }, (_, i) => new THREE.Vector3((i - 32) * 0.07, 0.2, -1.6)))
  csiLine = new THREE.Line(csiGeo, new THREE.LineBasicMaterial({ color: 0x38bdf8 }))
  scene.add(csiLine)

  const onResize = () => {
    if (!el || !renderer) return
    camera.aspect = el.clientWidth / el.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(el.clientWidth, el.clientHeight)
  }
  window.addEventListener('resize', onResize)

  const clock = new THREE.Clock()
  const animate = () => {
    animId = requestAnimationFrame(animate)
    const t = clock.getElapsedTime()

    // Position Seated Observer
    const rp = telemetry.retro_intermod?.params || {}
    const obsDist = rp.observer_distance_m || 2.1
    const obsAz = ((rp.observer_azimuth_deg || 18) * Math.PI) / 180
    const ox = Math.sin(obsAz) * obsDist
    const oz = Math.cos(obsAz) * obsDist
    observerGroup.position.set(ox, 0, oz)
    observerGroup.lookAt(0, 0, 0)
    const txMesh = observerGroup.getObjectByName('txRig')
    if (txMesh) txMesh.visible = !!rp.active_transceiver_enabled

    // Animate f1 Sonar & f2 Opposing Pilot Wavefronts + Mid-Air Collision Zone
    sonarRings.forEach((r, idx) => {
      const u = ((t * 0.65 + idx * 0.25) % 1)
      r.position.set(ox * u, 0.84, oz * u)
      r.lookAt(ox, 0.84, oz)
      r.scale.setScalar(0.5 + u * 1.4)
      r.material.opacity = (1 - u) * 0.65
    })

    mixSphere.visible = !!rp.active_transceiver_enabled
    mixSphere.position.set(ox * 0.5, 0.88, oz * 0.5)
    mixSphere.scale.setScalar(0.85 + 0.22 * Math.sin(t * 9))
    mixSphere.rotation.y = t * 1.6

    pilotRings.forEach((r, idx) => {
      r.visible = !!rp.active_transceiver_enabled
      if (!r.visible) return
      const u = ((t * 0.65 + idx * 0.25) % 1)
      r.position.set(ox * (1 - u), 0.88, oz * (1 - u))
      r.lookAt(0, 0.84, 0)
      r.scale.setScalar(0.5 + u * 1.3)
      r.material.opacity = (1 - u) * 0.7
    })

    // LO Leakage Rings + Directional Scanner Probe
    const lp = telemetry.lo_leakage?.params || {}
    const sDist = lp.scanner_distance_m || 1.8
    const sAz = ((lp.scanner_azimuth_deg || -35) * Math.PI) / 180
    scannerProbe.visible = showLOField.value
    scannerProbe.position.set(Math.sin(sAz) * sDist, 0.75, Math.cos(sAz) * sDist)
    scannerProbe.lookAt(0, 0.75, 0)
    loRings.forEach((r, idx) => {
      r.visible = showLOField.value
      const s = 0.6 + ((t * 0.4 + idx * 0.25) % 1) * 2.2
      r.scale.setScalar(s)
      r.material.opacity = (1 - (s - 0.6) / 2.2) * 0.38
    })

    // Speaker Coil Microphonics Back-EMF Pulse along cable
    const uEmf = (t * 1.3) % 1
    emfPulse.position.set(0.23 + uEmf * 0.85, 0.72 * (1 - uEmf) + 0.06, -0.7 * uEmf)

    // PlutoSDR Preemptive PTT / REAPER OSC Beacon
    const precharged = telemetry.pluto_bridge?.automation_osc?.is_rf_carrier_precharged
    const armed = telemetry.pluto_bridge?.automation_osc?.is_reaper_track_armed
    plutoBeacon.material.color.setHex(precharged ? 0xf43f5e : (armed ? 0x10b981 : 0x38bdf8))
    plutoBeacon.scale.setScalar(precharged ? 1.1 + 0.35 * Math.sin(t * 12) : 0.9)

    // Delay-and-Sum Steer Cone + Binaural HRTF Target
    const bp = telemetry.beamforming_hrtf?.params || {}
    steerCone.visible = showBeams.value
    steerCone.rotation.y = -((bp.steer_azimuth_deg || 0) * Math.PI) / 180
    const tc = telemetry.beamforming_hrtf?.binaural_hrtf?.target_coord_m || { x: -1.15, y: 1.2, z: 2.4 }
    hrtfTargetMesh.visible = showBeams.value
    hrtfLine.visible = showBeams.value
    hrtfTargetMesh.position.set(tc.x, tc.y, tc.z)
    hrtfTargetMesh.rotation.y = t * 2
    hrtfLine.geometry.setFromPoints([new THREE.Vector3(0, 0.82, 0), new THREE.Vector3(tc.x, tc.y, tc.z)])
    hrtfLine.computeLineDistances()

    // Update 64-subcarrier CSI waveform
    const csi = telemetry.cross_layer?.csi_subcarriers_64 || []
    if (csi.length === 64) {
      const pos = csiLine.geometry.attributes.position
      for (let i = 0; i < 64; i++) {
        pos.setXYZ(i, (i - 32) * 0.075, 0.15 + (csi[i] - 0.7) * 0.75, -1.65)
      }
      pos.needsUpdate = true
    }

    controls.update()
    renderer.render(scene, camera)
  }
  animate()
})

onBeforeUnmount(() => {
  cancelAnimationFrame(animId)
  if (renderer) renderer.dispose()
})
</script>

<style scoped>
.arena-wrap { position: relative; height: 410px; overflow: hidden; display: flex; flex-direction: column; }
.arena-canvas { flex: 1; width: 100%; height: 100%; cursor: grab; }
.arena-hud-top { position: absolute; top: 10px; left: 12px; right: 12px; z-index: 5; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; pointer-events: none; }
.hud-left, .hud-right { display: flex; gap: 6px; flex-wrap: wrap; pointer-events: auto; }
.arena-legend { position: absolute; bottom: 8px; left: 12px; right: 12px; z-index: 5; display: flex; gap: 14px; flex-wrap: wrap; font-size: 11px; color: var(--text-muted); background: rgba(6, 9, 17, 0.72); padding: 5px 10px; border-radius: 6px; }
.arena-legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
</style>
