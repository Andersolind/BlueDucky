import { describe, it, expect } from 'vitest'
import {
  createGame,
  beginGame,
  botStep,
  rollDice,
  currentTile,
  makeSuggestion,
  resolveChallenge,
  buyProperty,
  declineBuy,
  buyStoreIntel,
  serveJail,
  payBail,
  endTurn,
  humanReveal,
} from './engine'
import { GameState } from './types'
import { buildBoard, MIMICO_POI } from './data'

const SUSPECTS = ['sus_vesper', 'sus_finch', 'sus_mir', 'sus_hollis', 'sus_volkov', 'sus_marsh']
const DEVICES = ['dev_ultra', 'dev_laser', 'dev_gsm', 'dev_contact', 'dev_retro', 'dev_parabolic']

// A random auto-player standing in for the human, so we can drive full games
// through every landing phase (buy / store / jail / challenge).
function humanAct(s: GameState): GameState {
  const idx = s.currentPlayer
  let st = s.players[idx].inJail ? (Math.random() < 0.5 ? payBail(s) : serveJail(s)) : rollDice(s)
  // Bankruptcy or serving jail may have already passed the turn on.
  if (st.currentPlayer !== idx || st.phase === 'gameover') return st

  if (st.phase === 'challenge') st = resolveChallenge(st, Math.random() < 0.5)
  else if (st.phase === 'buying') st = Math.random() < 0.6 ? buyProperty(st) : declineBuy(st)
  else if (st.phase === 'store') st = buyStoreIntel(st, Math.random() < 0.5)
  if (st.currentPlayer !== idx || st.phase === 'gameover') return st

  if (currentTile(st).type === 'location') {
    st = makeSuggestion(
      st,
      SUSPECTS[Math.floor(Math.random() * SUSPECTS.length)],
      DEVICES[Math.floor(Math.random() * DEVICES.length)]
    )
  }
  if (st.currentPlayer === idx && st.phase !== 'gameover') st = endTurn(st)
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

describe('ring movement', () => {
  it('hops 1..6 tiles forward and derives room only on location tiles', () => {
    for (let i = 0; i < 100; i++) {
      let s = beginGame(
        createGame([
          { name: 'You', isBot: false },
          { name: 'A', isBot: true },
        ])
      )
      const before = s.players[0].pos
      s = rollDice(s)
      const delta = (s.players[0].pos - before + 24) % 24
      expect(delta).toBeGreaterThanOrEqual(1)
      expect(delta).toBeLessThanOrEqual(6)
      const tile = currentTile(s)
      // room is set iff standing on a location tile
      expect(s.players[0].room !== '').toBe(tile.type === 'location')
    }
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
      // economy stays sane: money is always a finite number.
      for (const p of s.players) expect(Number.isFinite(p.money)).toBe(true)
      if (s.winner) winners++
    }
    // With decisive bots, essentially every game is solved by someone.
    expect(winners).toBeGreaterThan(185)
  })
})

describe('board generation (POI-driven)', () => {
  it('builds 24 tiles with 9 priced locations, 2 stations, 3 stores, 2 bus stops', () => {
    const b = buildBoard(MIMICO_POI)
    expect(b.length).toBe(24)

    const locs = b.filter((t) => t.type === 'location')
    expect(locs.length).toBe(9)
    for (const t of locs) {
      expect(t.locationId).toBeTruthy()
      expect((t.price ?? 0) > 0).toBe(true)
      expect((t.rent ?? 0) > 0).toBe(true)
    }
    expect(new Set(locs.map((t) => t.locationId)).size).toBe(9)

    const stations = b.filter((t) => t.type === 'station')
    expect(stations.length).toBe(2)
    for (const t of stations) expect(t.price).toBe(200)

    expect(b.filter((t) => t.type === 'store').length).toBe(3)
    expect(b.filter((t) => t.type === 'busstop').length).toBe(2)
    expect(b.filter((t) => t.type === 'go').length).toBe(1)
    expect(b.filter((t) => t.type === 'gotojail').length).toBe(1)
  })
})

describe('economy — buying a property', () => {
  it('deducts the price, records ownership, and sets rent for visitors', () => {
    let s = beginGame(
      createGame([
        { name: 'You', isBot: false },
        { name: 'A', isBot: true },
      ])
    )
    const pos = s.board.findIndex((t) => t.type === 'location')
    s = { ...s, currentPlayer: 0, decisionPos: pos, phase: 'buying' }
    const price = s.board[pos].price!
    const before = s.players[0].money

    s = buyProperty(s)
    expect(s.players[0].money).toBe(before - price)
    expect(s.board[pos].owner).toBe(s.players[0].id)
    expect(s.players[0].properties).toContain(pos)
    expect(s.board[pos].rent).toBeGreaterThan(0)
  })
})
