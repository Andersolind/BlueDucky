import { useEffect } from 'react'

interface Props {
  icon: string
  name: string
  reason?: string
  onDone: () => void
}

const DURATION = 3400

/**
 * GTA-style "BUSTED" screen: grayscale vignette, red/blue police-light flashes,
 * and big slamming title text. Plays when the cops bust the human player.
 */
export default function BustScene({ icon, name, reason, onDone }: Props) {
  useEffect(() => {
    const t = window.setTimeout(onDone, DURATION)
    return () => window.clearTimeout(t)
  }, [onDone])

  return (
    <div className="overlay bust-overlay" onClick={onDone}>
      <div className="bust-lights">
        <span className="bust-light red" />
        <span className="bust-light blue" />
      </div>
      <div className="bust-vignette" />
      <div className="bust-content">
        <div className="bust-cuff">
          <span className="bust-token">{icon}</span>
          <span className="bust-chain">⛓️</span>
        </div>
        <div className="bust-title">BUSTED</div>
        <div className="bust-sub">
          {name} got pinched{reason ? ` — ${reason}` : ''}. Cash seized, product gone.
        </div>
        <div className="bust-skip">click to continue</div>
      </div>
    </div>
  )
}
