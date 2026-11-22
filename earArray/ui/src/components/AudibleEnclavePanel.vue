<template>
  <section class="glass-panel enclave-panel">
    <div class="panel-header">
      <div>
        <div class="section-title">
          00 // SELF-BENDING ULTRASONIC AUDIBLE ENCLAVE &amp; 7-LAYER TACTICAL AUDIO PROTOTYPE
        </div>
        <h2>
          Nonlinear Metasurface Enclaves (`f₁={{ (freq.f1_ultrasonic_hz / 1000).toFixed(1) }}kHz`, `f₂={{ (freq.f2_ultrasonic_hz / 1000).toFixed(1) }}kHz`) • 20kHz Vocal Sonar • 100m GPS FHSS • LMS Echo Null • 250/261Hz (11Hz Alpha) Loop • Wall-Bounce TOF • 24kHz Goertzel • SQLite Journal
        </h2>
      </div>
      <div class="header-badges">
        <span class="pill pill-emerald mono">ENCLAVE: {{ em.peak_enclave_spl_db }} dB (+{{ em.privacy_isolation_db }} dB ISO)</span>
        <span class="pill pill-cyan mono">FHSS: {{ fhss.grid_square_id }} ({{ fhss.current_hop_freq_hz }} Hz)</span>
        <span class="pill pill-violet mono">ALPHA LOOP: {{ cog.left_ear_carrier_hz }}/{{ cog.right_ear_carrier_hz }} Hz → {{ cog.binaural_beat_hz }} Hz</span>
        <span class="pill pill-amber mono">SQLITE ROWS: {{ db.total_committed_rows }} ({{ db.priority_level }})</span>
      </div>
    </div>

    <div class="enclave-grid">
      <!-- Card 1: Self-Bending Ultrasonic Beam Trajectories & Obstacle Bypass Map -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">1. SELF-BENDING ULTRASONIC TRAJECTORIES &amp; OBSTACLE BYPASS</span>
          <span class="mono val-emerald">Beat f₂−f₁ = {{ freq.audible_enclave_beat_hz }} Hz</span>
        </div>

        <svg viewBox="0 0 320 185" class="field-svg">
          <line x1="160" y1="10" x2="160" y2="175" stroke="rgba(148,163,184,0.14)" stroke-dasharray="3 3" />
          <line x1="20" y1="95" x2="300" y2="95" stroke="rgba(148,163,184,0.14)" stroke-dasharray="3 3" />

          <!-- Dual Ultrasound Sources + 3D-Printed Metasurfaces at z = 0 -->
          <rect x="68" y="8" width="52" height="8" rx="2" fill="#334155" stroke="#94a3b8" stroke-width="1" />
          <rect x="68" y="17" width="52" height="5" rx="1" fill="#eab308" />
          <text x="64" y="31" fill="#fde047" font-size="7.5" font-family="monospace">Metasurface 1 (f₁)</text>

          <rect x="200" y="8" width="52" height="8" rx="2" fill="#334155" stroke="#94a3b8" stroke-width="1" />
          <rect x="200" y="17" width="52" height="5" rx="1" fill="#10b981" />
          <text x="196" y="31" fill="#34d399" font-size="7.5" font-family="monospace">Metasurface 2 (f₂)</text>

          <!-- Blocked Conventional Straight Line-of-Sight -->
          <line
            v-if="ob.obstacle_enabled"
            x1="160"
            y1="20"
            :x2="mapX(em.target_coord_m.x)"
            :y2="mapZ(em.target_coord_m.z)"
            stroke="rgba(244,63,94,0.45)"
            stroke-width="1.2"
            stroke-dasharray="4 3"
          />

          <!-- Self-Bending Ultrasonic Beam 1 & Beam 2 -->
          <polyline :points="beamPolyline(1)" fill="none" stroke="rgba(250,204,21,0.3)" stroke-width="14" stroke-linecap="round" />
          <polyline :points="beamPolyline(1)" fill="none" stroke="#facc15" stroke-width="2.2" />

          <polyline :points="beamPolyline(2)" fill="none" stroke="rgba(16,185,129,0.3)" stroke-width="14" stroke-linecap="round" />
          <polyline :points="beamPolyline(2)" fill="none" stroke="#10b981" stroke-width="2.2" />

          <!-- Central Obstacle (Human Head / Mannequin blocking direct path) -->
          <g v-if="ob.obstacle_enabled">
            <circle
              :cx="mapX(ob.obstacle_x_m)"
              :cy="mapZ(ob.obstacle_z_m)"
              :r="Math.max(12, ob.obstacle_radius_cm * 2.1)"
              fill="rgba(30,41,59,0.92)"
              stroke="#64748b"
              stroke-width="1.5"
            />
            <text :x="mapX(ob.obstacle_x_m) - 21" :y="mapZ(ob.obstacle_z_m) + 3" fill="#e2e8f0" font-size="7.5" font-family="monospace">
              HEAD OBSTACLE
            </text>
          </g>

          <!-- Audible Enclave Intersection Zone (f2 - f1) -->
          <circle
            :cx="mapX(em.target_coord_m.x)"
            :cy="mapZ(em.target_coord_m.z)"
            r="19"
            fill="rgba(244,63,94,0.22)"
            stroke="#f43f5e"
            stroke-width="1.5"
            stroke-dasharray="3 2"
          />
          <circle :cx="mapX(em.target_coord_m.x)" :cy="mapZ(em.target_coord_m.z)" r="8" fill="#f43f5e" />
          <text
            :x="Math.min(215, mapX(em.target_coord_m.x) + 12)"
            :y="mapZ(em.target_coord_m.z) + 3"
            fill="#fda4af"
            font-size="8"
            font-family="monospace"
            font-weight="bold"
          >
            AUDIBLE ENCLAVE ({{ em.peak_enclave_spl_db }} dB)
          </text>

          <g v-if="enc.mode === 'MULTI_TRACK_CROWD' && em.secondary_coord_m">
            <circle
              :cx="mapX(em.secondary_coord_m.x)"
              :cy="mapZ(em.secondary_coord_m.z)"
              r="14"
              fill="rgba(56,189,248,0.22)"
              stroke="#38bdf8"
              stroke-width="1.4"
            />
            <circle :cx="mapX(em.secondary_coord_m.x)" :cy="mapZ(em.secondary_coord_m.z)" r="6" fill="#38bdf8" />
            <text :x="mapX(em.secondary_coord_m.x) - 32" :y="mapZ(em.secondary_coord_m.z) + 18" fill="#7dd3fc" font-size="7.5" font-family="monospace">
              Track 2 ({{ freq.secondary_enclave_beat_hz }} Hz)
            </text>
          </g>

          <text x="22" y="88" fill="#94a3b8" font-size="7.5" font-family="monospace">🔇 Inaudible f₁</text>
          <text x="235" y="88" fill="#94a3b8" font-size="7.5" font-family="monospace">🔇 Inaudible f₂</text>
        </svg>

        <div class="ctrl-group">
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Beam 1 Ultrasonic Carrier f₁ (Hz)</span>
              <span class="val">{{ enc.params.f1_carrier_hz }} Hz</span>
            </div>
            <input type="range" min="36000" max="44000" step="100" :value="enc.params.f1_carrier_hz"
              @input="e => updateCfg({ f1_carrier_hz: +e.target.value })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Beam 2 Ultrasonic Carrier f₂ (Hz) → Beat {{ freq.audible_enclave_beat_hz }} Hz</span>
              <span class="val">{{ enc.params.f2_carrier_hz }} Hz</span>
            </div>
            <input type="range" min="35000" max="43000" step="100" :value="enc.params.f2_carrier_hz"
              @input="e => updateCfg({ f2_carrier_hz: +e.target.value })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Metasurface Self-Bending Curvature (Airy Caustic)</span>
              <span class="val">{{ enc.params.bend_curvature }}</span>
            </div>
            <input type="range" min="0.20" max="1.50" step="0.04" :value="enc.params.bend_curvature"
              @input="e => updateCfg({ bend_curvature: +e.target.value })" />
          </div>
          <div class="ctrl-row two-col">
            <div>
              <div class="ctrl-label">
                <span>Target Lateral X (m)</span>
                <span class="val">{{ enc.params.target_x_m }} m</span>
              </div>
              <input type="range" min="-0.35" max="0.35" step="0.02" :value="enc.params.target_x_m"
                @input="e => updateCfg({ target_x_m: +e.target.value })" />
            </div>
            <div>
              <div class="ctrl-label">
                <span>Target Axial Z (m)</span>
                <span class="val">{{ enc.params.target_z_m }} m</span>
              </div>
              <input type="range" min="0.55" max="1.20" step="0.03" :value="enc.params.target_z_m"
                @input="e => updateCfg({ target_z_m: +e.target.value })" />
            </div>
          </div>
        </div>
      </div>

      <!-- Card 2: 3D-Printed Metasurface Phase Lens & 6-Octave Ultrabroadband Response -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">2. 3D-PRINTED METASURFACE PHASE &amp; 6-OCTAVE RESPONSE</span>
          <span class="mono val-cyan">{{ ms.num_channels }}ch • Pitch {{ ms.subwavelength_pitch_mm }} mm</span>
        </div>

        <div class="metric-strip mono">
          <div class="m-item">
            <span class="m-lbl">Airy Scale x₀</span>
            <span class="val-cyan">{{ ms.airy_scale_x0_mm }} mm</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">Carrier λ₁ / λ₂</span>
            <span class="val-emerald">{{ ms.wavelength_f1_mm }} / {{ ms.wavelength_f2_mm }} mm</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">Mid-Beam Leak</span>
            <span class="val-amber">{{ em.beam_path_audible_leak_db }} dB (Silent)</span>
          </div>
        </div>

        <svg viewBox="0 0 300 74" class="wave-svg">
          <line x1="0" y1="37" x2="300" y2="37" stroke="rgba(148,163,184,0.18)" stroke-dasharray="3 2" />
          <polyline :points="phasePoints(ms.phase_f1_rad, 300, 74)" fill="none" stroke="#facc15" stroke-width="1.8" />
          <polyline :points="phasePoints(ms.phase_f2_rad, 300, 74)" fill="none" stroke="#10b981" stroke-width="1.6" stroke-dasharray="3 2" />
          <text x="8" y="13" fill="#cbd5e1" font-size="8" font-family="monospace">
            Metasurface Wrapped Cubic Phase φ₁(x) [Yellow] &amp; φ₂(x) [Emerald] (0..2π rad)
          </text>
        </svg>

        <div class="octave-box">
          <div class="octave-title mono">
            <span>ULTRABROADBAND ENCLAVE SPECTRUM ({{ oct.bandwidth_label }})</span>
            <span class="val-emerald">Westervelt ∂²(p₁p₂)/∂t²</span>
          </div>
          <div class="octave-bars mono">
            <div v-for="(fOct, idx) in oct.octave_freqs_hz" :key="fOct" class="oct-col">
              <div class="oct-val">{{ (oct.enclave_spl_db[idx] || 58).toFixed(0) }}dB</div>
              <div class="oct-track">
                <div
                  class="oct-fill"
                  :style="{ height: `${Math.min(100, Math.max(12, ((oct.enclave_spl_db[idx] || 55) - 20) * 1.6))}%` }"
                ></div>
              </div>
              <div class="oct-lbl">{{ fOct >= 1000 ? `${fOct / 1000}k` : fOct }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Card 3: Operating Modes, Active Noise Cancellation & Live Audio/WAV Prototype -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">3. ENCLAVE MODES, ACTIVE NOISE CANCELLATION &amp; AUDIO</span>
          <span class="mono val-amber">{{ enc.mode }}</span>
        </div>

        <div class="mode-btn-row">
          <button
            class="btn"
            :class="{ 'btn-active': enc.mode === 'PRIVATE_ENCLAVE' }"
            @click="updateCfg({ mode: 'PRIVATE_ENCLAVE' })"
          >
            🎯 Private Enclave
          </button>
          <button
            class="btn"
            :class="{ 'btn-active': enc.mode === 'MULTI_TRACK_CROWD' }"
            @click="updateCfg({ mode: 'MULTI_TRACK_CROWD' })"
          >
            👥 Multi-Track Crowd
          </button>
          <button
            class="btn"
            :class="{ 'btn-active': enc.mode === 'ACTIVE_NOISE_CANCEL' }"
            @click="updateCfg({ mode: 'ACTIVE_NOISE_CANCEL' })"
          >
            🛡️ Active Noise Cancel
          </button>
        </div>

        <div class="ctrl-group">
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Obstacle in Direct Path (Head / Partition)</span>
              <button
                class="btn btn-xs"
                :class="{ 'btn-active': ob.obstacle_enabled }"
                @click="updateCfg({ obstacle_enabled: !ob.obstacle_enabled })"
              >
                {{ ob.obstacle_enabled ? 'OBSTACLE PRESENT' : 'OPEN AIR' }}
              </button>
            </div>
          </div>

          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>ANC Destructive Phase Angle (180° = Anti-Noise Null)</span>
              <span class="val">{{ enc.params.anc_phase_align_deg }}°</span>
            </div>
            <input
              type="range"
              min="0"
              max="360"
              step="5"
              :value="enc.params.anc_phase_align_deg"
              @input="e => updateCfg({ mode: 'ACTIVE_NOISE_CANCEL', anc_phase_align_deg: +e.target.value })"
            />
          </div>
        </div>

        <div class="anc-summary mono">
          <div>
            <span class="m-lbl">Ambient Noise:</span>
            <span class="val-amber">{{ anc.ambient_noise_spl_db }} dB SPL</span>
          </div>
          <div>
            <span class="m-lbl">Residual at Ear:</span>
            <span class="val-emerald">{{ anc.residual_enclave_spl_db }} dB SPL</span>
          </div>
          <div>
            <span class="m-lbl">ANC Null Depth:</span>
            <span class="val-cyan">-{{ anc.anc_suppression_db }} dB</span>
          </div>
        </div>

        <div class="audio-actions">
          <button
            class="btn"
            :class="{ 'btn-active': audioPreviewMode === 'enclave_inside' }"
            @click="toggleAudioPreview('enclave_inside')"
          >
            🔊 {{ audioPreviewMode === 'enclave_inside' ? 'Stop Inside Preview' : 'Listen Inside Enclave (Target Ear)' }}
          </button>
          <button
            class="btn"
            :class="{ 'btn-active': audioPreviewMode === 'enclave_outside' }"
            @click="toggleAudioPreview('enclave_outside')"
          >
            🔇 {{ audioPreviewMode === 'enclave_outside' ? 'Stop Outside Preview' : 'Listen 22cm Outside (Bystander)' }}
          </button>
          <button class="btn btn-emerald" @click="exportWavs" :disabled="exporting">
            💾 {{ exporting ? 'Synthesizing 192kHz & 48kHz WAVs...' : 'Export 192kHz + 48kHz Enclave & Alpha WAVs' }}
          </button>
        </div>

        <div v-if="wavResult" class="wav-toast mono">
          <div>✅ 192kHz Carriers: {{ wavResult.ultrasonic_wav.split('/').pop() }}</div>
          <div>✅ 48kHz In/Out Audio: {{ wavResult.audible_comparison_wav.split('/').pop() }}</div>
          <div v-if="wavResult.binaural_alpha_wav">✅ 48kHz 11Hz Alpha: {{ wavResult.binaural_alpha_wav.split('/').pop() }}</div>
        </div>
      </div>

      <!-- Card 4: Non-Contact 20 kHz Vocal Reconstruction + Adaptive LMS Echo Cancellation + 100m GPS FHSS -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">4. 20kHz NON-CONTACT VOCAL SONAR, LMS ECHO NULL &amp; 100m GPS FHSS</span>
          <span class="mono val-emerald">ERLE -{{ vocLms.erle_suppression_db }} dB</span>
        </div>

        <div class="metric-strip mono">
          <div class="m-item">
            <span class="m-lbl">20kHz Throat Disp</span>
            <span class="val-cyan">{{ voc.throat_displacement_mm }} mm ({{ voc.throat_displacement_um }} µm)</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">LMS TV Clutter Null</span>
            <span class="val-emerald">{{ vocLms.tv_background_spl_db }}→{{ vocLms.residual_clutter_spl_db }} dB</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">100m Grid Lock</span>
            <span :class="fhss.observer_inside_100m_grid ? 'val-emerald' : 'val-rose'">
              {{ fhss.observer_inside_100m_grid ? `IN GRID (${fhss.observer_distance_m}m)` : `OUTSIDE (${fhss.observer_distance_m}m)` }}
            </span>
          </div>
        </div>

        <div class="anc-summary mono">
          <div>
            <span class="m-lbl">GPS Grid:</span>
            <span class="val-cyan">{{ fhss.grid_square_id }}</span>
          </div>
          <div>
            <span class="m-lbl">Hop Rate:</span>
            <span class="val-amber">{{ fhss.hop_rate_hz }} hops/s (+{{ fhss.processing_gain_db }} dB)</span>
          </div>
        </div>

        <div class="ctrl-group">
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Sub-Millimeter Throat Movement (20 kHz Active Sonar)</span>
              <span class="val">{{ enc.params.throat_disp_mm }} mm</span>
            </div>
            <input type="range" min="0.02" max="0.45" step="0.02" :value="enc.params.throat_disp_mm"
              @input="e => updateCfg({ throat_disp_mm: +e.target.value })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Smart-TV / Room Noise Clutter Level (LMS Input)</span>
              <span class="val">{{ enc.params.tv_noise_spl_db }} dB SPL</span>
            </div>
            <input type="range" min="50" max="85" step="1" :value="enc.params.tv_noise_spl_db"
              @input="e => updateCfg({ tv_noise_spl_db: +e.target.value })" />
          </div>
          <div class="ctrl-row">
            <div class="ctrl-label">
              <span>Observer Geodetic Position vs. 100m Grid Square</span>
              <button
                class="btn btn-xs"
                :class="{ 'btn-active': fhss.observer_inside_100m_grid }"
                @click="toggleGridObserver"
              >
                {{ fhss.observer_inside_100m_grid ? 'INSIDE 100m GRID (SYNCED)' : 'OUTSIDE 100m GRID (NOISE FLOOR)' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Card 5: Cognitive Loop Delivery (250/261 Hz -> 11 Hz Alpha) & Living-Room Wall-Bounce TOF -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">5. COGNITIVE ALPHA LOOP (250/261Hz) &amp; WALL-BOUNCE TOF</span>
          <span class="mono val-cyan">{{ cog.binaural_beat_hz }} Hz Alpha Beat</span>
        </div>

        <div class="metric-strip mono">
          <div class="m-item">
            <span class="m-lbl">Dichotic Carriers</span>
            <span class="val-cyan">{{ cog.left_ear_carrier_hz }}Hz (L) / {{ cog.right_ear_carrier_hz }}Hz (R)</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">Target Ear Skew</span>
            <span class="val-emerald">{{ wb.target_phase_alignment_skew_ms }} ms (Converged)</span>
          </div>
          <div class="m-item">
            <span class="m-lbl">Couch Bystander</span>
            <span class="val-amber">{{ wb.couch_bystander_skew_ms }} ms (Disjointed)</span>
          </div>
        </div>

        <div class="table-mini mono">
          <div v-for="s in wb.multipath_streams" :key="s.path_name" class="t-row">
            <span class="val-cyan">{{ s.path_name.replace('_BOUNCE', '') }}</span>
            <span>Pre-Delay: +{{ s.pre_delay_compensation_ms }}ms</span>
            <span class="val-emerald">Target: {{ s.arrival_at_target_ms }}ms</span>
          </div>
        </div>

        <button
          class="btn"
          :class="{ 'btn-active': audioPreviewMode === 'binaural_alpha' }"
          @click="toggleAudioPreview('binaural_alpha')"
        >
          🧠 {{ audioPreviewMode === 'binaural_alpha' ? 'Stop 11Hz Alpha Binaural Stream' : 'Listen 250Hz / 261Hz Stereo (11 Hz Alpha Monologue)' }}
        </button>
      </div>

      <!-- Card 6: Wideband 0-24,000 Hz Parallel Goertzel Interceptor & Priority SQLite Journal -->
      <div class="sub-card">
        <div class="card-head">
          <span class="card-tag">6. 24kHz PARALLEL GOERTZEL DECODER &amp; SQLITE JOURNAL</span>
          <span class="mono val-amber">Nyquist {{ gz.nyquist_limit_hz }} Hz</span>
        </div>

        <div class="mode-btn-row">
          <button
            class="btn"
            :class="{ 'btn-active': gz.active_preset === 'KEYPAD_BURST' }"
            @click="triggerIntercept('KEYPAD_BURST')"
          >
            🔢 Keypad DTMF
          </button>
          <button
            class="btn"
            :class="{ 'btn-active': gz.active_preset === 'FAX_HANDSHAKE' }"
            @click="triggerIntercept('FAX_HANDSHAKE')"
          >
            📠 Fax T.30/V.21
          </button>
          <button
            class="btn"
            :class="{ 'btn-active': gz.active_preset === 'ULTRASONIC_PAYLOAD' }"
            @click="triggerIntercept('ULTRASONIC_PAYLOAD')"
          >
            📡 22.8kHz FSK
          </button>
        </div>

        <div class="decoded-box mono">
          <div class="m-lbl">GOERTZEL DECODED PLAIN-TEXT PAYLOAD ({{ gz.transmission_type }}):</div>
          <div class="val-emerald">{{ gz.decoded_plain_text }}</div>
        </div>

        <div class="anc-summary mono">
          <div>
            <span class="m-lbl">SQLite Gate:</span>
            <span class="val-cyan">{{ db.last_trigger_reason }}</span>
          </div>
          <div>
            <span class="m-lbl">Written / Throttled:</span>
            <span class="val-amber">{{ db.total_committed_rows }} / {{ db.throttled_routine_ticks }}</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useTelemetry } from '../composables/useTelemetry'

const { telemetry, audioPreviewMode, postAudibleEnclave, toggleAudioPreview } = useTelemetry()

const exporting = ref(false)
const wavResult = ref(null)

const enc = computed(() => telemetry.audible_enclave || {})
const freq = computed(() => enc.value.frequencies_hz || {})
const em = computed(() => enc.value.enclave_metrics || { target_coord_m: { x: 0, y: 1.2, z: 0.85 } })
const ob = computed(() => enc.value.obstacle_bypass || {})
const anc = computed(() => enc.value.active_noise_cancellation || {})
const oct = computed(() => enc.value.ultrabroadband_octaves || { octave_freqs_hz: [], enclave_spl_db: [] })
const ms = computed(() => enc.value.metasurface || { phase_f1_rad: [], phase_f2_rad: [] })
const traj = computed(() => enc.value.trajectories || { z_m: [], beam1_x_m: [], beam2_x_m: [] })

const ts = computed(() => enc.value.tactical_stack || {})
const voc = computed(() => ts.value.non_contact_vocal_lms || {})
const vocLms = computed(() => voc.value.lms_echo_canceller || {})
const fhss = computed(() => ts.value.fhss_anti_intercept || {})
const cog = computed(() => ts.value.cognitive_loop_binaural || {})
const wb = computed(() => ts.value.wall_bounce_targeting || { multipath_streams: [] })
const gz = computed(() => ts.value.wideband_goertzel_intercept || {})
const db = computed(() => ts.value.sqlite_spatial_journal || {})

function mapX(xMeters) {
  return 160 + (xMeters / 0.55) * 140
}

function mapZ(zMeters) {
  return 20 + (zMeters / 1.30) * 152
}

function beamPolyline(which) {
  const zs = traj.value.z_m || []
  const xs = which === 1 ? (traj.value.beam1_x_m || []) : (traj.value.beam2_x_m || [])
  if (!zs.length || !xs.length) return ''
  return zs
    .map((z, i) => `${mapX(xs[i] ?? 0).toFixed(1)},${mapZ(z).toFixed(1)}`)
    .join(' ')
}

function phasePoints(arr, w, h) {
  if (!arr || !arr.length) {
    return Array.from({ length: 24 }, (_, i) => {
      const x = (i / 23) * w
      const y = h / 2 - Math.sin(i * 0.45) * (h * 0.35)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
  }
  return arr
    .map((v, i) => {
      const x = (i / Math.max(1, arr.length - 1)) * w
      const y = h - 8 - (v / (2 * Math.PI)) * (h - 22)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

async function updateCfg(patch) {
  await postAudibleEnclave('config', patch)
}

async function toggleGridObserver() {
  const inside = fhss.value.observer_inside_100m_grid
  if (inside) {
    // Move observer ~260m away outside the 100m grid square
    await updateCfg({ observer_lat_deg: 40.7960, observer_lon_deg: -77.8625 })
  } else {
    // Return observer inside the 100m grid square (~24m away)
    await updateCfg({ observer_lat_deg: 40.7936, observer_lon_deg: -77.8599 })
  }
}

async function triggerIntercept(preset) {
  await postAudibleEnclave('intercept', { preset })
}

async function exportWavs() {
  exporting.value = true
  try {
    const res = await postAudibleEnclave('export-wav', { duration_s: 2.5 })
    if (res && res.ok) {
      wavResult.value = res
    }
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.enclave-panel {
  padding: 14px 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.header-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.enclave-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 1180px) {
  .enclave-grid {
    grid-template-columns: 1fr;
  }
}

.sub-card {
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}

.card-tag {
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: 0.03em;
}

.field-svg {
  width: 100%;
  height: 175px;
  background: radial-gradient(circle at 50% 62%, rgba(244, 63, 94, 0.08), rgba(2, 6, 23, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 6px;
}

.wave-svg {
  width: 100%;
  height: 74px;
  background: rgba(2, 6, 23, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 6px;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  background: rgba(2, 6, 23, 0.55);
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 10.5px;
}

.m-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.m-lbl {
  color: #94a3b8;
  font-size: 9.5px;
}

.ctrl-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ctrl-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.ctrl-row.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.ctrl-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10.5px;
  color: #cbd5e1;
}

.octave-box {
  background: rgba(2, 6, 23, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 6px;
  padding: 8px 10px;
}

.octave-title {
  display: flex;
  justify-content: space-between;
  font-size: 9.5px;
  color: #94a3b8;
  margin-bottom: 6px;
}

.octave-bars {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  align-items: end;
  height: 78px;
}

.oct-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  gap: 3px;
  font-size: 9px;
}

.oct-val {
  color: #38bdf8;
  font-size: 8.5px;
}

.oct-track {
  flex: 1;
  width: 16px;
  background: rgba(30, 41, 59, 0.8);
  border-radius: 3px;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
}

.oct-fill {
  width: 100%;
  background: linear-gradient(180deg, #f43f5e, #f59e0b, #10b981);
  border-radius: 3px;
}

.oct-lbl {
  color: #94a3b8;
}

.mode-btn-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.anc-summary {
  display: flex;
  justify-content: space-between;
  background: rgba(2, 6, 23, 0.6);
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 10.5px;
}

.table-mini {
  background: rgba(2, 6, 23, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 6px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 10px;
}

.t-row {
  display: flex;
  justify-content: space-between;
  color: #cbd5e1;
}

.decoded-box {
  background: rgba(2, 6, 23, 0.72);
  border: 1px solid rgba(16, 185, 129, 0.28);
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 10.5px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.audio-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.btn-emerald {
  border-color: rgba(16, 185, 129, 0.5);
  color: #34d399;
}

.btn-xs {
  padding: 2px 7px;
  font-size: 9.5px;
}

.wav-toast {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.35);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 10px;
  color: #a7f3d0;
}

.val-cyan { color: #22d3ee; }
.val-emerald { color: #34d399; }
.val-amber { color: #fbbf24; }
.val-rose { color: #fb7185; }
</style>
