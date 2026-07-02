import { describe, it, expect } from 'vitest'
import { generateChallenge, checkChallenge } from './challenges'

// Small seeded RNG so the generated challenges are deterministic here.
function makeRng(seed: number) {
  let s = seed
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    return s / 0x7fffffff
  }
}

describe('clue challenges', () => {
  it('every generated challenge (all clearances) accepts its own canonical answer', () => {
    for (let difficulty = 1; difficulty <= 3; difficulty++) {
      for (let seed = 1; seed <= 300; seed++) {
        const ch = generateChallenge(makeRng(seed), difficulty)
        expect(checkChallenge(ch, ch.answer)).toBe(true)
        // quizzes must carry their correct answer among the options
        if (ch.kind === 'quiz') expect(ch.options).toContain(ch.answer)
      }
    }
  })

  it('rejects a wrong answer and is case/space-insensitive on the right one', () => {
    const ch = generateChallenge(makeRng(42))
    expect(checkChallenge(ch, ch.answer.toUpperCase() + '  ')).toBe(true)
    expect(checkChallenge(ch, ch.answer + '_definitely_wrong')).toBe(false)
  })

  it('produces all three challenge kinds across many seeds', () => {
    const kinds = new Set<string>()
    for (let seed = 1; seed <= 200; seed++) kinds.add(generateChallenge(makeRng(seed)).kind)
    expect(kinds).toEqual(new Set(['cipher', 'sequence', 'quiz']))
  })
})
