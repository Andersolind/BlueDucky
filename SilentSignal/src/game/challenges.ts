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

function makeCipher(rng: Rng): ChallengeState {
  const word = choice(CIPHER_WORDS, rng)
  const shift = 1 + Math.floor(rng() * 25)
  return {
    kind: 'cipher',
    title: 'Cipher Cache',
    prompt: caesar(word, shift).toUpperCase(),
    answer: word,
    hint: `Caesar cipher — every letter shifted forward by ${shift}. Decode it.`,
    reward: REWARD,
  }
}

/* ---------------- Sequence: what comes next ---------------- */

function makeSequence(rng: Rng): ChallengeState {
  const geometric = rng() < 0.4
  let seq: number[]
  let next: number
  if (geometric) {
    const a = 1 + Math.floor(rng() * 4)
    const r = 2 + Math.floor(rng() * 2) // ×2 or ×3
    seq = [a, a * r, a * r * r, a * r * r * r]
    next = a * r * r * r * r
  } else {
    const a = 1 + Math.floor(rng() * 6)
    const d = 2 + Math.floor(rng() * 5)
    seq = [a, a + d, a + 2 * d, a + 3 * d]
    next = a + 4 * d
  }
  return {
    kind: 'sequence',
    title: 'Wiretap Pattern',
    prompt: `${seq.join('  ,  ')}  ,  ?`,
    answer: String(next),
    hint: 'A repeating step drives the intercepted counter. What is the next value?',
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

function makeQuiz(rng: Rng): ChallengeState {
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

export function generateChallenge(rng: Rng = Math.random): ChallengeState {
  return choice(GENERATORS, rng)(rng)
}

/** Case-insensitive, whitespace-trimmed comparison. */
export function checkChallenge(challenge: ChallengeState, input: string): boolean {
  return input.trim().toLowerCase() === challenge.answer.trim().toLowerCase()
}
