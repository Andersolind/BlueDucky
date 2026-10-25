import { describe, it, expect } from 'vitest'
import {
  steeringVector,
  simulateArrival,
  estimateAoa,
  arrayFactor,
  focusDelays,
  fieldMagnitude,
  focusGainDb,
  linspaceDeg,
  deg,
  rad,
} from './beamform'

// A small deterministic RNG so the noisy-array tests never flake.
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const THETAS = linspaceDeg(-90, 90, 0.5)

describe('steering vector', () => {
  it('is all-ones at broadside (sin 0 = 0)', () => {
    for (const c of steeringVector(0, 5)) {
      expect(c.re).toBeCloseTo(1, 12)
      expect(c.im).toBeCloseTo(0, 12)
    }
  })

  it('has unit magnitude at every element', () => {
    for (const c of steeringVector(rad(37), 8)) {
      expect(Math.hypot(c.re, c.im)).toBeCloseTo(1, 12)
    }
  })
})

describe('delay-and-sum DoA', () => {
  it('recovers the true angle of a clean signal', () => {
    const truth = 25
    const X = simulateArrival(rad(truth), {
      elements: 3,
      samples: 4000,
      toneHz: 0.02e6,
      sampleRate: 1e6,
      noise: 0,
    })
    const { aoaRad } = estimateAoa(X, THETAS)
    expect(deg(aoaRad)).toBeCloseTo(truth, 0)
  })

  it('recovers the angle under receiver noise', () => {
    const truth = -40
    const X = simulateArrival(rad(truth), {
      elements: 8,
      samples: 6000,
      toneHz: 0.02e6,
      sampleRate: 1e6,
      noise: 0.1,
      rng: mulberry32(7),
    })
    const { aoaRad } = estimateAoa(X, THETAS)
    // More elements = tighter beam; allow 1° for the noise.
    expect(Math.abs(deg(aoaRad) - truth)).toBeLessThan(1.5)
  })

  it('a bigger array resolves a sharper peak', () => {
    const truth = 10
    const mk = (M: number) =>
      estimateAoa(
        simulateArrival(rad(truth), {
          elements: M,
          samples: 3000,
          toneHz: 0.02e6,
          sampleRate: 1e6,
          noise: 0,
        }),
        THETAS
      ).responsesDb

    const width = (resp: number[]) => {
      const peak = Math.max(...resp)
      // count angles within 3 dB of the peak — narrower = better resolution
      return resp.filter((r) => r >= peak - 3).length
    }
    expect(width(mk(12))).toBeLessThan(width(mk(4)))
  })
})

describe('array factor (beam shape)', () => {
  it('is unity along the steer direction', () => {
    expect(arrayFactor(rad(30), rad(30), 6)).toBeCloseTo(1, 12)
  })

  it('is well below unity far from the steer direction', () => {
    // 8-element array steered broadside barely responds at 40°.
    expect(arrayFactor(rad(40), 0, 8)).toBeLessThan(0.3)
  })
})

describe('TX focusing (tranducer.py model)', () => {
  const SPEED = 343
  const FREQ = 40000
  // A square 4-node sub-aperture, like TRANSMITTER_ARRAY_NODES.
  const nodes: [number, number, number][] = [
    [1.0, 1.0, 3.0],
    [1.2, 1.0, 3.0],
    [1.0, 1.2, 3.0],
    [1.2, 1.2, 3.0],
  ]

  it('the farthest element fires first (delay 0), all delays non-negative', () => {
    const target: [number, number, number] = [0, 0, 0]
    const delays = focusDelays(nodes, target, SPEED)
    expect(Math.min(...delays)).toBeCloseTo(0, 12)
    for (const d of delays) expect(d).toBeGreaterThanOrEqual(-1e-12)
  })

  it('focused field at the target beats an unfocused (zero-delay) array', () => {
    const target: [number, number, number] = [0.5, 0.4, 0]
    const focused = fieldMagnitude(target, nodes, focusDelays(nodes, target, SPEED), FREQ, SPEED)
    const unfocused = fieldMagnitude(target, nodes, [0, 0, 0, 0], FREQ, SPEED)
    expect(focused).toBeGreaterThan(unfocused)
  })

  it('field peaks AT the focus, not a metre to the side', () => {
    const target: [number, number, number] = [0.5, 0.4, 0]
    const delays = focusDelays(nodes, target, SPEED)
    const atFocus = fieldMagnitude(target, nodes, delays, FREQ, SPEED)
    const offset = fieldMagnitude([1.5, 0.4, 0], nodes, delays, FREQ, SPEED)
    expect(atFocus).toBeGreaterThan(offset)
  })

  it('focus gain is positive and bounded by ~20log10(M)', () => {
    const g = focusGainDb(nodes, [0.5, 0.4, 0], FREQ, SPEED)
    expect(g).toBeGreaterThan(0)
    expect(g).toBeLessThan(20 * Math.log10(nodes.length) + 1)
  })
})
