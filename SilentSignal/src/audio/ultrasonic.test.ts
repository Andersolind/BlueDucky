import { describe, it, expect } from 'vitest'
import { synthesize, decodeSamples, bandDominance, DEFAULT_CONFIG } from './ultrasonic'

const SR = 48000
const cfg = DEFAULT_CONFIG

// Deterministic PRNG so tests are reproducible run-to-run.
function makeRng(seed: number) {
  let s = seed
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    return s / 0x7fffffff
  }
}

/** Simulate a real acoustic path: silent lead-in, gain, white noise, DC offset. */
function degrade(pcm: Float32Array, noise: number, gain: number, dc: number, seed = 99): Float32Array {
  const rnd = makeRng(seed)
  const lead = 700
  const out = new Float32Array(pcm.length + lead + 1300)
  for (let i = 0; i < out.length; i++) {
    let s = i >= lead && i - lead < pcm.length ? pcm[i - lead] * gain : 0
    s += (rnd() * 2 - 1) * noise
    s += dc
    out[i] = s
  }
  return out
}

describe('ultrasonic modem loopback', () => {
  const cases = [
    'the walls have ears',
    'SS-BEACON::live',
    'Vesper Kane / Ultrasonic Implant / Comms Closet',
    'ping 42',
    'MixedCASE and sym+bols!?',
  ]

  for (const text of cases) {
    it(`round-trips "${text}" clean`, () => {
      expect(decodeSamples(synthesize(text, cfg, SR), cfg, SR)?.text).toBe(text)
    })

    it(`round-trips "${text}" through a quiet room (atten + lead-in)`, () => {
      const got = decodeSamples(degrade(synthesize(text, cfg, SR), 0.01, 0.5, 0.0), cfg, SR)
      expect(got?.text).toBe(text)
    })

    it(`round-trips "${text}" through a noisy room (+noise +DC)`, () => {
      const got = decodeSamples(degrade(synthesize(text, cfg, SR), 0.03, 0.35, 0.02), cfg, SR)
      expect(got?.text).toBe(text)
    })
  }

  it('returns null when there is no frame in the buffer', () => {
    const rnd = makeRng(7)
    const noise = new Float32Array(SR)
    for (let i = 0; i < noise.length; i++) noise[i] = (rnd() * 2 - 1) * 0.2
    expect(decodeSamples(noise, cfg, SR)).toBeNull()
  })
})

describe('sweep band-dominance (the "live contact" signal)', () => {
  const sym = Math.round(cfg.symbolSec * SR)

  it('reads HIGH when an ultrasonic beacon tone is present', () => {
    // Take a window from the middle of a synthesized beacon (a pure band tone).
    const pcm = synthesize('SS-BEACON::live', cfg, SR)
    const mid = sym * 4 // inside the data region
    const d = bandDominance(pcm, mid, sym, cfg, SR)
    expect(d).toBeGreaterThan(0.3)
  })

  it('reads LOW for broadband noise (no false contact)', () => {
    const rnd = makeRng(3)
    const noise = new Float32Array(sym)
    for (let i = 0; i < noise.length; i++) noise[i] = (rnd() * 2 - 1) * 0.3
    expect(bandDominance(noise, 0, sym, cfg, SR)).toBeLessThan(0.15)
  })

  it('reads LOW for an audible-range tone (e.g. speech/music fundamentals)', () => {
    // A 1 kHz tone — well below the modem band — must not trip the sweep.
    const tone = new Float32Array(sym)
    for (let i = 0; i < tone.length; i++) tone[i] = Math.sin((2 * Math.PI * 1000 * i) / SR) * 0.5
    expect(bandDominance(tone, 0, sym, cfg, SR)).toBeLessThan(0.15)
  })

  it('separates beacon from noise by a wide margin (threshold is safe)', () => {
    const pcm = synthesize('SS-BEACON::live', cfg, SR)
    const beacon = bandDominance(pcm, sym * 4, sym, cfg, SR)
    const rnd = makeRng(5)
    const noise = new Float32Array(sym)
    for (let i = 0; i < noise.length; i++) noise[i] = (rnd() * 2 - 1) * 0.3
    const amb = bandDominance(noise, 0, sym, cfg, SR)
    expect(beacon - amb).toBeGreaterThan(0.2)
  })
})
