import { GameState } from '../game/types'

export type NetRole = 'host' | 'guest'

/** What GameScreen needs from the networking layer to route actions. */
export interface NetHandle {
  role: NetRole
  /** The player index this client controls. */
  seat: number
  /** Host: set + broadcast the new authoritative state. (Unused by guests.) */
  commit: (state: GameState) => void
  /** Guest: send an action to the host to be applied authoritatively. */
  sendAction: (action: string, args: any[]) => void
}

/** A seat in the lobby before the game starts. */
export interface Seat {
  seat: number
  name: string
  isBot: boolean
  /** True for the local client's seat. */
  you?: boolean
}

/* Wire protocol between host and guests (over the data channel / relay). */
export type NetMsg =
  | { t: 'state'; state: GameState } // host → guests: authoritative snapshot
  | { t: 'action'; action: string; args: any[]; seat: number } // guest → host
  | { t: 'seat'; seat: number; roster: { name: string; isBot: boolean }[] } // host → guest
  | { t: 'start' } // host → guests: game beginning
