import {
  BotStage,
  Card,
  ChallengeState,
  GameState,
  LogEntry,
  Notebook,
  NoteMark,
  Player,
  Solution,
  Suggestion,
} from './types'
import {
  ALL_CARDS,
  BUS_FARE,
  BUYABLE,
  buildBoard,
  CARD_BY_ID,
  CHALLENGE_TILES,
  DEVICES,
  GOTOJAIL_POS,
  JAIL_POS,
  LOCATIONS,
  MIMICO_POI,
  PLAYER_COLORS,
  Poi,
  PoiSet,
  RING_LEN,
  STATION_POSITIONS,
  SUSPECTS,
  Tile,
  TOKENS,
} from './data'
import { generateChallenge } from './challenges'

const START_MONEY = 1500
const GO_SALARY = 200
const INTEL_PRICE = 100
const JAIL_BAIL = 50

// --- Underworld economy ---
const PRODUCT_BATCH = 4 // units taken on consignment
const DEBT_PER_BATCH = 300 // owed to the Supplier for a batch (incl. interest)
const DEBT_TURNS = 4 // turns you have to repay before you're busted
const DROP_PRICE = 120 // cash per unit sold at a drop house
const SNITCH_BOUNTY = 90 // paid by police for informing on a rival
const HEAT_MAX = 5
const HEAT_BUST = 3 // police checkpoint busts you at/above this heat

/**
 * Per-game display names for the deduction location cards. Location labels are
 * dynamic (Mimico by default, or geolocated), but the card IDs are stable — so
 * we keep a tiny registry the display helpers consult, leaving all the
 * ID-based game logic untouched.
 */
const LOCATION_NAMES: Record<string, { name: string; address?: string }> = {}
function setLocationNames(board: Tile[]) {
  for (const k of Object.keys(LOCATION_NAMES)) delete LOCATION_NAMES[k]
  for (const t of board) {
    if (t.type === 'location' && t.locationId) {
      LOCATION_NAMES[t.locationId] = { name: t.label, address: t.address }
    }
  }
}

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
  return LOCATION_NAMES[id]?.name ?? CARD_BY_ID[id]?.name ?? id
}

export function cardAddress(id: string): string | undefined {
  return LOCATION_NAMES[id]?.address ?? CARD_BY_ID[id]?.address
}

export function money(n: number): string {
  return `$${n.toLocaleString('en-US')}`
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

export function createGame(configs: PlayerConfig[], clearance = 1, poi: PoiSet = MIMICO_POI): GameState {
  // 0. Build the board from the POI set and register dynamic location names.
  const board = buildBoard(poi)
  setLocationNames(board)

  // 1. Draw the solution: one card from each category.
  const solution: Solution = {
    suspect: pick(SUSPECTS).id,
    device: pick(DEVICES).id,
    location: pick(LOCATIONS).id,
  }

  // Deal a unique playing token to each agent.
  const tokens = shuffle(TOKENS.map((t) => t.id))

  // 2. Deal the rest round-robin.
  const rest = shuffle(
    ALL_CARDS.filter(
      (c) => c.id !== solution.suspect && c.id !== solution.device && c.id !== solution.location
    ).map((c) => c.id)
  )

  const players: Player[] = configs.map((cfg, i) => ({
    id: `p${i}`,
    name: cfg.name,
    isBot: cfg.isBot,
    hand: [],
    pos: 0, // everyone starts on Field HQ (GO)
    room: '',
    out: false,
    color: PLAYER_COLORS[i % PLAYER_COLORS.length],
    token: tokens[i % tokens.length],
    money: START_MONEY,
    properties: [],
    inJail: false,
    jailTurns: 0,
    heat: 0,
    product: 0,
    debt: 0,
    debtDue: null,
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
    notebooks: players.map(() => emptyNotebook()),
    log: [],
    turn: 0,
    dice: 0,
    moveFrom: 0,
    moveSteps: 0,
    clearance,
    board,
    place: poi.place,
    pot: 0,
    decisionPos: null,
    challenge: null,
    pending: null,
    winner: null,
    revealed: false,
    sweepClue: null,
    botStage: null,
    sweptThisTurn: false,
    snitchedThisTurn: false,
    rollSeq: 0,
  }

  // Pre-mark each human's own hand in their own notebook.
  players.forEach((p, i) => {
    if (!p.isBot) p.hand.forEach((id) => (state.notebooks[i][id] = '✗'))
  })

  log(state, 'system', `Case opened in ${poi.place}. ${players.length} agents on the board — find the eavesdropper.`)
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
  s.moveSteps = 0
  s.challenge = null
  s.pending = null
  s.sweepClue = null
  s.sweptThisTurn = false
  s.snitchedThisTurn = false
  s.decisionPos = null

  const p = s.players[s.currentPlayer]
  if (p.out) {
    // Skip eliminated players entirely.
    const next = nextActiveIndex(s, s.currentPlayer)
    if (next === -1) return
    s.currentPlayer = next
    return startTurn(s)
  }

  s.turn++

  // Underworld: the Supplier calls in an overdue debt — you get busted.
  if (p.debt > 0 && p.debtDue != null && s.turn > p.debtDue) {
    bust(s, s.currentPlayer, 'the Supplier called in the debt')
  }

  if (p.isBot) {
    s.phase = 'bot-turn'
    s.botStage = 'roll'
  } else {
    // Detained humans get the jail prompt before rolling.
    s.phase = p.inJail ? 'jail' : 'rolling'
    s.botStage = null
  }
}

/** Advance to the next active player (used by endTurn and bankruptcy). */
function advanceTurn(s: GameState) {
  if (s.phase === 'gameover') return
  const active = s.players.filter((p) => !p.out)
  if (active.length <= 1 && s.players.length > 1) {
    if (active[0]) declareWinner(s, active[0], true)
    return
  }
  const next = nextActiveIndex(s, s.currentPlayer)
  if (next === -1) return
  s.currentPlayer = next
  startTurn(s)
}

export function endTurn(state: GameState): GameState {
  const s = clone(state)
  advanceTurn(s)
  return s
}

/* ------------------------------------------------------------------ *
 *  Monopoly economy: jail, rent, buying, bankruptcy
 * ------------------------------------------------------------------ */

function sendToJail(s: GameState, idx: number) {
  const p = s.players[idx]
  p.pos = JAIL_POS
  p.room = ''
  p.inJail = true
  p.jailTurns = 0
  s.moveSteps = 0 // jump, not a hop
  log(s, 'money', `${p.name} was intercepted and sent to Detention.`, p.name)
}

function stationsOwnedBy(s: GameState, playerId: string): number {
  return STATION_POSITIONS.filter((pos) => s.board[pos].owner === playerId).length
}

/** Charge rent to the visitor. Returns true if it bankrupted them. */
function payRent(s: GameState, payerIdx: number, pos: number): boolean {
  const tile = s.board[pos]
  const ownerId = tile.owner!
  const payer = s.players[payerIdx]
  const ownerIdx = s.players.findIndex((pl) => pl.id === ownerId)
  if (ownerIdx < 0) return false

  let rent = tile.rent ?? 0
  if (tile.type === 'station') rent = 25 * stationsOwnedBy(s, ownerId)

  payer.money -= rent
  s.players[ownerIdx].money += rent
  log(
    s,
    'money',
    `${payer.name} paid ${money(rent)} rent to ${s.players[ownerIdx].name} for ${tile.label}.`,
    payer.name
  )

  if (payer.money < 0) {
    bankrupt(s, payerIdx)
    return true
  }
  return false
}

function bankrupt(s: GameState, idx: number) {
  const p = s.players[idx]
  p.out = true
  // Properties revert to the bank (available again).
  for (const pos of p.properties) if (s.board[pos]) s.board[pos].owner = undefined
  p.properties = []
  log(s, 'accuse', `${p.name} is bankrupt and out of the hunt.`, p.name)
  advanceTurn(s)
}

/** Buyable price/label for the current player's tile (or null). */
export function pendingPurchase(s: GameState): Tile | null {
  if (s.decisionPos == null) return null
  return s.board[s.decisionPos]
}

export function buyProperty(state: GameState): GameState {
  const s = clone(state)
  const idx = s.currentPlayer
  const p = s.players[idx]
  const pos = s.decisionPos
  if (pos == null) return state
  const tile = s.board[pos]
  if (!tile.price || p.money < tile.price || tile.owner) {
    s.decisionPos = null
    s.phase = 'suggesting'
    return s
  }
  p.money -= tile.price
  tile.owner = p.id
  p.properties.push(pos)
  log(s, 'money', `${p.name} bought ${tile.label} for ${money(tile.price)}.`, p.name)
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

export function declineBuy(state: GameState): GameState {
  const s = clone(state)
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

export function buyStoreIntel(state: GameState, buy: boolean): GameState {
  const s = clone(state)
  const idx = s.currentPlayer
  const p = s.players[idx]
  if (buy && p.money >= INTEL_PRICE) {
    p.money -= INTEL_PRICE
    log(s, 'money', `${p.name} paid ${money(INTEL_PRICE)} for a tip.`, p.name)
    grantIntel(s, idx, 'a convenience-store tip')
  }
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

/** Detained human pays bail to act, or serves their turn. */
export function payBail(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  if (p.money >= JAIL_BAIL) {
    p.money -= JAIL_BAIL
    p.inJail = false
    p.jailTurns = 0
    s.pot += JAIL_BAIL // bail fines feed the Safehouse jackpot
    log(s, 'money', `${p.name} paid ${money(JAIL_BAIL)} bail and walks.`, p.name)
    s.phase = 'rolling'
  }
  return s
}

export function serveJail(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  p.jailTurns++
  if (p.jailTurns >= 2) {
    p.inJail = false
    p.jailTurns = 0
    log(s, 'money', `${p.name} is released from Detention.`, p.name)
  } else {
    log(s, 'money', `${p.name} sits in Detention.`, p.name)
  }
  advanceTurn(s)
  return s
}

/* ------------------------------------------------------------------ *
 *  Underworld: the Supplier, drop houses, police, snitching
 * ------------------------------------------------------------------ */

/** Get busted: cash seized toward any debt, product & debt wiped, off to Detention. */
function bust(s: GameState, idx: number, reason: string) {
  const p = s.players[idx]
  const seized = Math.min(p.money, Math.max(0, p.debt))
  p.money -= seized
  p.product = 0
  p.debt = 0
  p.debtDue = null
  p.heat = 0
  log(
    s,
    'crime',
    `${p.name} got BUSTED — ${reason}.${seized > 0 ? ` ${money(seized)} seized.` : ''} Product gone.`,
    p.name
  )
  sendToJail(s, idx)
}

/** The tile the current player is deciding on (dealer/drophouse/store/buy). */
export function decisionTile(s: GameState): Tile | null {
  return s.decisionPos == null ? null : s.board[s.decisionPos]
}

export const PRODUCT_DEAL = { batch: PRODUCT_BATCH, debt: DEBT_PER_BATCH, turns: DEBT_TURNS, price: DROP_PRICE }

/** Take a batch of product on consignment from the Supplier. */
export function takeProduct(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  p.product += PRODUCT_BATCH
  p.debt += DEBT_PER_BATCH
  p.debtDue = p.debtDue == null ? s.turn + DEBT_TURNS : Math.min(p.debtDue, s.turn + DEBT_TURNS)
  p.heat = Math.min(HEAT_MAX, p.heat + 1)
  log(
    s,
    'crime',
    `${p.name} took ${PRODUCT_BATCH} product on consignment — owes ${money(p.debt)} by turn ${p.debtDue}.`,
    p.name
  )
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

/** Repay as much of the Supplier debt as you can afford. */
export function repayDebt(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  const pay = Math.min(p.money, p.debt)
  p.money -= pay
  p.debt -= pay
  if (p.debt <= 0) {
    p.debt = 0
    p.debtDue = null
    log(s, 'crime', `${p.name} paid off the Supplier (${money(pay)}). Debt clear.`, p.name)
  } else {
    log(s, 'crime', `${p.name} paid the Supplier ${money(pay)} — ${money(p.debt)} still owed.`, p.name)
  }
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

export function leaveDecision(state: GameState): GameState {
  const s = clone(state)
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

/** Sell all held product at a drop house — good cash, but heat and bust risk. */
export function sellProduct(state: GameState): GameState {
  const s = clone(state)
  const idx = s.currentPlayer
  const p = s.players[idx]
  if (p.product <= 0) {
    s.decisionPos = null
    s.phase = 'suggesting'
    return s
  }
  // Bust risk scales with how hot you already are.
  const bustChance = p.heat * 0.12
  if (Math.random() < bustChance) {
    bust(s, idx, 'a drop-house raid')
    concludeLanding(s, false)
    return s
  }
  const gross = p.product * DROP_PRICE
  p.money += gross
  log(s, 'crime', `${p.name} moved ${p.product} product for ${money(gross)}.`, p.name)
  p.product = 0
  p.heat = Math.min(HEAT_MAX, p.heat + 1)
  s.decisionPos = null
  s.phase = 'suggesting'
  return s
}

/** Rivals you could snitch on (active, not you). */
export function snitchTargets(s: GameState): number[] {
  return s.players.map((_, i) => i).filter((i) => i !== s.currentPlayer && !s.players[i].out)
}

export type SnitchLevel = 1 | 2 | 3

export const SNITCH_MOVES: { level: SnitchLevel; name: string; blurb: string }[] = [
  { level: 1, name: 'Anonymous tip', blurb: 'A quiet word. Small bounty, nudges their heat, keeps you clean.' },
  { level: 2, name: 'Rat them out', blurb: 'A named statement. Bigger bounty (more if they’re holding), but you get noticed too.' },
  { level: 3, name: 'Wear a wire', blurb: 'High-risk sting. Seize their product and maybe bust them — but it can backfire on YOU.' },
]

/** Expected bounty for a snitch level against a target (pre-backfire). */
export function snitchBounty(s: GameState, targetIdx: number, level: SnitchLevel): number {
  const t = s.players[targetIdx]
  if (!t) return 0
  if (level === 1) return 60
  if (level === 2) return 100 + t.product * 10
  return 140 + t.product * 15 + t.heat * 20
}

/**
 * Inform on a rival. Three moves of escalating reward and risk:
 *  1 tip  — small bounty, +1 their heat.
 *  2 rat  — scaled bounty, +2 their heat, +1 YOUR heat.
 *  3 wire — big bounty, +3 their heat, seize half their product, chance to bust
 *           them on the spot — but a 25% chance it backfires and burns you.
 */
export function snitch(state: GameState, targetIdx: number, level: SnitchLevel = 2): GameState {
  const s = clone(state)
  if (s.snitchedThisTurn) return state
  const p = s.players[s.currentPlayer]
  const t = s.players[targetIdx]
  if (!t || t.out || targetIdx === s.currentPlayer) return state

  s.snitchedThisTurn = true
  let bounty = snitchBounty(s, targetIdx, level)

  if (level === 1) {
    t.heat = Math.min(HEAT_MAX, t.heat + 1)
    p.money += bounty
    log(s, 'crime', `${p.name} dropped an anonymous tip on ${t.name} (+${money(bounty)}).`, p.name)
  } else if (level === 2) {
    t.heat = Math.min(HEAT_MAX, t.heat + 2)
    p.heat = Math.min(HEAT_MAX, p.heat + 1)
    p.money += bounty
    log(s, 'crime', `${p.name} ratted out ${t.name} for ${money(bounty)} — ${t.name} is getting hot.`, p.name)
  } else {
    const backfire = Math.random() < 0.25
    if (backfire) {
      bounty = Math.floor(bounty * 0.4)
      p.heat = Math.min(HEAT_MAX, p.heat + 2)
      p.money += bounty
      log(s, 'crime', `${p.name}'s wire on ${t.name} BACKFIRED — only ${money(bounty)} and the heat's on ${p.name} now.`, p.name)
    } else {
      t.heat = Math.min(HEAT_MAX, t.heat + 3)
      const seized = Math.ceil(t.product / 2)
      t.product -= seized
      p.money += bounty
      log(
        s,
        'crime',
        `${p.name} wired up ${t.name}: ${money(bounty)} bounty, ${seized} product seized.`,
        p.name
      )
      // A hot enough target gets busted on the spot.
      if (t.heat >= HEAT_BUST && Math.random() < 0.7) bust(s, targetIdx, `${p.name}'s wire`)
    }
  }
  return s
}

/** Which rival a bot would most want to snitch on (juiciest = most product/heat), or -1. */
export function botSnitchTarget(s: GameState): number {
  let best = -1
  let bestScore = 1 // require some payoff
  for (let i = 0; i < s.players.length; i++) {
    if (i === s.currentPlayer || s.players[i].out) continue
    const t = s.players[i]
    const score = t.product * 2 + t.heat
    if (score > bestScore) {
      bestScore = score
      best = i
    }
  }
  return best
}

/* ------------------------------------------------------------------ *
 *  Movement
 * ------------------------------------------------------------------ */

/** The ring tile the current player is standing on. */
export function currentTile(s: GameState): Tile {
  return s.board[s.players[s.currentPlayer].pos]
}

export function tileAt(s: GameState, pos: number): Tile {
  return s.board[((pos % RING_LEN) + RING_LEN) % RING_LEN]
}

/**
 * Roll and hop clockwise around the ring (Monopoly-style — no route choice).
 * Sets up the board hop animation, pays the GO salary when you pass Field HQ,
 * and resolves what the landing tile does (buy / rent / challenge / …).
 */
export function rollDice(state: GameState): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  const d = 1 + Math.floor(Math.random() * 6)
  s.dice = d
  s.rollSeq++
  s.moveFrom = p.pos
  s.moveSteps = d

  const from = p.pos
  const passedGo = from + d >= RING_LEN
  p.pos = (from + d) % RING_LEN
  const tile = s.board[p.pos]
  p.room = tile.type === 'location' ? tile.locationId! : ''

  log(s, 'move', `${p.name} rolled a ${d} → ${tile.label}.`, p.name)
  if (passedGo) {
    p.money += GO_SALARY
    log(s, 'money', `${p.name} passed Field HQ and collected ${money(GO_SALARY)}.`, p.name)
    grantIntel(s, s.currentPlayer, 'reached Field HQ')
  }

  applyLanding(s)
  return s
}

/** Decide what a landing tile does for the current player. */
function applyLanding(s: GameState) {
  const idx = s.currentPlayer
  const p = s.players[idx]
  const tile = s.board[p.pos]

  // Sent to detention.
  if (tile.type === 'gotojail') {
    sendToJail(s, idx)
    concludeLanding(s, false)
    return
  }

  // Safehouse (free parking): scoop the jackpot of accumulated bail fines.
  if (tile.type === 'corner' && s.pot > 0) {
    log(s, 'money', `${p.name} swept the Safehouse jackpot: ${money(s.pot)}.`, p.name)
    p.money += s.pot
    s.pot = 0
  }

  // Police checkpoint: hot players get busted, everyone else is waved through.
  if (tile.type === 'police') {
    if (p.heat >= HEAT_BUST) {
      bust(s, idx, 'failed a police checkpoint')
      concludeLanding(s, false)
      return
    }
    log(s, 'crime', `${p.name} passed the police checkpoint clean.`, p.name)
  }

  // Pay rent on someone else's property (may bankrupt).
  if (BUYABLE.has(tile.type) && tile.owner && tile.owner !== p.id) {
    const bankrupt = payRent(s, idx, p.pos)
    if (bankrupt) return
  }

  if (p.isBot) {
    // Bots resolve buy / store / challenge / dealer / drophouse in botStep('act').
    s.phase = 'bot-turn'
    return
  }

  // Human landing prompts.
  if (tile.type === 'dealer') {
    s.decisionPos = p.pos
    s.phase = 'dealer'
  } else if (tile.type === 'drophouse') {
    s.decisionPos = p.pos
    s.phase = 'drophouse'
  } else if (BUYABLE.has(tile.type) && !tile.owner) {
    s.decisionPos = p.pos
    s.phase = 'buying'
  } else if (tile.type === 'store') {
    s.decisionPos = p.pos
    s.phase = 'store'
  } else if (CHALLENGE_TILES.has(tile.type)) {
    s.challenge = generateChallenge(Math.random, s.clearance)
    s.phase = 'challenge'
  } else {
    s.phase = 'suggesting'
  }
}

/** After a landing that isn't a prompt (jail, plain tile): resume or end. */
function concludeLanding(s: GameState, _prompt: boolean) {
  const p = s.players[s.currentPlayer]
  if (p.isBot) {
    s.phase = 'bot-turn'
    s.botStage = 'decide'
  } else {
    s.phase = 'suggesting'
  }
}

/**
 * INTEL reward: rule one random innocent card off the notebook (human) or add
 * it to the bot's known-innocent set. Never touches a real solution card, so it
 * accelerates deduction without ever handing someone the win.
 */
export function grantIntel(s: GameState, playerIdx: number, reason: string): string | null {
  const p = s.players[playerIdx]
  const sol = s.solution!
  const solutionCards = new Set([sol.suspect, sol.device, sol.location])

  if (p.isBot) {
    const options = ALL_CARDS.filter((c) => !solutionCards.has(c.id) && !p.seen!.includes(c.id))
    if (!options.length) return null
    const card = pick(options).id
    p.seen!.push(card)
    botDeduce(s, playerIdx)
    return card
  }

  // Human: rule out a card not already marked off in this player's notebook.
  const nb = s.notebooks[playerIdx]
  const options = ALL_CARDS.filter((c) => !solutionCards.has(c.id) && nb[c.id] !== '✗')
  if (!options.length) return null
  const card = pick(options).id
  nb[card] = '✗'
  log(s, 'intel', `Intel (${reason}): ${cardName(card)} is cleared — ruled off your notebook.`, p.name)
  return card
}

/** Resolve the human's landing challenge. Success grants intel. */
export function resolveChallenge(state: GameState, success: boolean): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  const ch = s.challenge
  s.challenge = null
  if (ch) {
    if (success) {
      log(s, 'intel', `${p.name} cracked the ${ch.title}.`, p.name)
      grantIntel(s, s.currentPlayer, ch.title)
    } else {
      log(s, 'intel', `${p.name} failed the ${ch.title}. No intel this time.`, p.name)
    }
  }
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
  const onLocation = p.room !== '' // sweep tiles have no room
  const where = onLocation ? `the ${cardName(p.room)}` : `this sector`
  const inSolutionRoom = onLocation && p.room === sol.location
  const trueDevice = CARD_BY_ID[sol.device]

  let clue: string
  const seat = s.currentPlayer
  const annotate = !p.isBot // only auto-fill a human's own notebook
  if (realContact) {
    clue = `⚡ LIVE CONTACT — a device in ${where} is transmitting ultrasound right now.`
  } else if (inSolutionRoom && trueDevice.emits) {
    clue = `Emission detected in ${where}: the bug here is an ACTIVE emitter.`
    if (annotate) markCards(s, seat, devicesMatchingEmission(false), '✗') // rule out passive devices
  } else if (inSolutionRoom && !trueDevice.emits) {
    clue = `The bug in ${where} is silent on RF/ultrasound — a PASSIVE device.`
    if (annotate) markCards(s, seat, devicesMatchingEmission(true), '✗') // rule out active devices
  } else if (onLocation) {
    clue = `No emissions in ${where}. The active bug isn't planted here.`
    if (annotate) markCards(s, seat, [p.room], '✗') // this location is ruled out
  } else {
    clue = `Faint hiss in ${where}, nothing locks. Sweep from inside a room for a clean read.`
  }
  s.sweepClue = clue
  log(s, 'sweep', `${p.name} ran an ultrasonic sweep: ${clue}`, p.name)
  return s
}

/** Devices consistent with a sweep result, for auto-annotating the notebook. */
export function devicesMatchingEmission(emits: boolean): string[] {
  return DEVICES.filter((d) => !!d.emits === emits).map((d) => d.id)
}

/** Set a notebook mark for a set of cards in seat's notebook unless already '✓'. */
function markCards(s: GameState, seat: number, ids: string[], mark: '✗' | '?' | '✓') {
  const nb = s.notebooks[seat]
  if (!nb) return
  ids.forEach((id) => {
    if (nb[id] !== '✓') nb[id] = mark
  })
}

/* ------------------------------------------------------------------ *
 *  Suggestions + disprove resolution
 * ------------------------------------------------------------------ */

export function makeSuggestion(state: GameState, suspect: string, device: string): GameState {
  const s = clone(state)
  const p = s.players[s.currentPlayer]
  if (p.room === '') return state // must be standing in a location tile
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
    // Reveal privately to the human suggester and auto-mark THEIR notebook.
    // (The feed stays generic so the card isn't broadcast to everyone.)
    pending.shownCard = cardId
    s.notebooks[pending.suggester][cardId] = '✗'
    log(s, 'disprove', `${responder.name} showed a card to ${suggester.name}.`, responder.name)
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

export function cycleNote(state: GameState, cardId: string, seat: number): GameState {
  const s = clone(state)
  const nb = s.notebooks[seat]
  if (!nb) return s
  const order: NoteMark[] = ['', '✗', '?', '✓']
  const cur = nb[cardId] ?? ''
  const idx = order.indexOf(cur)
  nb[cardId] = order[(idx + 1) % order.length]
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
      // Handle detention before rolling.
      if (p.inJail) {
        if (p.money >= JAIL_BAIL * 3) {
          Object.assign(s, payBail(s))
          // payBail set phase 'rolling'; fall through to a real roll next tick.
          s.botStage = 'roll'
          return s
        }
        Object.assign(s, serveJail(s)) // ends the bot's turn
        return s
      }
      const rolled = rollDice(s)
      Object.assign(s, rolled)
      // rollDice may have bankrupted the bot (rent) and advanced the turn.
      if (s.currentPlayer !== state.currentPlayer || (s.phase as string) === 'gameover') return s
      s.botStage = 'act'
      return s
    }
    case 'act': {
      const tile = s.board[p.pos]
      // Economy: buy an unowned property the bot can afford.
      if (BUYABLE.has(tile.type) && !tile.owner && tile.price && p.money >= tile.price + 200) {
        p.money -= tile.price
        tile.owner = p.id
        p.properties.push(p.pos)
        log(s, 'money', `${p.name} bought ${tile.label} for ${money(tile.price)}.`, p.name)
      } else if (tile.type === 'store' && p.money >= INTEL_PRICE + 300) {
        p.money -= INTEL_PRICE
        grantIntel(s, s.currentPlayer, 'a store tip')
      } else if (tile.type === 'dealer') {
        // Repay if the debt is coming due; otherwise take a batch when clean.
        if (p.debt > 0) Object.assign(s, repayDebt(s))
        else if (p.heat < HEAT_BUST && Math.random() < 0.6) Object.assign(s, takeProduct(s))
      } else if (tile.type === 'drophouse' && p.product > 0) {
        Object.assign(s, sellProduct(s))
        if (s.currentPlayer !== state.currentPlayer) return s // busted → turn passed
      }

      if (tile.type === 'location') {
        // In a room — investigate with a suggestion. makeSuggestion drives the
        // disprove resolution and sets the next stage (or yields to a human).
        const suspect = pick(botCandidates(p, 'suspect').length ? botCandidates(p, 'suspect') : SUSPECTS.map((c) => c.id))
        const device = pick(botCandidates(p, 'device').length ? botCandidates(p, 'device') : DEVICES.map((c) => c.id))
        const sugg = makeSuggestion(s, suspect, device)
        Object.assign(s, sugg)
        return s
      }
      if (CHALLENGE_TILES.has(tile.type)) {
        // Bots auto-solve landing challenges and collect the intel.
        grantIntel(s, s.currentPlayer, tile.label)
      }
      s.botStage = 'decide'
      return s
    }
    case 'decide': {
      // Bots turn informant on a loaded rival (the human included).
      if (!s.snitchedThisTurn && Math.random() < 0.22) {
        const tgt = botSnitchTarget(s)
        if (tgt >= 0) Object.assign(s, snitch(s, tgt, Math.random() < 0.3 ? 3 : 2))
      }
      const confident = botConfident(s.players[s.currentPlayer])
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

/* ------------------------------------------------------------------ *
 *  Networked action registry (host-authoritative multiplayer)
 * ------------------------------------------------------------------ */

/**
 * Serializable game actions. A guest sends {action, args, seat}; the host looks
 * the action up here, validates it, applies it to the canonical state, and
 * broadcasts the result. Single-player uses the exact same table locally, so
 * there's one code path for turn logic in every mode.
 *
 * `seat` is the acting player's index — used for validation and for actions
 * (cycleNote) that aren't tied to whoever's turn it is.
 */
export const ACTIONS: Record<string, (s: GameState, seat: number, args: any[]) => GameState> = {
  rollDice: (s) => rollDice(s),
  makeSuggestion: (s, _seat, [suspect, device]) => makeSuggestion(s, suspect, device),
  makeAccusation: (s, _seat, [su, dv, lo]) => makeAccusation(s, su, dv, lo),
  ultrasonicSweep: (s, _seat, [realContact]) => ultrasonicSweep(s, !!realContact),
  resolveChallenge: (s, _seat, [ok]) => resolveChallenge(s, !!ok),
  buyProperty: (s) => buyProperty(s),
  declineBuy: (s) => declineBuy(s),
  buyStoreIntel: (s, _seat, [buy]) => buyStoreIntel(s, !!buy),
  takeProduct: (s) => takeProduct(s),
  repayDebt: (s) => repayDebt(s),
  sellProduct: (s) => sellProduct(s),
  leaveDecision: (s) => leaveDecision(s),
  snitch: (s, _seat, [idx, level]) => snitch(s, idx, level),
  payBail: (s) => payBail(s),
  serveJail: (s) => serveJail(s),
  endTurn: (s) => endTurn(s),
  humanReveal: (s, _seat, [cardId]) => humanReveal(s, cardId),
  cycleNote: (s, seat, [cardId]) => cycleNote(s, cardId, seat),
}

/** Actions any seat may take at any time (not gated to the current turn). */
const UNGATED = new Set(['cycleNote'])

/**
 * Is `seat` allowed to perform `action` right now? Prevents a client from
 * acting out of turn or as another player.
 */
export function validateAction(s: GameState, action: string, seat: number): boolean {
  if (!ACTIONS[action]) return false
  if (s.phase === 'gameover') return false
  if (UNGATED.has(action)) return true
  // Disprove is done by the specific responder, not the current player.
  if (action === 'humanReveal') return s.pending?.humanPick?.responder === seat
  // Everything else is a turn action.
  return s.currentPlayer === seat && !s.players[seat]?.out
}

/** Apply a validated remote action, or return the state unchanged if invalid. */
export function applyAction(s: GameState, action: string, seat: number, args: any[] = []): GameState {
  if (!validateAction(s, action, seat)) return s
  return ACTIONS[action](s, seat, args)
}

/* ------------------------------------------------------------------ *
 *  Utility
 * ------------------------------------------------------------------ */

function clone(s: GameState): GameState {
  // structuredClone keeps it simple and avoids shared-reference bugs across React state.
  return structuredClone(s)
}
