import { describe, it, expect } from 'vitest'
import {
  createGame,
  beginGame,
  botStep,
  rollDice,
  moveTo,
  makeSuggestion,
  endTurn,
  humanReveal,
  reachableRooms,
} from './engine'
import { GameState } from './types'

const SUSPECTS = ['sus_vesper', 'sus_finch', 'sus_mir', 'sus_hollis', 'sus_volkov', 'sus_marsh']
const DEVICES = ['dev_ultra', 'dev_laser', 'dev_gsm', 'dev_contact', 'dev_retro', 'dev_parabolic']

// A random auto-player standing in for the human, so we can drive full games.
function humanAct(s: GameState): GameState {
  let st = rollDice(s)
  st = moveTo(st, st.reachable[Math.floor(Math.random() * st.reachable.length)])
  st = makeSuggestion(
    st,
    SUSPECTS[Math.floor(Math.random() * SUSPECTS.length)],
    DEVICES[Math.floor(Math.random() * DEVICES.length)]
  )
  if (st.phase !== 'gameover') st = endTurn(st)
  return st
}

function step(s: GameState): GameState {
  if (s.pending?.humanPick) return humanReveal(s, s.pending.humanPick.options[0])
  return s.players[s.currentPlayer].isBot ? botStep(s) : humanAct(s)
}

function playToEnd(): GameState {
  let s = beginGame(
    createGame([
      { name: 'You', isBot: false },
      { name: 'CIPHER', isBot: true },
      { name: 'ECHO', isBot: true },
      { name: 'RAVEN', isBot: true },
    ])
  )
  let steps = 0
  while (s.phase !== 'gameover' && steps < 8000) {
    s = step(s)
    steps++
  }
  return s
}

describe('game setup', () => {
  it('deals every non-solution card and never leaks a solution card into a hand', () => {
    for (let i = 0; i < 50; i++) {
      const s = createGame([
        { name: 'You', isBot: false },
        { name: 'A', isBot: true },
        { name: 'B', isBot: true },
      ])
      const sol = s.solution!
      const hands = s.players.flatMap((p) => p.hand)
      expect(hands).not.toContain(sol.suspect)
      expect(hands).not.toContain(sol.device)
      expect(hands).not.toContain(sol.location)
      // 21 cards total - 3 solution = 18 dealt, no duplicates.
      expect(hands.length).toBe(18)
      expect(new Set(hands).size).toBe(18)
    }
  })
})

describe('board reachability', () => {
  it('includes the start room and grows with the roll', () => {
    const near = reachableRooms('loc_vault', 1)
    const far = reachableRooms('loc_vault', 4)
    expect(near).toContain('loc_vault')
    expect(far.length).toBeGreaterThanOrEqual(near.length)
  })
})

describe('full game simulation', () => {
  it('every game terminates with a valid winner and intact solution (200 games)', () => {
    let winners = 0
    for (let g = 0; g < 200; g++) {
      const s = playToEnd()
      expect(s.phase).toBe('gameover')
      const hands = s.players.flatMap((p) => p.hand)
      const sol = s.solution!
      expect(hands).not.toContain(sol.suspect)
      expect(hands).not.toContain(sol.device)
      expect(hands).not.toContain(sol.location)
      if (s.winner) winners++
    }
    // With decisive bots, essentially every game is solved by someone.
    expect(winners).toBeGreaterThan(190)
  })
})
