import {
  BotStage,
  Card,
  GameState,
  LogEntry,
  Notebook,
  Player,
  Solution,
  Suggestion,
} from './types'
import {
  ALL_CARDS,
  CARD_BY_ID,
  DEVICES,
  LOCATIONS,
  PLAYER_COLORS,
  ROOM_ADJACENCY,
  ROOM_GRID,
  SUSPECTS,
} from './data'

/* ------------------------------------------------------------------ *
 *  Small helpers
 * ------------------------------------------------------------------ */

let LOG_SEQ = 1

function shuffle<T>(arr: T[]): T[] {
  const a = arr.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function log(state: GameState, kind: LogEntry['kind'], text: string, actor?: string, cards?: Suggestion) {
  state.log.unshift({ id: LOG_SEQ++, turn: state.turn, kind, actor, text, cards })
  if (state.log.length > 60) state.log.pop()
}

export function cardName(id: string): string {
  return CARD_BY_ID[id]?.name ?? id
}

function cardsOf(suggestion: Suggestion): string[] {
  return [suggestion.suspect, suggestion.device, suggestion.location]
}

/* ------------------------------------------------------------------ *
 *  Setup
 * ------------------------------------------------------------------ */

export interface PlayerConfig {
  name: string
  isBot: boolean
}

export function createGame(configs: PlayerConfig[]): GameState {
  // 1. Draw the solution: one card from each category.
  const solution: Solution = {
    suspect: pick(SUSPECTS).id,
    device: pick(DEVICES).id,
    location: pick(LOCATIONS).id,
  }

  // 2. Deal the rest round-robin.
  const rest = shuffle(
    ALL_CARDS.filter(
      (c) => c.id !== solution.suspect && c.id !== solution.device && c.id !== solution.location
    ).map((c) => c.id)
  )

  const startRooms = shuffle(ROOM_GRID.flat())
  const players: Player[] = configs.map((cfg, i) => ({
    id: `p${i}`,
    name: cfg.name,
    isBot: cfg.isBot,
    hand: [],
    room: startRooms[i % startRooms.length],
    out: false,
    color: PLAYER_COLORS[i % PLAYER_COLORS.length],
    seen: cfg.isBot ? [] : undefined,
    deduced: cfg.isBot ? {} : undefined,
  }))

  rest.forEach((cardId, i) => players[i % players.length].hand.push(cardId))

  // Bots "see" their own hand.
  players.forEach((p) => {
    if (p.isBot) p.seen = p.hand.slice()
  })

  const state: GameState = {
    phase: 'lobby',
    players,
    currentPlayer: 0,
    solution,
    notebook: emptyNotebook(),
    log: [],
    turn: 0,
    dice: 0,
    reachable: [],
    pending: null,
    winner: null,
    revealed: false,
    sweepClue: null,
    botStage: null,
    sweptThisTurn: false,
  }

  // Pre-mark the human's own hand in their notebook (they know they're innocent of holding these).
  const human = players.find((p) => !p.isBot)
  if (human) human.hand.forEach((id) => (state.notebook[id] = '✗'))

  log(state, 'system', `Case opened. ${players.length} agents on the board. Find the eavesdropper.`)
  return state
}

export function emptyNotebook(): Notebook {
  const nb: Notebook = {}
  ALL_CARDS.forEach((c) => (nb[c.id] = ''))
  return nb
}

/* ------------------------------------------------------------------ *
 *  Turn lifecycle
 * ------------------------------------------------------------------ */

export function beginGame(state: GameState): GameState {
  const s = clone(state)
  s.phase = 'lobby'
  startTurn(s)
  return s
}

function nextActiveIndex(s: GameState, from: number): number {
  // Find the next player who is not out. If all others are out, return -1.
  for (let step = 1; step <= s.players.length; step++) {
    const idx = (from + step) % s.players.length
    if (!s.players[idx].out) return idx
  }
  return -1
}

function startTurn(s: GameState) {
  s.dice = 0
  s.reachable = []
  s.pending = null
  s.sweepClue = null
  s.sweptThisTurn = false

  const p = s.players[s.currentPlayer]
  if (p.out) {
    // Skip eliminated players entirely.
    const next = nextActiveIndex(s, s.currentPlayer)
    if (next === -1) return
    s.currentPlayer = next
    return startTurn(s)
  }

  s.turn++
  if (p.isBot) {
    s.phase = 'bot-turn'
    s.botStage = 'roll'
  } else {
    s.phase = 'rolling'
    s.botStage = null
  }
}

export function endTurn(state: GameState): GameState {
  const s = clone(state)
  const active = s.players.filter((p) => !p.out)
  if (active.length <= 1 && s.players.length > 1) {
    // Everyone else accused wrong — last one standing wins by default.
    const survivor = active[0]
    if (survivor) declareWinner(s, survivor, true)
    return s
  }
  const next = nextActiveIndex(s, s.currentPlayer)
  if (next === -1) return s
  s.currentPlayer = next
  startTurn(s)
  return s
}

/* ------------------------------------------------------------------ *
 *  Movement
 * ------------------------------------------------------------------ */

export function rollDice(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  s.dice = 1 + Math.floor(Math.random() * 6)
  s.reachable = reachableRooms(p.room, s.dice)
  s.phase = p.isBot ? 'bot-turn' : 'moving'
  log(s, 'move', `${p.name} rolled a ${s.dice}.`, p.name)
  return s
}

/** BFS over the room graph: all rooms within `dist` steps (includes start). */
export function reachableRooms(start: string, dist: number): string[] {
  const seen = new Set<string>([start])
  let frontier = [start]
  for (let d = 0; d < dist; d++) {
    const next: string[] = []
    for (const room of frontier) {
      for (const nb of ROOM_ADJACENCY[room] ?? []) {
        if (!seen.has(nb)) {
          seen.add(nb)
          next.push(nb)
        }
      }
    }
    frontier = next
  }
  return Array.from(seen)
}

export function moveTo(state: GameState, roomId: string): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  if (!s.reachable.includes(roomId)) return state
  p.room = roomId
  log(s, 'move', `${p.name} moved to the ${cardName(roomId)}.`, p.name)
  s.phase = 'suggesting'
  return s
}

/* ------------------------------------------------------------------ *
 *  Ultrasonic sweep (the signature mechanic)
 * ------------------------------------------------------------------ */

/**
 * A sweep in your current room. Two flavors of result:
 *  - If a real ultrasonic contact was detected in the room (a co-located
 *    device transmitting the beacon), `realContact` is true — strong flavor.
 *  - Always: narrows the DEVICE category by revealing whether the true bug
 *    is an active emitter or passive, IF the true location matches where you
 *    swept (you can only sniff emissions from the room the bug is in).
 */
export function ultrasonicSweep(state: GameState, realContact: boolean): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  s.sweptThisTurn = true

  const sol = s.solution!
  const inSolutionRoom = p.room === sol.location
  const trueDevice = CARD_BY_ID[sol.device]

  let clue: string
  const annotate = !p.isBot // only auto-fill a human's own notebook
  if (realContact) {
    clue = `⚡ LIVE CONTACT — a device in the ${cardName(p.room)} is transmitting ultrasound right now.`
  } else if (inSolutionRoom && trueDevice.emits) {
    clue = `Emission detected in the ${cardName(p.room)}: the bug here is an ACTIVE emitter.`
    if (annotate) markCards(s, devicesMatchingEmission(false), '✗') // rule out passive devices
  } else if (inSolutionRoom && !trueDevice.emits) {
    clue = `The bug in the ${cardName(p.room)} is silent on RF/ultrasound — a PASSIVE device.`
    if (annotate) markCards(s, devicesMatchingEmission(true), '✗') // rule out active devices
  } else {
    clue = `No emissions in the ${cardName(p.room)}. The active bug isn't planted here.`
    if (annotate) markCards(s, [p.room], '✗') // this location is ruled out
  }
  s.sweepClue = clue
  log(s, 'sweep', `${p.name} ran an ultrasonic sweep: ${clue}`, p.name)
  return s
}

/** Devices consistent with a sweep result, for auto-annotating the notebook. */
export function devicesMatchingEmission(emits: boolean): string[] {
  return DEVICES.filter((d) => !!d.emits === emits).map((d) => d.id)
}

/** Set a notebook mark for a set of cards unless the human already marked it '✓'. */
function markCards(s: GameState, ids: string[], mark: '✗' | '?' | '✓') {
  ids.forEach((id) => {
    if (s.notebook[id] !== '✓') s.notebook[id] = mark
  })
}

/* ------------------------------------------------------------------ *
 *  Suggestions + disprove resolution
 * ------------------------------------------------------------------ */

export function makeSuggestion(state: GameState, suspect: string, device: string): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  const suggestion: Suggestion = { suspect, device, location: p.room }

  log(
    s,
    'suggest',
    `${p.name} suggests ${cardName(suspect)} · ${cardName(device)} · ${cardName(p.room)}.`,
    p.name,
    suggestion
  )

  // Ask each other player in clockwise order.
  const queue: number[] = []
  for (let step = 1; step < s.players.length; step++) {
    queue.push((s.currentPlayer + step) % s.players.length)
  }
  s.pending = { suggestion, suggester: s.currentPlayer, queue, resolved: false }
  s.phase = 'disproving'
  processDisprove(s)
  return s
}

/**
 * Walk the disprove queue until either someone reveals a card, the queue is
 * exhausted, or we need a *human* to choose which card to show.
 */
function processDisprove(s: GameState) {
  const pending = s.pending
  if (!pending) return
  const cards = cardsOf(pending.suggestion)

  while (pending.queue.length > 0) {
    const responderIdx = pending.queue[0]
    const responder = s.players[responderIdx]
    const matching = responder.hand.filter((c) => cards.includes(c))

    if (matching.length === 0) {
      // Cannot disprove.
      pending.queue.shift()
      log(s, 'no-disprove', `${responder.name} cannot disprove.`, responder.name)
      continue
    }

    // This responder must reveal a card.
    if (!responder.isBot) {
      // Human chooses which card to show.
      pending.humanPick = { responder: responderIdx, options: matching }
      s.phase = 'disproving'
      return
    }

    // Bot reveals — pick strategically to leak the least (prefer a card the
    // suggester has probably already seen; else random).
    const chosen = botChooseReveal(s, responderIdx, pending.suggester, matching)
    revealCard(s, responderIdx, chosen)
    return
  }

  // Nobody could disprove.
  finishDisprove(s)
}

/** Called after a human responder picks a card to show. */
export function humanReveal(state: GameState, cardId: string): GameState {
  const s = clone(state)
  const pending = s.pending
  if (!pending || !pending.humanPick) return state
  if (!pending.humanPick.options.includes(cardId)) return state
  const responderIdx = pending.humanPick.responder
  pending.humanPick = null
  revealCard(s, responderIdx, cardId)
  return s
}

function revealCard(s: GameState, responderIdx: number, cardId: string) {
  const pending = s.pending!
  const responder = s.players[responderIdx]
  const suggester = s.players[pending.suggester]
  pending.shownBy = responderIdx
  pending.resolved = true
  pending.queue = []

  if (!suggester.isBot) {
    // Reveal the exact card to the human suggester and auto-mark their notebook.
    pending.shownCard = cardId
    s.notebook[cardId] = '✗'
    log(s, 'disprove', `${responder.name} privately showed you the ${cardName(cardId)}.`, responder.name)
  } else {
    // Bot suggester "sees" the card.
    if (!suggester.seen!.includes(cardId)) suggester.seen!.push(cardId)
    botDeduce(s, pending.suggester)
    log(s, 'disprove', `${responder.name} showed a card to ${suggester.name}.`, responder.name)
  }
  finishDisprove(s)
}

function finishDisprove(s: GameState) {
  const pending = s.pending!
  pending.resolved = true

  if (pending.shownBy === undefined) {
    // Nobody disproved — powerful clue.
    log(s, 'no-disprove', `No one could disprove the suggestion. Interesting.`, undefined)
    // Bot suggester: infer solution cards where possible.
    const suggester = s.players[pending.suggester]
    if (suggester.isBot) botInferNoDisprove(s, pending.suggester)
  }

  const suggester = s.players[pending.suggester]
  if (suggester.isBot) {
    // Bot continues its turn (decide whether to accuse).
    s.phase = 'bot-turn'
    s.botStage = 'decide'
  } else {
    // Human decides what to do next.
    s.phase = 'suggesting'
  }
}

/* ------------------------------------------------------------------ *
 *  Accusation
 * ------------------------------------------------------------------ */

export function makeAccusation(
  state: GameState,
  suspect: string,
  device: string,
  location: string
): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  const sol = s.solution!
  const correct = suspect === sol.suspect && device === sol.device && location === sol.location

  log(
    s,
    'accuse',
    `${p.name} ACCUSES ${cardName(suspect)} · ${cardName(device)} · ${cardName(location)}!`,
    p.name,
    { suspect, device, location }
  )

  if (correct) {
    declareWinner(s, p, false)
  } else {
    p.out = true
    log(s, 'accuse', `Wrong. ${p.name} is compromised and out of the hunt.`, p.name)
    // If everyone is now out, reveal.
    const active = s.players.filter((pl) => !pl.out)
    if (active.length === 0) {
      s.phase = 'gameover'
      s.revealed = true
      s.winner = null
      log(s, 'win', `Everyone burned out. The eavesdropper walks free.`)
    } else if (active.length === 1) {
      declareWinner(s, active[0], true)
    } else {
      // Turn passes.
      const next = nextActiveIndex(s, s.currentPlayer)
      s.currentPlayer = next
      startTurn(s)
    }
  }
  return s
}

function declareWinner(s: GameState, p: Player, byDefault: boolean) {
  s.phase = 'gameover'
  s.revealed = true
  s.winner = p.id
  const sol = s.solution!
  if (byDefault) {
    log(s, 'win', `${p.name} is the last agent standing and closes the case.`)
  } else {
    log(
      s,
      'win',
      `Case closed. ${p.name} nailed it: ${cardName(sol.suspect)} used the ${cardName(
        sol.device
      )} in the ${cardName(sol.location)}.`
    )
  }
}

/* ------------------------------------------------------------------ *
 *  Notebook (human)
 * ------------------------------------------------------------------ */

export function cycleNote(state: GameState, cardId: string): GameState {
  const s = clone(state)
  const order: Array<GameState['notebook'][string]> = ['', '✗', '?', '✓']
  const cur = s.notebook[cardId] ?? ''
  const idx = order.indexOf(cur)
  s.notebook[cardId] = order[(idx + 1) % order.length]
  return s
}

/* ------------------------------------------------------------------ *
 *  Bot brain
 * ------------------------------------------------------------------ */

function botCandidates(bot: Player, category: Card['category']): string[] {
  const pool =
    category === 'suspect' ? SUSPECTS : category === 'device' ? DEVICES : LOCATIONS
  const seen = new Set(bot.seen ?? [])
  return pool.filter((c) => !seen.has(c.id)).map((c) => c.id)
}

function botDeduce(s: GameState, botIdx: number) {
  const bot = s.players[botIdx]
  if (!bot.deduced) bot.deduced = {}
  const cats: Card['category'][] = ['suspect', 'device', 'location']
  for (const cat of cats) {
    const cands = botCandidates(bot, cat)
    if (cands.length === 1) bot.deduced[cat] = cands[0]
  }
}

/** After a no-disprove, mark any of the three cards the bot already ruled out. */
function botInferNoDisprove(s: GameState, botIdx: number) {
  const bot = s.players[botIdx]
  const pending = s.pending!
  const three = cardsOf(pending.suggestion)
  // None of the OTHER players hold any of these three. So each is either in
  // the bot's own seen-set (innocent) or must be a solution card.
  const unknown = three.filter((c) => !bot.seen!.includes(c))
  // Group unknowns by category; if exactly one unknown in a category, it's the answer.
  for (const cat of ['suspect', 'device', 'location'] as const) {
    const inCat = unknown.filter((c) => CARD_BY_ID[c].category === cat)
    if (inCat.length === 1) {
      bot.deduced![cat] = inCat[0]
    }
  }
  botDeduce(s, botIdx)
}

function botChooseReveal(s: GameState, responderIdx: number, suggesterIdx: number, matching: string[]): string {
  // Simple: prefer to re-show something already public-ish; otherwise random.
  return pick(matching)
}

function botConfident(bot: Player): Solution | null {
  const d = bot.deduced ?? {}
  // Confident when each category is narrowed to one candidate.
  const suspect = d.suspect ?? single(botCandidates(bot, 'suspect'))
  const device = d.device ?? single(botCandidates(bot, 'device'))
  const location = d.location ?? single(botCandidates(bot, 'location'))
  if (suspect && device && location) return { suspect, device, location }
  return null
}

function single(arr: string[]): string | null {
  return arr.length === 1 ? arr[0] : null
}

/** A bot's most plausible accusation right now, with a "narrowness" score
 *  (product of remaining candidate counts — smaller means more sure). */
function botBestGuess(bot: Player): Solution & { narrowness: number } {
  const d = bot.deduced ?? {}
  const suspects = d.suspect ? [d.suspect] : botCandidates(bot, 'suspect')
  const devices = d.device ? [d.device] : botCandidates(bot, 'device')
  const locations = d.location ? [d.location] : botCandidates(bot, 'location')
  const safe = (arr: string[], cat: Card['category']) =>
    arr.length ? arr : botCandidates(bot, cat)
  const s = safe(suspects, 'suspect')
  const dv = safe(devices, 'device')
  const l = safe(locations, 'location')
  return {
    suspect: pick(s),
    device: pick(dv),
    location: pick(l),
    narrowness: s.length * dv.length * l.length,
  }
}

/**
 * Advance the current bot's turn by ONE micro-step. The UI calls this on a
 * timer so bot turns animate. Returns the new state; when the bot's suggestion
 * requires a human to reveal a card, this yields with phase 'disproving'.
 */
export function botStep(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  if (!p.isBot || s.phase === 'gameover') return s

  // If a human must pick a card to disprove, don't advance — wait for them.
  if (s.pending && s.pending.humanPick) return s

  const stage: BotStage = s.botStage ?? 'roll'

  switch (stage) {
    case 'roll': {
      const rolled = rollDice(s)
      Object.assign(s, rolled)
      s.botStage = 'move'
      return s
    }
    case 'move': {
      const target = botChooseRoom(s, p)
      const moved = moveTo(s, target)
      Object.assign(s, moved)
      s.botStage = 'sweep'
      return s
    }
    case 'sweep': {
      // Bots sweep occasionally for flavor + minor info; no real mic contact.
      if (Math.random() < 0.4) {
        const swept = ultrasonicSweep(s, false)
        Object.assign(s, swept)
      }
      s.botStage = 'suggest'
      return s
    }
    case 'suggest': {
      const suspect = pick(botCandidates(p, 'suspect').length ? botCandidates(p, 'suspect') : SUSPECTS.map((c) => c.id))
      const device = pick(botCandidates(p, 'device').length ? botCandidates(p, 'device') : DEVICES.map((c) => c.id))
      const sugg = makeSuggestion(s, suspect, device)
      Object.assign(s, sugg)
      // makeSuggestion set phase/botStage appropriately (or yielded to human).
      return s
    }
    case 'decide': {
      const confident = botConfident(p)
      if (confident) {
        const acc = makeAccusation(s, confident.suspect, confident.device, confident.location)
        Object.assign(s, acc)
        return s
      }
      // Not certain — but don't stall forever. Take a best guess when the field
      // is narrow, or grow desperate as the case drags on (like a real player
      // who eventually has to commit).
      const guess = botBestGuess(p)
      const desperate = s.turn > s.players.length * 12
      const narrow = guess.narrowness <= 8
      if (desperate || (narrow && Math.random() < 0.5)) {
        const acc = makeAccusation(s, guess.suspect, guess.device, guess.location)
        Object.assign(s, acc)
        return s
      }
      s.botStage = 'end'
      return s
    }
    case 'end':
    default: {
      const ended = endTurn(s)
      Object.assign(s, ended)
      return s
    }
  }
}

function botChooseRoom(s: GameState, bot: Player): string {
  // Prefer reachable rooms whose location is still an open candidate.
  const openLocs = new Set(botCandidates(bot, 'location'))
  const good = s.reachable.filter((r) => openLocs.has(r))
  if (good.length) return pick(good)
  return pick(s.reachable.length ? s.reachable : [bot.room])
}

/* ------------------------------------------------------------------ *
 *  Utility
 * ------------------------------------------------------------------ */

function clone(s: GameState): GameState {
  // structuredClone keeps it simple and avoids shared-reference bugs across React state.
  return structuredClone(s)
}
