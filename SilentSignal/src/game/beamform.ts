/**
 * Beamforming maths for the Beamformer3D scene.
 *
 * Two halves, and they are emphatically not the same thing:
 *
 *   RX — delay-and-sum direction finding. A passive uniform linear array (ULA)
 *   estimates which angle a signal arrived from by steering a beam across every
 *   angle and keeping the one with the strongest response. Nothing is emitted:
 *   the source is not touched, not jammed, not even aware it was located.
 *
 *   TX — phased-array focusing (the model in tranducer.py). Every element emits
 *   the same waveform on a per-element delay chosen so all wavefronts co-arrive
 *   at one point. Energy piles up on that point and largely cancels elsewhere.
 *   This is the only half that does anything TO a target.
 *
 * Angles are measured from broadside (boresight = 0), positive toward +x.
 * Element spacing `d` is in wavelengths throughout the RX half.
 */

export interface Complex {
  re: number
  im: number
}

export type Vec3 = [number, number, number]

/** Spacing that avoids grating lobes — the classic λ/2 rule. */
export const HALF_WAVELENGTH = 0.5

/**
 * Steering vector for an M-element ULA: vₘ(θ) = exp(-2πj·d·m·sin θ).
 *
 * The m·sin θ term is the per-element path difference, i.e. the time delay the
 * wavefront takes to walk from element 0 to element m. That is the whole trick.
 */
export function steeringVector(thetaRad: number, elements: number, d = HALF_WAVELENGTH): Complex[] {
  const sin = Math.sin(thetaRad)
  return Array.from({ length: elements }, (_, m) => {
    const phase = -2 * Math.PI * d * m * sin
    return { re: Math.cos(phase), im: Math.sin(phase) }
  })
}

export interface ArrivalOptions {
  elements: number
  samples: number
  toneHz: number
  sampleRate: number
  /** Std-dev of complex AWGN added per element. 0 for a noiseless array. */
  noise: number
  spacing?: number
  /** Injectable uniform RNG so tests are deterministic. */
  rng?: () => number
}

/**
 * Simulate a tone impinging on the array from `thetaRad`.
 * Returns the received matrix X as X[sample][element].
 */
export function simulateArrival(thetaRad: number, o: ArrivalOptions): Complex[][] {
  const { elements, samples, toneHz, sampleRate, noise } = o
  const d = o.spacing ?? HALF_WAVELENGTH
  const rng = o.rng ?? Math.random
  const v = steeringVector(thetaRad, elements, d)
  const X: Complex[][] = []

  for (let n = 0; n < samples; n++) {
    const t = n / sampleRate
    const phase = 2 * Math.PI * toneHz * t
    const s: Complex = { re: Math.cos(phase), im: Math.sin(phase) }
    const row: Complex[] = []
    for (let m = 0; m < elements; m++) {
      // s · vₘ, then per-element receiver noise.
      const re = s.re * v[m].re - s.im * v[m].im
      const im = s.re * v[m].im + s.im * v[m].re
      row.push({ re: re + gauss(rng) * noise, im: im + gauss(rng) * noise })
    }
    X.push(row)
  }
  return X
}

/**
 * Delay-and-sum at one steering angle: y = X · conj(w(θ)) / M.
 *
 * When θ matches the true arrival angle the per-element phases cancel and every
 * element adds coherently, so y is a clean copy of the source and its variance
 * (the array response) peaks.
 */
export function delayAndSum(
  X: Complex[][],
  thetaRad: number,
  d = HALF_WAVELENGTH
): { y: Complex[]; responseDb: number } {
  const elements = X[0].length
  const w = steeringVector(thetaRad, elements, d)
  const y: Complex[] = X.map((row) => {
    let re = 0
    let im = 0
    for (let m = 0; m < elements; m++) {
      // row[m] · conj(w[m])
      re += row[m].re * w[m].re + row[m].im * w[m].im
      im += row[m].im * w[m].re - row[m].re * w[m].im
    }
    return { re: re / elements, im: im / elements }
  })
  return { y, responseDb: 10 * Math.log10(complexVariance(y) + 1e-12) }
}

/**
 * Sweep the steering vector across `thetasRad` and return the response in dB at
 * each — the direction-finding spectrum. Its peak is the angle-of-arrival estimate.
 */
export function sweep(X: Complex[][], thetasRad: number[], d = HALF_WAVELENGTH): number[] {
  return thetasRad.map((t) => delayAndSum(X, t, d).responseDb)
}

/** Angle of arrival = the steering angle with the LARGEST response. */
export function estimateAoa(
  X: Complex[][],
  thetasRad: number[],
  d = HALF_WAVELENGTH
): { aoaRad: number; responsesDb: number[] } {
  const responsesDb = sweep(X, thetasRad, d)
  let best = 0
  for (let i = 1; i < responsesDb.length; i++) if (responsesDb[i] > responsesDb[best]) best = i
  return { aoaRad: thetasRad[best], responsesDb }
}

/**
 * Normalised array factor in [0, 1] — how sensitive the array is toward
 * `thetaRad` while steered at `steerRad`. This is the *beam shape*: 1 along the
 * steer direction, deep nulls elsewhere. Distinct from the DoA spectrum above,
 * which peaks at where the signal actually is.
 */
export function arrayFactor(
  thetaRad: number,
  steerRad: number,
  elements: number,
  d = HALF_WAVELENGTH
): number {
  const delta = Math.sin(thetaRad) - Math.sin(steerRad)
  let re = 0
  let im = 0
  for (let m = 0; m < elements; m++) {
    const phase = 2 * Math.PI * d * m * delta
    re += Math.cos(phase)
    im += Math.sin(phase)
  }
  return Math.hypot(re, im) / elements
}

/* ------------------------------------------------------------------ *
 * TX — phased-array focusing (tranducer.py's model)
 * ------------------------------------------------------------------ */

/**
 * Per-element firing delays that focus the array on `target`.
 *
 * Only RELATIVE delays matter; the common flight time is irrelevant. The element
 * FARTHEST from the target has the longest path, so it fires first (delay 0);
 * every closer element waits out the extra time its shorter path would have
 * saved. All wavefronts then co-arrive and add coherently at the target.
 */
export function focusDelays(nodes: Vec3[], target: Vec3, speed: number): number[] {
  const dist = nodes.map((n) => distance(n, target))
  const max = Math.max(...dist)
  return dist.map((r) => (max - r) / speed)
}

/**
 * Coherent pressure magnitude at `p` — the steady-state field the delayed array
 * produces, with 1/r spherical spreading. Peaks sharply at the focus; the size
 * of that peak versus everywhere else is exactly "how much the target is affected".
 */
export function fieldMagnitude(
  p: Vec3,
  nodes: Vec3[],
  delays: number[],
  freqHz: number,
  speed: number
): number {
  let re = 0
  let im = 0
  for (let i = 0; i < nodes.length; i++) {
    const r = Math.max(distance(nodes[i], p), 1e-3)
    const phase = -2 * Math.PI * freqHz * (r / speed + delays[i])
    re += Math.cos(phase) / r
    im += Math.sin(phase) / r
  }
  return Math.hypot(re, im)
}

/**
 * Focus gain in dB: the focused array's pressure at the target versus what a
 * single element at the same range would deliver. An M-element array that
 * focuses perfectly buys ~20·log10(M) dB.
 */
export function focusGainDb(nodes: Vec3[], target: Vec3, freqHz: number, speed: number): number {
  const delays = focusDelays(nodes, target, speed)
  const focused = fieldMagnitude(target, nodes, delays, freqHz, speed)
  const single = 1 / Math.max(distance(nodes[0], target), 1e-3)
  return 20 * Math.log10(focused / single + 1e-12)
}

/* ------------------------------------------------------------------ *
 * helpers
 * ------------------------------------------------------------------ */

function distance(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
}

/** Mean |y − ȳ|² — the power of the beamformer output about its mean. */
function complexVariance(y: Complex[]): number {
  let mre = 0
  let mim = 0
  for (const c of y) {
    mre += c.re
    mim += c.im
  }
  mre /= y.length
  mim /= y.length
  let acc = 0
  for (const c of y) acc += (c.re - mre) ** 2 + (c.im - mim) ** 2
  return acc / y.length
}

/** Box–Muller standard normal from a uniform RNG. */
function gauss(rng: () => number): number {
  const u = Math.max(rng(), 1e-12)
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng())
}

export const deg = (rad: number) => (rad * 180) / Math.PI
export const rad = (degrees: number) => (degrees * Math.PI) / 180

/** Inclusive angle grid in radians, e.g. linspaceDeg(-90, 90, 0.5). */
export function linspaceDeg(fromDeg: number, toDeg: number, stepDeg: number): number[] {
  const out: number[] = []
  for (let a = fromDeg; a <= toDeg + 1e-9; a += stepDeg) out.push(rad(a))
  return out
}
