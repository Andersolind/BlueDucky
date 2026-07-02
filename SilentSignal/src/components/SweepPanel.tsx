import { useEffect, useRef, useState } from 'react'
import { useUltrasonic } from '../audio/useUltrasonic'

export const BEACON_TOKEN = 'SS-BEACON'

type Ultra = ReturnType<typeof useUltrasonic>

interface Props {
  ultra: Ultra
  onResult: (realContact: boolean) => void
  onCancel: () => void
}

const SWEEP_MS = 2200
// A clean beacon tone reads ~0.35–0.46 band-dominance; broadband ambient and
// audible-range sound stay under ~0.15. 0.28 sits safely in that gap.
const CONTACT_LEVEL = 0.28

export default function SweepPanel({ ultra, onResult, onCancel }: Props) {
  const [phase, setPhase] = useState<'idle' | 'listening' | 'done'>('idle')
  const [peak, setPeak] = useState(0)
  const contactRef = useRef(false)

  // Subscribe for a decoded beacon while sweeping.
  useEffect(() => {
    return ultra.subscribe((m) => {
      if (m.text.includes(BEACON_TOKEN)) contactRef.current = true
    })
  }, [ultra])

  // Track peak level while listening.
  useEffect(() => {
    if (phase !== 'listening') return
    setPeak((p) => Math.max(p, ultra.state.level))
    if (ultra.state.level > CONTACT_LEVEL) contactRef.current = true
  }, [ultra.state.level, phase])

  const runSweep = async () => {
    contactRef.current = false
    setPeak(0)
    setPhase('listening')
    const ok = await ultra.startListening()
    if (!ok) {
      // Mic blocked (permission or insecure context) — surface the error and
      // let the user retry or cancel instead of reporting a false "clear".
      setPhase('idle')
      return
    }
    window.setTimeout(async () => {
      await ultra.stopListening()
      setPhase('done')
      setTimeout(() => onResult(contactRef.current), 600)
    }, SWEEP_MS)
  }

  return (
    <div className="overlay" onClick={phase === 'idle' ? onCancel : undefined}>
      <div className="modal sweep" onClick={(e) => e.stopPropagation()}>
        <h2>📡 Ultrasonic Sweep</h2>
        <p className="modal-sub">
          Point your mic at the room. If the bug here is an active emitter — or a co-located player
          is broadcasting a beacon from the Signal Lab — you'll get a live contact. Otherwise you'll
          still learn whether an active bug is planted in this room.
        </p>

        <div className={`scope ${phase}`}>
          <div className="scope-ring" />
          <div className="scope-bar" style={{ height: `${Math.round(ultra.state.level * 100)}%` }} />
          <div className="scope-label">
            {phase === 'idle' && 'ready'}
            {phase === 'listening' && 'sweeping…'}
            {phase === 'done' && (contactRef.current ? '⚡ contact' : 'clear')}
          </div>
        </div>

        <div className="meter">
          <div className="meter-fill" style={{ width: `${Math.round(peak * 100)}%` }} />
        </div>

        {ultra.state.error && <div className="error">{ultra.state.error}</div>}

        <div className="modal-actions">
          {phase === 'idle' && (
            <>
              <button className="ghost" onClick={onCancel}>
                Cancel
              </button>
              <button className="primary" onClick={runSweep}>
                ▶ Run sweep
              </button>
            </>
          )}
          {phase === 'listening' && <div className="listening-note">Listening… hold still.</div>}
        </div>
      </div>
    </div>
  )
}
