import { describe, it, expect } from 'vitest'
import { HostSession, GuestSession } from './session'
import { mockTransportPair } from './transport'
import { beginGame, createGame } from '../game/engine'
import { GameState } from '../game/types'

function flush() {
  // let queued microtasks (mock transport delivery) run
  return new Promise((r) => setTimeout(r, 0))
}

function newGame(): GameState {
  // Two humans + one bot → seats 0,1 human, 2 bot.
  return beginGame(
    createGame([
      { name: 'Host', isBot: false },
      { name: 'Guest', isBot: false },
      { name: 'Bot', isBot: true },
    ])
  )
}

describe('host-authoritative session', () => {
  it('assigns the guest seat 1 and syncs the initial snapshot', async () => {
    const host = new HostSession()
    host.setState(newGame())
    const [toGuest, toHost] = mockTransportPair()
    const guest = new GuestSession(toHost)
    let got: GameState | null = null
    guest.onState = (s) => (got = s)

    host.addGuest(toGuest)
    await flush()

    expect(guest.seat).toBe(1)
    expect(got).not.toBeNull()
    expect(got!.players.length).toBe(3)
  })

  it('applies a guest action only on its own turn, and rejects out-of-turn', async () => {
    const host = new HostSession()
    let hostState = newGame()
    hostState = { ...hostState, currentPlayer: 1, phase: 'rolling' } // guest's turn
    host.setState(hostState)
    host.onState = (s) => (hostState = s)

    const [toGuest, toHost] = mockTransportPair()
    const guest = new GuestSession(toHost)
    let guestState: GameState | null = null
    guest.onState = (s) => (guestState = s)
    host.addGuest(toGuest)
    await flush()

    // It's seat 1's (guest's) turn → a roll should advance the game.
    const before = hostState.rollSeq
    guest.sendAction('rollDice', [])
    await flush()
    expect(hostState.rollSeq).toBe(before + 1)
    expect(guestState!.rollSeq).toBe(before + 1) // broadcast back to the guest

    // Now it's NOT the guest's turn — force host's current player to seat 0.
    hostState = { ...hostState, currentPlayer: 0, phase: 'rolling' }
    host.setState(hostState)
    await flush()
    const seq2 = hostState.rollSeq
    guest.sendAction('rollDice', []) // out of turn
    await flush()
    expect(hostState.rollSeq).toBe(seq2) // rejected, unchanged
  })

  it('lets a guest mark its own notebook (ungated) without affecting others', async () => {
    const host = new HostSession()
    host.setState(newGame())
    const [toGuest, toHost] = mockTransportPair()
    const guest = new GuestSession(toHost)
    host.addGuest(toGuest)
    await flush()

    // Pick a card NEITHER seat has already marked. newGame() pre-marks each
    // human's own hand ('you know your own cards'), so a hard-coded card id is
    // only unmarked for whichever deal you happened to get: this assertion
    // failed on ~50% of runs because 'dev_laser' is dealt to seat 0 half the
    // time, and its notebook then already reads '✗' before the guest acts.
    const before = (host as any).state as GameState
    const cardId = Object.keys(before.notebooks[1]).find(
      (id) => before.notebooks[0][id] === '' && before.notebooks[1][id] === '',
    )
    expect(cardId, 'no card is unmarked in both notebooks').toBeDefined()

    guest.sendAction('cycleNote', [cardId!]) // guest = seat 1
    await flush()
    // Access host state via a fresh guest snapshot.
    let snap: GameState | null = null
    guest.onState = (s) => (snap = s)
    host.broadcast({ t: 'state', state: (host as any).state })
    await flush()
    expect(snap!.notebooks[1][cardId!]).toBe('✗')
    expect(snap!.notebooks[0][cardId!]).toBe('') // host's notebook untouched
  })
})
