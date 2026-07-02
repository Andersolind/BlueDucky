import { useEffect, useRef, useState } from 'react'
import { Player } from '../game/types'
import { TOKENS, TOKEN_BY_ID } from '../game/data'

interface Props {
  players: Player[]
  onDone: () => void
}

const KIND_LABEL: Record<string, string> = { car: 'VEHICLE', person: 'AGENT', item: 'GADGET' }
const SPIN_ICONS = TOKENS.map((t) => t.icon)

/**
 * Slot-machine token reveal: each agent's playing piece spins through the token
 * pool, then locks onto their assigned token one by one with a pop.
 */
export default function TokenDraw({ players, onDone }: Props) {
  // How many players have locked in so far.
  const [locked, setLocked] = useState(0)
  // The currently spinning icon shown on the not-yet-locked reels.
  const [spinIcon, setSpinIcon] = useState(SPIN_ICONS[0])
  const spinRef = useRef(0)

  useEffect(() => {
    const spin = window.setInterval(() => {
      spinRef.current = (spinRef.current + 1) % SPIN_ICONS.length
      setSpinIcon(SPIN_ICONS[spinRef.current])
    }, 70)

    // Lock players in one at a time.
    const timers: number[] = []
    players.forEach((_, i) => {
      timers.push(window.setTimeout(() => setLocked(i + 1), 700 + i * 650))
    })
    // Finish shortly after the last lock.
    timers.push(window.setTimeout(onDone, 700 + players.length * 650 + 1100))

    return () => {
      window.clearInterval(spin)
      timers.forEach((t) => window.clearTimeout(t))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="tokendraw">
      <div className="td-head">
        <div className="ch-tag">ASSIGNING TOKENS</div>
        <h1>Take your piece, agent.</h1>
        <p className="lede">Each operative is dealt a playing token. Locking in…</p>
      </div>

      <div className="td-grid">
        {players.map((p, i) => {
          const isLocked = i < locked
          const tok = TOKEN_BY_ID[p.token]
          return (
            <div
              key={p.id}
              className={`td-card ${isLocked ? 'locked' : 'spinning'}`}
              style={{ borderColor: p.color }}
            >
              <div className="td-name" style={{ color: p.color }}>
                {p.name}
                {p.isBot && <span className="td-bot">BOT</span>}
              </div>
              <div className={`td-reel ${isLocked ? 'pop' : ''}`}>
                {isLocked ? tok.icon : spinIcon}
              </div>
              <div className="td-token">
                {isLocked ? (
                  <>
                    <span className="td-tokname">{tok.name}</span>
                    <span className="td-kind">{KIND_LABEL[tok.kind]}</span>
                  </>
                ) : (
                  <span className="td-rolling">rolling…</span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <button className="ghost" onClick={onDone}>
        Skip ➜
      </button>
    </div>
  )
}
