/**
 * Tiny WebAudio sound-effects kit — short synthesized blips for game events.
 * Separate from the ultrasonic modem; audible-range and deliberately minimal.
 */

let muted = false
let ctx: AudioContext | null = null

export function setMuted(m: boolean) {
  muted = m
}
export function isMuted() {
  return muted
}

function ac(): AudioContext {
  if (!ctx) {
    const Ctor = window.AudioContext || (window as any).webkitAudioContext
    ctx = new Ctor()
  }
  if (ctx.state === 'suspended') ctx.resume()
  return ctx
}

function beep(freq: number, dur: number, type: OscillatorType, when: number, gain = 0.14) {
  const c = ac()
  const t0 = c.currentTime + when
  const osc = c.createOscillator()
  const g = c.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(freq, t0)
  g.gain.setValueAtTime(0, t0)
  g.gain.linearRampToValueAtTime(gain, t0 + 0.008)
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur)
  osc.connect(g)
  g.connect(c.destination)
  osc.start(t0)
  osc.stop(t0 + dur + 0.02)
}

function sweepTone(f0: number, f1: number, dur: number, when: number, gain = 0.1) {
  const c = ac()
  const t0 = c.currentTime + when
  const osc = c.createOscillator()
  const g = c.createGain()
  osc.type = 'sawtooth'
  osc.frequency.setValueAtTime(f0, t0)
  osc.frequency.exponentialRampToValueAtTime(f1, t0 + dur)
  g.gain.setValueAtTime(gain, t0)
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur)
  osc.connect(g)
  g.connect(c.destination)
  osc.start(t0)
  osc.stop(t0 + dur + 0.02)
}

export type Sfx =
  | 'roll'
  | 'move'
  | 'buy'
  | 'rent'
  | 'intel'
  | 'sweep'
  | 'jail'
  | 'bust'
  | 'accuse'
  | 'win'
  | 'lose'

export function sfx(kind: Sfx) {
  if (muted) return
  try {
    switch (kind) {
      case 'roll':
        beep(180, 0.06, 'square', 0)
        beep(240, 0.06, 'square', 0.06)
        break
      case 'move':
        beep(520, 0.05, 'sine', 0, 0.08)
        break
      case 'buy':
        beep(660, 0.08, 'triangle', 0)
        beep(990, 0.12, 'triangle', 0.08)
        break
      case 'rent':
        beep(300, 0.14, 'sawtooth', 0, 0.1)
        beep(200, 0.16, 'sawtooth', 0.08, 0.1)
        break
      case 'intel':
        beep(880, 0.06, 'sine', 0)
        beep(1320, 0.08, 'sine', 0.06)
        break
      case 'sweep':
        sweepTone(600, 3000, 0.4, 0)
        break
      case 'jail':
        beep(140, 0.3, 'sawtooth', 0, 0.16)
        beep(110, 0.35, 'square', 0.05, 0.12)
        break
      case 'bust':
        // wailing two-tone siren
        for (let i = 0; i < 4; i++) {
          beep(760, 0.16, 'sawtooth', i * 0.3, 0.13)
          beep(560, 0.16, 'sawtooth', i * 0.3 + 0.15, 0.13)
        }
        break
      case 'accuse':
        beep(500, 0.1, 'square', 0)
        beep(400, 0.14, 'square', 0.1)
        break
      case 'win':
        ;[523, 659, 784, 1047].forEach((f, i) => beep(f, 0.18, 'triangle', i * 0.12, 0.13))
        break
      case 'lose':
        ;[400, 330, 262].forEach((f, i) => beep(f, 0.2, 'sawtooth', i * 0.14, 0.12))
        break
    }
  } catch {
    /* audio not available — ignore */
  }
}
