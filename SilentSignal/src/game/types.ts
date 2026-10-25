import type { Tile } from './data'

export type CardCategory = 'suspect' | 'device' | 'location'

export interface Card {
  id: string
  name: string
  category: CardCategory
  /** Short flavor line shown on the card face. */
  hint: string
  /** Locations only: the real Mimico street address. */
  address?: string
  /**
   * Devices only: does this bug actively emit RF / ultrasound (detectable by a
   * sweep) or is it passive? Used by the in-game Ultrasonic Sweep clue.
   */
  emits?: boolean
  /** Devices only: acoustic-hardware complexity tier (1 basic … 3 black-ops). */
  tier?: number
  /** Devices only: the acoustic band / technique detail for that hardware. */
  band?: string
}

/** A Monopoly-style playing token assigned to each agent. */
export interface TokenDef {
  id: string
  icon: string
  name: string
  kind: 'car' | 'person' | 'item'
}

export interface Solution {
  suspect: string
  device: string
  location: string
}

/** One suggestion made on a turn: "It was SUSPECT with DEVICE in LOCATION". */
export interface Suggestion {
  suspect: string
  device: string
  location: string
}

export interface Player {
  id: string
  name: string
  isBot: boolean
  /** Card ids held in hand. */
  hand: string[]
  /** Ring tile index (0..23) the token occupies. */
  pos: number
  /** Location room id when standing on a location tile, else ''. */
  room: string
  /** Eliminated after a wrong accusation (can still disprove). */
  out: boolean
  color: string
  /** Assigned playing-token id (see TOKENS). */
  token: string
  /** Monopoly economy: cash on hand. */
  money: number
  /** Board positions of properties this player owns. */
  properties: number[]
  /** Currently detained. */
  inJail: boolean
  /** Turns spent in detention this stint. */
  jailTurns: number
  /** Underworld: wanted level 0..5 (police bust you when it's high). */
  heat: number
  /** Units of product held, sellable at a drop house. */
  product: number
  /** Money owed to the Supplier. */
  debt: number
  /** Turn by which the debt must be repaid, else you get busted. */
  debtDue: number | null
  /** Bots only: card ids known NOT to be in the solution (hand + cards seen). */
  seen?: string[]
  /** Bots only: cards this bot has deduced ARE the solution. */
  deduced?: { suspect?: string; device?: string; location?: string }
}

/** A record for the shared log / feed. */
export interface LogEntry {
  id: number
  turn: number
  kind:
    | 'move'
    | 'suggest'
    | 'disprove'
    | 'no-disprove'
    | 'accuse'
    | 'sweep'
    | 'system'
    | 'win'
    | 'intel'
    | 'money'
    | 'crime'
  actor?: string
  text: string
  /** For suggestions/accusations, the cards involved. */
  cards?: Suggestion
}

/** A cell in a player's detective notebook. */
export type NoteMark = '' | '✓' | '✗' | '?'

export interface Notebook {
  [cardId: string]: NoteMark
}

export type Phase =
  | 'lobby'
  | 'rolling'
  | 'moving'
  | 'suggesting'
  | 'disproving'
  | 'challenge'
  | 'buying'
  | 'store'
  | 'jail'
  | 'dealer'
  | 'drophouse'
  | 'accusing'
  | 'bot-turn'
  | 'gameover'

/** A landing clue-challenge presented to the human. */
export interface ChallengeState {
  kind: 'cipher' | 'sequence' | 'quiz'
  title: string
  prompt: string
  /** Multiple-choice options (quiz only). */
  options?: string[]
  /** Canonical answer, normalized-compared against the player's input. */
  answer: string
  hint?: string
  /** Human-readable description of the reward on success. */
  reward: string
}

export interface GameState {
  phase: Phase
  players: Player[]
  currentPlayer: number
  solution: Solution | null
  /** One detective notebook per player index (humans use theirs; bots ignore). */
  notebooks: Notebook[]
  log: LogEntry[]
  turn: number
  dice: number
  /** Where the last move started, for the board hop animation. */
  moveFrom: number
  /** How many tiles the last move advanced (for the animation). */
  moveSteps: number
  /** Clearance level (1 Rookie … 3 Black-Ops) — scales challenge difficulty. */
  clearance: number
  /** The 24 board tiles for this game (POI-driven, possibly from geolocation). */
  board: Tile[]
  /** Where the board is set — "Mimico" or a geolocated area name. */
  place: string
  /** Free-parking jackpot (fed by bail fines, collected on the Safehouse). */
  pot: number
  /** Position of a pending buy/store decision for the human. */
  decisionPos: number | null
  /** Active landing challenge for the human, if any. */
  challenge: ChallengeState | null
  /** Pending suggestion awaiting disproof resolution. */
  pending: PendingSuggestion | null
  winner: string | null
  /** True once the solution was revealed at game end. */
  revealed: boolean
  /** Latest ultrasonic-sweep clue text, if any. */
  sweepClue: string | null
  /** Micro-stage of the current bot's turn (null when it's a human's turn). */
  botStage: BotStage | null
  /** Whether the human has already used their sweep this turn. */
  sweptThisTurn: boolean
  /** Whether the current player has already snitched this turn. */
  snitchedThisTurn: boolean
  /** Monotonic roll counter, so clients can react to a new dice roll. */
  rollSeq: number
}

export type BotStage = 'roll' | 'act' | 'decide' | 'end'

export interface PendingSuggestion {
  suggestion: Suggestion
  suggester: number
  /** Responder indices still to be asked, in order. */
  queue: number[]
  /** Card shown to the suggester (only surfaced to the human suggester). */
  shownCard?: string
  /** Player index who disproved. */
  shownBy?: number
  /** Set when a HUMAN responder must choose which card to reveal. */
  humanPick?: { responder: number; options: string[] } | null
  /** True once resolution finished (shown or nobody could). */
  resolved: boolean
}
