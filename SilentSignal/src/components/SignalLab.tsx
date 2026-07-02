import { useEffect, useRef, useState } from 'react'
import { useUltrasonic } from '../audio/useUltrasonic'
import { BEACON_TOKEN } from './SweepPanel'

type Ultra = ReturnType<typeof useUltrasonic>

interface Props {
  ultra: Ultra
  onClose: () => void
}

interface RxLine {
  id: number
  text: string
}

let RX_SEQ = 1

export default function SignalLab({ ultra, onClose }: Props) {
  const [msg, setMsg] = useState('the walls have ears')
  const [rx, setRx] = useState<RxLine[]>([])
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    return ultra.subscribe((m) => {
      setRx((prev) => [...prev, { id: RX_SEQ++, text: m.text }].slice(-30))
    })
  }, [ultra])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [rx])

  const send = () => ultra.transmit(msg)
  const sendBeacon = () => ultra.transmit(`${BEACON_TOKEN}::live`)

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal lab" onClick={(e) => e.stopPropagation()}>
        <div className="lab-head">
          <h2>⚡ Signal Lab</h2>
          <button className="ghost" onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="modal-sub">
          The same engine that powers the game's sweep — a real data-over-sound modem. Encode text
          into an 18–21 kHz multi-tone FSK burst on one device, decode it on another (or the same
          one, speaker → mic). This is the browser cousin of the Python decoder in this repo.
        </p>

        <div className="lab-grid">
          <div className="lab-col">
            <h4>Transmit</h4>
            <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={3} maxLength={120} />
            <div className="lab-buttons">
              <button className="primary" disabled={ultra.state.transmitting} onClick={send}>
                {ultra.state.transmitting ? '📢 transmitting…' : '📢 Transmit'}
              </button>
              <button className="ghost" disabled={ultra.state.transmitting} onClick={sendBeacon}>
                ⚡ Broadcast game beacon
              </button>
            </div>
            <p className="tiny">
              Tip: keep it short. Bytes are sent as 4-bit symbols at ~17 symbols/sec, so long
              strings take a while and are more error-prone over the air.
            </p>
          </div>

          <div className="lab-col">
            <div className="lab-rx-head">
              <h4>Receive</h4>
              <button
                className={`chip ${ultra.state.listening ? 'on' : ''}`}
                onClick={() => (ultra.state.listening ? ultra.stopListening() : ultra.startListening())}
              >
                {ultra.state.listening ? '● listening' : '○ start mic'}
              </button>
            </div>
            <div className="lab-meter">
              <div className="lab-meter-fill" style={{ width: `${Math.round(ultra.state.level * 100)}%` }} />
            </div>
            <div className="lab-rx" ref={listRef}>
              {rx.length === 0 && <div className="lab-rx-empty">decoded messages appear here…</div>}
              {rx.map((l) => (
                <div className="lab-rx-line" key={l.id}>
                  <span className="lab-rx-time">rx</span> {l.text}
                </div>
              ))}
            </div>
            {ultra.state.error && <div className="error">{ultra.state.error}</div>}
          </div>
        </div>

        <div className="lab-foot">
          <b>Two-device demo:</b> open this page on a phone and a laptop side by side. Start the mic
          on one, hit Transmit on the other. Works best in a quiet room at medium volume.
        </div>
      </div>
    </div>
  )
}
