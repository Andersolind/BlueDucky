/**
 * ultrasonic.ts — a real data-over-sound modem for the browser.
 *
 * This is a JS port + hardening of the Python `decode_ultrasonic_signal`
 * pipeline you started from. The Python version used a ~19 kHz carrier, a
 * `10101011` preamble, and 8-bit ASCII framing. We keep the same spirit
 * (near-ultrasonic carrier band, a preamble sync marker, byte framing) but
 * swap the fragile coherent-BPSK-by-polarity scheme for multi-tone FSK
 * decoded with the Goertzel algorithm, which is far more robust to phase,
 * room reverb, and cheap laptop mics.
 *
 * Framing on the wire, one tone per symbol (symbol = one 4-bit nibble):
 *
 *   [ CALIB ][ CALIB ][ START ] n0 n1 n2 ... nk [ END ]
 *
 * - CALIB  : two lead-in tones so AGC/mic settle before real data.
 * - START  : a dedicated marker tone (the moral equivalent of the
 *            `10101011` preamble) that tells the receiver "data begins".
 * - nX     : one hex nibble per symbol. So repeated nibbles produce a
 *            *frequency change* every symbol (which clock recovery needs to
 *            see symbol edges), even and odd symbol positions draw from two
 *            disjoint 16-tone banks — the ggwave trick.
 * - END    : marker tone that closes the frame.
 *
 * Everything runs in-browser with the Web Audio API. No server, no infra.
 * The pure `synthesize()` / `decodeSamples()` functions have no DOM deps, so
 * the modem can be unit-tested via loopback (see scratchpad sim).
 */

export interface ModemConfig {
  /** Lowest data tone, Hz. ~18 kHz sits above most adult hearing. */
  baseFreq: number
  /** Spacing between adjacent tones, Hz. */
  step: number
  /** Symbol duration in seconds. Longer = slower but more robust. */
  symbolSec: number
  /** Detection threshold: dominant-tone power / total window power (0..1). */
  threshold: number
}

/**
 * MEASURED IN A REAL ROOM, not chosen for roundness. 2026-09-03, laptop speaker
 * -> room -> DMIC array at 48 kHz, swept across the whole tone grid, compared
 * against a 9-day ultrasonic occupancy profile of the same room (32,745 captures).
 *
 * The previous grid (baseFreq 18000, step 100) put its top data tones at
 * 20.8-21.1 kHz, where two independent things go wrong at once:
 *
 *   speaker roll-off   d28 21.3 dB -> d31 8.7 dB SNR. The last tone was below
 *                      any usable detection margin; d30/d31 were the two worst
 *                      of all 35 tones.
 *   the room itself    20.0-21.5 kHz is occupied by persistent emitters ~5-6%
 *                      of the time (repellers / sensors / SMPS harmonics).
 *
 * Both land on the SAME tones, and because tone index maps to nibble value, the
 * failures were not random: nibbles 0xC-0xF at odd symbol positions (bank 1)
 * were systematically the least reliable symbols in the alphabet.
 *
 * This grid spans 18150-19950 Hz instead. Every tone measured 0.0% room
 * occupancy over 9 days and 35-55 dB SNR on the same hardware. Step is 50 Hz,
 * which at symbolSec 0.06 (a 2880-sample Goertzel window, 16.7 Hz resolution)
 * leaves adjacent tones 3 bins apart - tighter than the old 6, and the reason
 * symbolSec must not be shortened without re-measuring.
 *
 * Both ends must share this config; it is the wire format.
 */
export const DEFAULT_CONFIG: ModemConfig = {
  baseFreq: 18400,
  step: 50,
  symbolSec: 0.06,
  threshold: 0.18,
}

// 16 nibble values × 2 banks = 32 data tones, plus 3 control markers.
const NIBBLES = 16
const BANKS = 2
const DATA_TONES = NIBBLES * BANKS // 32

// Marker tones live just below the data band so they never collide with data.
const MARKER_START = -2 // baseFreq - 2*step
const MARKER_END = -3 // baseFreq - 3*step
const MARKER_CALIB = -5 // baseFreq - 5*step

function toneFreq(cfg: ModemConfig, toneIndex: number): number {
  return cfg.baseFreq + toneIndex * cfg.step
}
function markerFreq(cfg: ModemConfig, marker: number): number {
  return cfg.baseFreq + marker * cfg.step
}

/** Which data tone index encodes `nibble` at symbol `position`. */
function dataTone(nibble: number, position: number): number {
  const bank = position % BANKS
  return bank * NIBBLES + nibble
}

export interface DecodeResult {
  text: string
  /** Raw nibble values recovered, for debugging / tuning. */
  nibbles: number[]
}

/* ------------------------------------------------------------------ *
 *  Goertzel — single-frequency power estimate over a sample window
 * ------------------------------------------------------------------ */

function goertzelPower(samples: ArrayLike<number>, start: number, len: number, freq: number, sr: number): number {
  const k = (freq / sr) * len
  const w = (2 * Math.PI * k) / len
  const coeff = 2 * Math.cos(w)
  let s1 = 0
  let s2 = 0
  for (let i = 0; i < len; i++) {
    const s0 = samples[start + i] + coeff * s1 - s2
    s2 = s1
    s1 = s0
  }
  return (s1 * s1 + s2 * s2 - coeff * s1 * s2) / (len * len)
}

function windowEnergy(samples: ArrayLike<number>, start: number, len: number): number {
  let e = 0
  for (let i = 0; i < len; i++) {
    const v = samples[start + i]
    e += v * v
  }
  return e / len
}

/**
 * How strongly the window is dominated by our near-ultrasonic tone band,
 * as a ratio in [0, 1]: (energy in the modem's tones) / (total window energy).
 * A clean single tone in the band reads ~0.5; broadband ambient / speech reads
 * near 0. This is what drives the sweep meter and the "live contact" trigger —
 * it's amplitude-independent, so it works the same at any mic gain.
 */
export function bandDominance(
  samples: ArrayLike<number>,
  start: number,
  len: number,
  cfg: ModemConfig,
  sr: number
): number {
  const total = windowEnergy(samples, start, len)
  if (total <= 1e-12) return 0
  let band = 0
  for (let t = 0; t < DATA_TONES; t++) band += goertzelPower(samples, start, len, toneFreq(cfg, t), sr)
  for (const m of [MARKER_START, MARKER_END, MARKER_CALIB])
    band += goertzelPower(samples, start, len, markerFreq(cfg, m), sr)
  return Math.min(1, band / total)
}

/* ------------------------------------------------------------------ *
 *  Pure encode / decode (no DOM) — the testable core
 * ------------------------------------------------------------------ */

/** Turn a UTF-8 string into the raw PCM burst for `sampleRate`. */
export function synthesize(text: string, cfg: ModemConfig, sampleRate: number, gain = 0.9): Float32Array {
  const bytes = new TextEncoder().encode(text)
  const nibbles: number[] = []
  for (const b of bytes) {
    nibbles.push((b >> 4) & 0x0f)
    nibbles.push(b & 0x0f)
  }
  const tones: number[] = [
    markerFreq(cfg, MARKER_CALIB),
    markerFreq(cfg, MARKER_CALIB),
    markerFreq(cfg, MARKER_START),
    ...nibbles.map((n, i) => toneFreq(cfg, dataTone(n, i))),
    markerFreq(cfg, MARKER_END),
  ]

  const sym = Math.round(cfg.symbolSec * sampleRate)
  const ramp = Math.min(Math.round(0.006 * sampleRate), Math.floor(sym / 3))
  const out = new Float32Array(tones.length * sym)

  tones.forEach((freq, si) => {
    const offset = si * sym
    const w = (2 * Math.PI * freq) / sampleRate
    for (let n = 0; n < sym; n++) {
      let env = 1
      if (n < ramp) env = 0.5 - 0.5 * Math.cos((Math.PI * n) / ramp)
      else if (n > sym - ramp) env = 0.5 - 0.5 * Math.cos((Math.PI * (sym - n)) / ramp)
      out[offset + n] = Math.sin(w * n) * env * gain
    }
  })
  return out
}

function decodeNibble(samples: ArrayLike<number>, start: number, len: number, position: number, sr: number, cfg: ModemConfig): number {
  const bank = position % BANKS
  let best = 0
  let bestP = -1
  for (let n = 0; n < NIBBLES; n++) {
    const p = goertzelPower(samples, start, len, toneFreq(cfg, bank * NIBBLES + n), sr)
    if (p > bestP) {
      bestP = p
      best = n
    }
  }
  return best
}

function nibblesToResult(nibbles: number[]): DecodeResult | null {
  if (nibbles.length < 2) return null
  const bytes: number[] = []
  for (let i = 0; i + 1 < nibbles.length; i += 2) bytes.push((nibbles[i] << 4) | nibbles[i + 1])
  let text: string
  try {
    text = new TextDecoder('utf-8', { fatal: false }).decode(new Uint8Array(bytes))
  } catch {
    text = bytes.map((b) => String.fromCharCode(b)).join('')
  }
  text = text.replace(/[^\x09\x0a\x0d\x20-\x7e]+$/g, '')
  if (!text.length) return null
  return { text, nibbles }
}

/**
 * Decode a complete captured buffer. Finds the START marker, aligns to the
 * symbol grid, and reads nibbles until the END marker or the buffer runs out.
 * Returns null if no frame is found. Pure — used by both the live receiver and
 * the loopback test.
 */
export function decodeSamples(samples: ArrayLike<number>, cfg: ModemConfig, sr: number): DecodeResult | null {
  const sym = Math.round(cfg.symbolSec * sr)
  const len = samples.length
  if (len < sym * 2) return null

  // 1. Coarse scan for the START marker.
  const hop = Math.max(1, Math.floor(sym / 4))
  let startIdx = -1
  for (let i = 0; i + sym <= len; i += hop) {
    const total = windowEnergy(samples, i, sym)
    if (total <= 1e-9) continue
    const p = goertzelPower(samples, i, sym, markerFreq(cfg, MARKER_START), sr) / total
    if (p > cfg.threshold) {
      startIdx = i
      break
    }
  }
  if (startIdx < 0) return null

  // 2. Fine-align: slide ±half a symbol to maximize START power.
  const fine = Math.max(1, Math.floor(sym / 16))
  let bestIdx = startIdx
  let bestP = -1
  for (let o = Math.max(0, startIdx - sym); o <= Math.min(len - sym, startIdx + sym); o += fine) {
    const total = windowEnergy(samples, o, sym)
    if (total <= 1e-9) continue
    const p = goertzelPower(samples, o, sym, markerFreq(cfg, MARKER_START), sr) / total
    if (p > bestP) {
      bestP = p
      bestIdx = o
    }
  }

  // 3. Data begins one full symbol after the START tone.
  const dataStart = bestIdx + sym
  const nibbles: number[] = []
  for (let i = dataStart, pos = 0; i + sym <= len; i += sym, pos++) {
    const total = windowEnergy(samples, i, sym)
    if (total > 1e-9) {
      const endP = goertzelPower(samples, i, sym, markerFreq(cfg, MARKER_END), sr) / total
      if (endP > cfg.threshold) break
    }
    nibbles.push(decodeNibble(samples, i, sym, pos, sr, cfg))
    if (nibbles.length > 512) break
  }
  return nibblesToResult(nibbles)
}

/* ------------------------------------------------------------------ *
 *  TRANSMITTER (Web Audio)
 * ------------------------------------------------------------------ */

export class UltrasonicTransmitter {
  private ctx: AudioContext | null = null

  private ensureCtx(): AudioContext {
    if (!this.ctx) {
      const Ctor = window.AudioContext || (window as any).webkitAudioContext
      this.ctx = new Ctor()
    }
    return this.ctx
  }

  get sampleRate(): number {
    return this.ensureCtx().sampleRate
  }

  async transmit(text: string, cfg: ModemConfig = DEFAULT_CONFIG, gain = 0.9): Promise<void> {
    const ctx = this.ensureCtx()
    if (ctx.state === 'suspended') await ctx.resume()

    const pcm = synthesize(text, cfg, ctx.sampleRate, gain)
    const buffer = ctx.createBuffer(1, pcm.length, ctx.sampleRate)
    buffer.getChannelData(0).set(pcm)

    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.connect(ctx.destination)
    src.start()
    return new Promise((resolve) => {
      src.onended = () => resolve()
    })
  }

  close() {
    this.ctx?.close()
    this.ctx = null
  }
}

/* ------------------------------------------------------------------ *
 *  RECEIVER (mic capture + framed decode)
 * ------------------------------------------------------------------ */

export interface ReceiverEvents {
  onLevel?: (bandEnergy: number) => void
  onMessage?: (result: DecodeResult) => void
  onCapture?: () => void
}

export class UltrasonicReceiver {
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private node: ScriptProcessorNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private running = false

  private cfg: ModemConfig
  private events: ReceiverEvents

  private ring: Float32Array = new Float32Array(0)
  private ringLen = 0
  private symSamples = 0

  private capturing = false
  private captureBuf: number[] = []
  private captureSamples = 0

  constructor(cfg: ModemConfig = DEFAULT_CONFIG, events: ReceiverEvents = {}) {
    this.cfg = cfg
    this.events = events
  }

  get active() {
    return this.running
  }

  async start(): Promise<void> {
    if (this.running) return

    // Mic capture requires a secure context. On http:// over a LAN IP the whole
    // `navigator.mediaDevices` object is undefined — fail with a clear message
    // instead of a cryptic "cannot read properties of undefined".
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        'Microphone unavailable — this page needs a secure context. Use http://localhost:5173 on this machine, or serve the app over HTTPS to use the mic from another device.'
      )
    }

    const Ctor = window.AudioContext || (window as any).webkitAudioContext
    this.ctx = new Ctor()
    if (this.ctx!.state === 'suspended') await this.ctx!.resume()

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        channelCount: 1,
      },
    })

    const sr = this.ctx!.sampleRate
    this.symSamples = Math.round(this.cfg.symbolSec * sr)
    this.ring = new Float32Array(this.symSamples * 3)
    this.ringLen = 0

    this.source = this.ctx!.createMediaStreamSource(this.stream)
    this.node = this.ctx!.createScriptProcessor(2048, 1, 1)
    this.node.onaudioprocess = (e) => this.process(e.inputBuffer.getChannelData(0))
    this.source.connect(this.node)
    // ScriptProcessor needs a downstream connection to fire in some browsers;
    // route through a muted gain so we don't echo the mic to the speakers.
    const sink = this.ctx!.createGain()
    sink.gain.value = 0
    this.node.connect(sink)
    sink.connect(this.ctx!.destination)

    this.running = true
  }

  async stop(): Promise<void> {
    this.running = false
    this.node?.disconnect()
    this.source?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    await this.ctx?.close()
    this.ctx = null
    this.node = null
    this.source = null
    this.stream = null
    this.capturing = false
    this.captureBuf = []
  }

  private sr(): number {
    return this.ctx ? this.ctx.sampleRate : 48000
  }

  private pushRing(chunk: Float32Array) {
    const cap = this.ring.length
    if (chunk.length >= cap) {
      this.ring.set(chunk.subarray(chunk.length - cap))
      this.ringLen = cap
      return
    }
    const shift = Math.min(this.ringLen, cap - chunk.length)
    this.ring.copyWithin(0, this.ringLen - shift, this.ringLen)
    this.ring.set(chunk, shift)
    this.ringLen = shift + chunk.length
  }

  private markerPower(marker: number): number {
    const len = this.symSamples
    if (this.ringLen < len) return 0
    const start = this.ringLen - len
    const total = windowEnergy(this.ring, start, len)
    if (total <= 1e-9) return 0
    return goertzelPower(this.ring, start, len, markerFreq(this.cfg, marker), this.sr()) / total
  }

  private process(input: Float32Array) {
    if (!this.running) return
    const chunk = new Float32Array(input) // copy — the audio thread reuses the buffer
    this.pushRing(chunk)

    // Near-ultrasonic band dominance (0..1) for the game's "sweep" meter.
    if (this.events.onLevel && this.ringLen >= this.symSamples) {
      const start = this.ringLen - this.symSamples
      this.events.onLevel(bandDominance(this.ring, start, this.symSamples, this.cfg, this.sr()))
    }

    if (!this.capturing) {
      if (this.markerPower(MARKER_START) > this.cfg.threshold) {
        // Seed the capture with recent history (the CALIB+START region) so the
        // shared decoder can re-find and fine-align on START.
        this.capturing = true
        const seed = Math.min(this.ringLen, this.symSamples * 2)
        this.captureBuf = Array.from(this.ring.subarray(this.ringLen - seed, this.ringLen))
        this.captureSamples = 0
        this.events.onCapture?.()
      }
      return
    }

    // Capturing: accumulate, finalize on END marker or timeout.
    for (let i = 0; i < chunk.length; i++) this.captureBuf.push(chunk[i])
    this.captureSamples += chunk.length

    const endSeen =
      this.captureSamples > this.symSamples * 2 && this.markerPower(MARKER_END) > this.cfg.threshold
    const timedOut = this.captureSamples > this.sr() * 4
    if (endSeen || timedOut) this.finalize()
  }

  private finalize() {
    const buf = Float32Array.from(this.captureBuf)
    this.capturing = false
    this.captureBuf = []
    this.captureSamples = 0
    const res = decodeSamples(buf, this.cfg, this.sr())
    if (res) this.events.onMessage?.(res)
  }
}
