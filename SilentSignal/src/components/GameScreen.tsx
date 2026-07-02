import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { GameState } from '../game/types'
import {
  buyProperty,
  buyStoreIntel,
  cardName,
  currentTile,
  cycleNote,
  declineBuy,
  endTurn,
  humanReveal,
  makeAccusation,
  makeSuggestion,
  money,
  payBail,
  resolveChallenge,
  rollDice,
  serveJail,
  ultrasonicSweep,
} from '../game/engine'
import { useUltrasonic } from '../audio/useUltrasonic'
import Board3D from './Board3D'
import Notebook from './Notebook'
import Feed from './Feed'
import SweepPanel from './SweepPanel'
import ChallengeModal from './ChallengeModal'
// Lazy — pulls in three.js only when someone actually gets detained.
const JailScene = lazy(() => import('./JailScene'))
import { AccuseModal, BuyModal, DisproveModal, JailModal, StoreModal, SuggestModal } from './Modals'
import { CARD_BY_ID, TOKEN_BY_ID } from '../game/data'

type Ultra = ReturnType<typeof useUltrasonic>

interface Props {
  state: GameState
  setState: React.Dispatch<React.SetStateAction<GameState | null>>
  ultra: Ultra
  onQuit: () => void
}

export default function GameScreen({ state, setState, ultra, onQuit }: Props) {
  const [showSuggest, setShowSuggest] = useState(false)
  const [showAccuse, setShowAccuse] = useState(false)
  const [showSweep, setShowSweep] = useState(false)
  const [suggestedThisTurn, setSuggestedThisTurn] = useState(false)

  const me = state.players.find((p) => !p.isBot)!
  const current = state.players[state.currentPlayer]
  const myTurn = current.id === me.id && !me.out
  const gameover = state.phase === 'gameover'

  // Reset per-turn UI flags when the turn changes.
  useEffect(() => {
    setSuggestedThisTurn(false)
    setShowSuggest(false)
    setShowAccuse(false)
    setShowSweep(false)
  }, [state.turn, state.currentPlayer])

  // Play the acoustic-array detention sequence the moment YOU get jailed.
  const [jailFx, setJailFx] = useState(false)
  const wasJailed = useRef(me.inJail)
  useEffect(() => {
    if (me.inJail && !wasJailed.current) setJailFx(true)
    wasJailed.current = me.inJail
  }, [me.inJail])

  const update = (next: GameState) => setState(next)
  const tile = currentTile(state)

  const onRoll = () => update(rollDice(state))
  const onSuggest = (suspect: string, device: string) => {
    setShowSuggest(false)
    setSuggestedThisTurn(true)
    update(makeSuggestion(state, suspect, device))
  }
  const onAccuse = (s: string, d: string, l: string) => {
    setShowAccuse(false)
    update(makeAccusation(state, s, d, l))
  }
  const onSweepResult = (realContact: boolean) => {
    setShowSweep(false)
    update(ultrasonicSweep(state, realContact))
  }
  const onChallenge = (success: boolean) => update(resolveChallenge(state, success))
  const onReveal = (cardId: string) => update(humanReveal(state, cardId))
  const onNote = (cardId: string) => update(cycleNote(state, cardId))
  const onEnd = () => update(endTurn(state))
  const onBuy = () => update(buyProperty(state))
  const onDecline = () => update(declineBuy(state))
  const onStoreBuy = () => update(buyStoreIntel(state, true))
  const onStoreSkip = () => update(buyStoreIntel(state, false))
  const onBail = () => update(payBail(state))
  const onServe = () => update(serveJail(state))

  return (
    <div className="game">
      <section className="col-left">
        <TurnBanner state={state} myTurn={myTurn} />
        <Board3D state={state} />

        {myTurn && !gameover && (
          <ActionBar
            state={state}
            onLocation={tile.type === 'location'}
            canSweep={tile.type === 'location' || tile.type === 'sweep'}
            suggestedThisTurn={suggestedThisTurn}
            onRoll={onRoll}
            onOpenSuggest={() => setShowSuggest(true)}
            onOpenAccuse={() => setShowAccuse(true)}
            onOpenSweep={() => setShowSweep(true)}
            onEnd={onEnd}
          />
        )}

        {state.pending?.shownCard && myTurn && (
          <div className="shown-card">
            🃏 You were shown the <b>{cardName(state.pending.shownCard)}</b> — it's marked off in your
            notebook.
          </div>
        )}
        {state.sweepClue && myTurn && <div className="sweep-clue">📡 {state.sweepClue}</div>}

        <Feed state={state} />
      </section>

      <aside className="col-right">
        <Notebook state={state} onToggle={onNote} />
      </aside>

      {showSuggest && (
        <SuggestModal state={state} onSubmit={onSuggest} onClose={() => setShowSuggest(false)} />
      )}
      {showAccuse && <AccuseModal onSubmit={onAccuse} onClose={() => setShowAccuse(false)} />}
      {showSweep && (
        <SweepPanel ultra={ultra} onResult={onSweepResult} onCancel={() => setShowSweep(false)} />
      )}
      {myTurn && state.phase === 'challenge' && state.challenge && (
        <ChallengeModal challenge={state.challenge} onResolve={onChallenge} />
      )}
      {myTurn && state.phase === 'buying' && <BuyModal state={state} onBuy={onBuy} onDecline={onDecline} />}
      {myTurn && state.phase === 'store' && (
        <StoreModal state={state} onBuy={onStoreBuy} onSkip={onStoreSkip} />
      )}
      {myTurn && state.phase === 'jail' && <JailModal state={state} onBail={onBail} onServe={onServe} />}
      {state.pending?.humanPick && <DisproveModal state={state} onReveal={onReveal} />}

      {jailFx && (
        <Suspense fallback={null}>
          <JailScene
            icon={TOKEN_BY_ID[me.token]?.icon ?? '★'}
            color={me.color}
            name={me.name}
            onDone={() => setJailFx(false)}
          />
        </Suspense>
      )}

      {gameover && <GameOver state={state} me={me} onQuit={onQuit} />}
    </div>
  )
}

/* ---------------- Turn banner ---------------- */

function TurnBanner({ state, myTurn }: { state: GameState; myTurn: boolean }) {
  const current = state.players[state.currentPlayer]
  return (
    <div className={`turn-banner ${myTurn ? 'mine' : ''}`}>
      <div className="players">
        {state.players.map((p, i) => (
          <span
            key={p.id}
            className={`player-chip ${i === state.currentPlayer ? 'active' : ''} ${
              p.out ? 'out' : ''
            }`}
            style={{ borderColor: p.color }}
            title={TOKEN_BY_ID[p.token]?.name}
          >
            <span className="pc-token">{TOKEN_BY_ID[p.token]?.icon}</span>
            {p.name}
            {p.inJail && ' 🚧'}
            <span className="pc-money">{money(p.money)}</span>
            {p.out && ' ✗'}
          </span>
        ))}
      </div>
      <div className="turn-status">
        {state.phase === 'bot-turn' && (
          <span>
            <span className="thinking" /> {current.name} is working the case…
          </span>
        )}
        {myTurn && state.phase === 'rolling' && <span>Your move, {current.name}. Roll to hop the ring.</span>}
        {myTurn && state.phase === 'challenge' && <span>A clue challenge blocks your path…</span>}
        {myTurn && state.phase === 'suggesting' && <span>Investigate, sweep, or accuse.</span>}
        {state.phase === 'disproving' && state.pending?.humanPick && (
          <span>You must reveal a card…</span>
        )}
      </div>
    </div>
  )
}

/* ---------------- Action bar ---------------- */

function ActionBar({
  state,
  onLocation,
  canSweep,
  suggestedThisTurn,
  onRoll,
  onOpenSuggest,
  onOpenAccuse,
  onOpenSweep,
  onEnd,
}: {
  state: GameState
  onLocation: boolean
  canSweep: boolean
  suggestedThisTurn: boolean
  onRoll: () => void
  onOpenSuggest: () => void
  onOpenAccuse: () => void
  onOpenSweep: () => void
  onEnd: () => void
}) {
  const phase = state.phase
  return (
    <div className="action-bar">
      {phase === 'rolling' && (
        <button className="primary big" onClick={onRoll}>
          🎲 Roll the dice
        </button>
      )}
      {phase === 'suggesting' && (
        <>
          {canSweep && (
            <button
              className="secondary"
              disabled={state.sweptThisTurn}
              onClick={onOpenSweep}
              title="Listen for an active bug here"
            >
              📡 Ultrasonic sweep{state.sweptThisTurn ? ' ✓' : ''}
            </button>
          )}
          {onLocation ? (
            <button className="primary" disabled={suggestedThisTurn} onClick={onOpenSuggest}>
              ❓ Suggest{suggestedThisTurn ? ' ✓' : ''}
            </button>
          ) : (
            <span className="ab-hint">Not in a room — roll onto a location to investigate.</span>
          )}
          <button className="danger" onClick={onOpenAccuse}>
            ⚑ Accuse
          </button>
          <button className="ghost" onClick={onEnd}>
            End turn ➜
          </button>
        </>
      )}
    </div>
  )
}

/* ---------------- Game over ---------------- */

function GameOver({ state, me, onQuit }: { state: GameState; me: GameState['players'][0]; onQuit: () => void }) {
  const sol = state.solution!
  const winner = state.players.find((p) => p.id === state.winner)
  const iWon = winner?.id === me.id
  return (
    <div className="overlay">
      <div className="modal gameover">
        <div className={`go-badge ${iWon ? 'win' : winner ? 'lose' : 'draw'}`}>
          {iWon ? '★ CASE CLOSED' : winner ? 'CASE CLOSED' : 'COLD CASE'}
        </div>
        <h2>
          {iWon
            ? 'You unmasked the eavesdropper.'
            : winner
            ? `${winner.name} cracked it first.`
            : 'The eavesdropper got away.'}
        </h2>
        <div className="solution-reveal">
          <SolCard label="Eavesdropper" id={sol.suspect} />
          <SolCard label="Device" id={sol.device} />
          <SolCard label="Location" id={sol.location} />
        </div>
        <div className="modal-actions center">
          <button className="primary big" onClick={onQuit}>
            ▶ New case
          </button>
        </div>
      </div>
    </div>
  )
}

function SolCard({ label, id }: { label: string; id: string }) {
  const c = CARD_BY_ID[id]
  return (
    <div className="sol-card">
      <span className="sol-label">{label}</span>
      <span className="sol-name">{c.name}</span>
      <span className="sol-hint">{c.hint}</span>
    </div>
  )
}
