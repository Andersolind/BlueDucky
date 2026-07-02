import { ChallengeState } from './types'

/**
 * Landing clue-challenges. Solve one and you earn INTEL — the game rules a
 * random innocent card off your notebook (see engine.grantIntel). Challenges
 * are themed to signals/espionage and never leak the actual solution.
 *
 * Pure module: generators take an optional rng so they can be unit-tested.
 */

type Rng = () => number

function choice<T>(arr: T[], rng: Rng): T {
  return arr[Math.floor(rng() * arr.length)]
}

const REWARD = 'Intel: one innocent card ruled off your notebook.'

/* ---------------- Cipher: decode a Caesar-shifted word ---------------- */

const CIPHER_WORDS = [
  'whisper',
  'intercept',
  'wiretap',
  'frequency',
  'decode',
  'payload',
  'antenna',
  'spectrum',
  'earpiece',
  'cipher',
  'beacon',
  'silence',
]

function caesar(word: string, shift: number): string {
  return word
    .split('')
    .map((c) => {
      const code = c.charCodeAt(0)
      if (code >= 97 && code <= 122) return String.fromCharCode(((code - 97 + shift) % 26) + 97)
      return c
    })
    .join('')
}

function makeCipher(rng: Rng, difficulty: number): ChallengeState {
  // Higher clearance → longer words and, at tier 3, the shift is withheld.
  const pool = difficulty <= 1 ? CIPHER_WORDS.filter((w) => w.length <= 6) : CIPHER_WORDS
  const word = choice(pool.length ? pool : CIPHER_WORDS, rng)
  const shift = 1 + Math.floor(rng() * 25)
  const hint =
    difficulty >= 3
      ? 'Caesar cipher — the shift is unknown. Work it out and decode.'
      : `Caesar cipher — every letter shifted forward by ${shift}. Decode it.`
  return {
    kind: 'cipher',
    title: 'Cipher Cache',
    prompt: caesar(word, shift).toUpperCase(),
    answer: word,
    hint,
    reward: REWARD,
  }
}

/* ---------------- Sequence: what comes next ---------------- */

function makeSequence(rng: Rng, difficulty: number): ChallengeState {
  let seq: number[]
  let next: number
  let hint: string
  if (difficulty >= 3 && rng() < 0.7) {
    // Shifted perfect squares: c+1, c+4, c+9, c+16, → c+25.
    const c = Math.floor(rng() * 5)
    seq = [c + 1, c + 4, c + 9, c + 16]
    next = c + 25
    hint = 'Not a fixed step — think about the gaps between the gaps.'
  } else if (difficulty >= 2 && rng() < 0.6) {
    const a = 1 + Math.floor(rng() * 4)
    const r = 2 + Math.floor(rng() * 2) // ×2 or ×3
    seq = [a, a * r, a * r * r, a * r * r * r]
    next = a * r * r * r * r
    hint = 'Each intercept multiplies by the same factor. What is next?'
  } else {
    const a = 1 + Math.floor(rng() * 6)
    const d = 2 + Math.floor(rng() * 5)
    seq = [a, a + d, a + 2 * d, a + 3 * d]
    next = a + 4 * d
    hint = 'A repeating step drives the intercepted counter. What is next?'
  }
  return {
    kind: 'sequence',
    title: 'Wiretap Pattern',
    prompt: `${seq.join('  ,  ')}  ,  ?`,
    answer: String(next),
    hint,
    reward: REWARD,
  }
}

/* ---------------- Quiz: signals-intelligence trivia ---------------- */

interface QuizDef {
  q: string
  correct: string
  wrong: string[]
}

const QUIZZES: QuizDef[] = [
  { q: 'Human hearing generally tops out around…', correct: '20 kHz', wrong: ['200 Hz', '2 kHz', '200 kHz'] },
  { q: 'A laser microphone eavesdrops by measuring…', correct: 'window-glass vibration', wrong: ['radio static', 'room temperature', 'magnetic fields'] },
  { q: 'Data-over-sound encodes bits as…', correct: 'tones / frequencies', wrong: ['colors', 'GPS coordinates', 'battery voltage'] },
  { q: 'The Goertzel algorithm efficiently detects…', correct: 'a single target frequency', wrong: ['hidden images', 'malware', 'weak passwords'] },
  { q: "An 'air-gapped' machine is one that is…", correct: 'not connected to any network', wrong: ['overclocked', 'fully encrypted', 'running in a VM'] },
  { q: 'Ultrasound is sound with a frequency above…', correct: '20 kHz', wrong: ['20 Hz', '1 kHz', '500 Hz'] },
  { q: 'A retroreflector bug is powered/read by…', correct: 'an external radio flood', wrong: ['a coin battery', 'solar panels', 'the mains supply'] },
]

function shuffleInPlace<T>(arr: T[], rng: Rng): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

function makeQuiz(rng: Rng, _difficulty: number): ChallengeState {
  const def = choice(QUIZZES, rng)
  const options = shuffleInPlace([def.correct, ...def.wrong], rng)
  return {
    kind: 'quiz',
    title: 'Interception',
    prompt: def.q,
    options,
    answer: def.correct,
    reward: REWARD,
  }
}

/* ---------------- Public API ---------------- */

const GENERATORS = [makeCipher, makeSequence, makeQuiz]

/** Generate a challenge. `difficulty` (1..3) is the clearance sub-layer. */
export function generateChallenge(rng: Rng = Math.random, difficulty = 1): ChallengeState {
  return choice(GENERATORS, rng)(rng, difficulty)
}

/** Case-insensitive, whitespace-trimmed comparison. */
export function checkChallenge(challenge: ChallengeState, input: string): boolean {
  return input.trim().toLowerCase() === challenge.answer.trim().toLowerCase()
}
