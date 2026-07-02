import { useState } from 'react'
import { GameState } from '../game/types'
import { SUSPECTS, DEVICES, LOCATIONS, CARD_BY_ID } from '../game/data'
import { cardName } from '../game/engine'

function Overlay({ children, onClose }: { children: React.ReactNode; onClose?: () => void }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  )
}

function Choices({
  cards,
  value,
  onPick,
}: {
  cards: { id: string; name: string; hint: string }[]
  value: string
  onPick: (id: string) => void
}) {
  return (
    <div className="choice-grid">
      {cards.map((c) => (
        <button
          key={c.id}
          className={`choice ${value === c.id ? 'sel' : ''}`}
          onClick={() => onPick(c.id)}
        >
          <span className="choice-name">{c.name}</span>
          <span className="choice-hint">{c.hint}</span>
        </button>
      ))}
    </div>
  )
}

/* ---------------- Suggest ---------------- */

export function SuggestModal({
  state,
  onSubmit,
  onClose,
}: {
  state: GameState
  onSubmit: (suspect: string, device: string) => void
  onClose: () => void
}) {
  const [suspect, setSuspect] = useState('')
  const [device, setDevice] = useState('')
  const room = state.players[state.currentPlayer].room

  return (
    <Overlay onClose={onClose}>
      <h2>Make a Suggestion</h2>
      <p className="modal-sub">
        Investigating the <b>{cardName(room)}</b> (your current room). Rivals must disprove you if
        they can.
      </p>
      <h4>Suspect</h4>
      <Choices cards={SUSPECTS} value={suspect} onPick={setSuspect} />
      <h4>Device</h4>
      <Choices cards={DEVICES} value={device} onPick={setDevice} />
      <div className="modal-actions">
        <button className="ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary"
          disabled={!suspect || !device}
          onClick={() => onSubmit(suspect, device)}
        >
          Put it to the room
        </button>
      </div>
    </Overlay>
  )
}

/* ---------------- Accuse ---------------- */

export function AccuseModal({
  onSubmit,
  onClose,
}: {
  onSubmit: (suspect: string, device: string, location: string) => void
  onClose: () => void
}) {
  const [suspect, setSuspect] = useState('')
  const [device, setDevice] = useState('')
  const [location, setLocation] = useState('')

  return (
    <Overlay onClose={onClose}>
      <h2 className="danger-title">Final Accusation</h2>
      <p className="modal-sub warn">
        No going back. Name all three correctly to close the case. Get any wrong and you're burned —
        out of the hunt for good.
      </p>
      <h4>Suspect</h4>
      <Choices cards={SUSPECTS} value={suspect} onPick={setSuspect} />
      <h4>Device</h4>
      <Choices cards={DEVICES} value={device} onPick={setDevice} />
      <h4>Location</h4>
      <Choices cards={LOCATIONS} value={location} onPick={setLocation} />
      <div className="modal-actions">
        <button className="ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          className="danger"
          disabled={!suspect || !device || !location}
          onClick={() => onSubmit(suspect, device, location)}
        >
          ⚑ Accuse
        </button>
      </div>
    </Overlay>
  )
}

/* ---------------- Human disprove picker ---------------- */

export function DisproveModal({
  state,
  onReveal,
}: {
  state: GameState
  onReveal: (cardId: string) => void
}) {
  const pending = state.pending
  if (!pending?.humanPick) return null
  const suggester = state.players[pending.suggester]
  const options = pending.humanPick.options

  return (
    <Overlay>
      <h2>You can disprove {suggester.name}</h2>
      <p className="modal-sub">
        {suggester.name} suggested <b>{cardName(pending.suggestion.suspect)}</b> ·{' '}
        <b>{cardName(pending.suggestion.device)}</b> · <b>{cardName(pending.suggestion.location)}</b>.
        You hold {options.length > 1 ? 'these matching cards' : 'this matching card'} — reveal one
        (only they will see which).
      </p>
      <div className="choice-grid">
        {options.map((id) => (
          <button key={id} className="choice sel" onClick={() => onReveal(id)}>
            <span className="choice-name">{CARD_BY_ID[id].name}</span>
            <span className="choice-hint">{CARD_BY_ID[id].hint}</span>
          </button>
        ))}
      </div>
    </Overlay>
  )
}
