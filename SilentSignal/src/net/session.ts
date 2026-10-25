import { GameState } from '../game/types'
import { applyAction } from '../game/engine'
import { Transport } from './transport'
import { NetMsg } from './types'

/**
 * HostSession — the authoritative side of an online game.
 *
 * The host owns the canonical GameState. Guests connect (one Transport each),
 * are assigned seats, and send {action} messages; the host validates + applies
 * them via the engine's action registry and broadcasts the new snapshot to
 * everyone. This is transport-agnostic: pass WebRTC data channels in production
 * or mock transports in tests.
 */
export class HostSession {
  private guests = new Map<string, { t: Transport; seat: number }>()
  private state: GameState | null = null
  onState?: (s: GameState) => void

  /** Seat 0 is the host; guests take 1, 2, … in join order. */
  addGuest(t: Transport): number {
    const seat = this.guests.size + 1
    this.guests.set(t.peerId, { t, seat })
    t.onMessage((m) => this.handle(m, seat))
    t.onClose(() => this.guests.delete(t.peerId))
    // Tell the guest its seat.
    t.send({ t: 'seat', seat, roster: [] })
    if (this.state) t.send({ t: 'state', state: this.state })
    return seat
  }

  /** Called by the host UI whenever it commits a new state (local move or bot). */
  setState(s: GameState) {
    this.state = s
    this.broadcast({ t: 'state', state: s })
  }

  private handle(m: NetMsg, seat: number) {
    if (m.t !== 'action' || !this.state) return
    // Trust the connection's seat, not the claimed one.
    const next = applyAction(this.state, m.action, seat, m.args)
    if (next !== this.state) {
      this.state = next
      this.onState?.(next) // let the host UI re-render + keep driving bots
      this.broadcast({ t: 'state', state: next })
    }
  }

  broadcast(msg: NetMsg) {
    for (const g of this.guests.values()) g.t.send(msg)
  }

  seatCount() {
    return this.guests.size + 1
  }
}

/**
 * GuestSession — a client that renders the host's authoritative state and sends
 * its own actions upstream.
 */
export class GuestSession {
  seat = -1
  onState?: (s: GameState) => void
  onSeat?: (seat: number) => void

  constructor(private host: Transport) {
    host.onMessage((m) => {
      if (m.t === 'seat') {
        this.seat = m.seat
        this.onSeat?.(m.seat)
      } else if (m.t === 'state') {
        this.onState?.(m.state)
      }
    })
  }

  sendAction(action: string, args: any[]) {
    this.host.send({ t: 'action', action, args, seat: this.seat })
  }
}
