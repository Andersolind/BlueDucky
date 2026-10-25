import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { GameState } from '../game/types'
import {
  buyProperty,
  buyStoreIntel,
  cardAddress,
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
  takeProduct,
  repayDebt,
  sellProduct,
  leaveDecision,
  snitch,
  snitchTargets,
  ultrasonicSweep,
} from '../game/engine'
import { useUltrasonic } from '../audio/useUltrasonic'
import Board3D from './Board3D'
import Notebook from './Notebook'
import Feed from './Feed'
import SweepPanel from './SweepPanel'
import ChallengeModal from './ChallengeModal'
import BustScene from './BustScene'
// Lazy — pulls in three.js only when the effect actually plays.
const JailScene = lazy(() => import('./JailScene'))
const Dice3D = lazy(() => import('./Dice3D'))
import {
  AccuseModal,
  BuyModal,
  DealerModal,
  DisproveModal,
  DropHouseModal,
  JailModal,
  SnitchModal,
  StoreModal,
  SuggestModal,
} from './Modals'
import { ACTIONS } from '../game/engine'
import { ALL_CARDS, CARD_BY_ID, TOKEN_BY_ID } from '../game/data'
import { sfx } from '../game/sfx'
import { NetHandle } from '../net/types'

type Ultra = ReturnType<typeof useUltrasonic>

interface Props {
  state: GameState
  setState: React.Dispatch<React.SetStateAction<GameState | null>>
  ultra: Ultra
  onQuit: () => void
  /** Present in online games; null for local play. */
  net?: NetHandle | null
}

export default function GameScreen({ state, setState, ultra, onQuit, net }: Props) {
  const [showSuggest, setShowSuggest] = useState(false)
  const [showAccuse, setShowAccuse] = useState(false)
  const [showSweep, setShowSweep] = useState(false)
  const [showSnitch, setShowSnitch] = useState(false)
  const [suggestedThisTurn, setSuggestedThisTurn] = useState(false)

  // Which seat this client controls (local play = the one human, seat found by index).
  const seat = net ? net.seat : Math.max(0, state.players.findIndex((p) => !p.isBot))
  const role: 'single' | 'host' | 'guest' = net ? net.role : 'single'
  const me = state.players[seat] ?? state.players[0]
  const current = state.players[state.currentPlayer]
  const myTurn = state.currentPlayer === seat && !me.out
  const gameover = state.phase === 'gameover'

  // Commit a locally-computed state (single: setState; host: setState + broadcast).
  const commit = (next: GameState) => {
    if (net) net.commit(next)
    else setState(next)
  }
  // Route a game action. Guests send to the host; host/single apply locally.
  const act = (action: string, ...args: any[]) => {
    if (role === 'guest') net!.sendAction(action, args)
    else commit(ACTIONS[action](state, seat, args))
  }

  // Reset per-turn UI flags when the turn changes.
  useEffect(() => {
    setSuggestedThisTurn(false)
    setShowSuggest(false)
    setShowAccuse(false)
    setShowSweep(false)
    setShowSnitch(false)
  }, [state.turn, state.currentPlayer])

  // When YOU get sent to Detention, play a cinematic. A police BUST (drop-house
  // raid / checkpoint / overdue debt) → GTA-style "BUSTED". The Interception
  // go-to-jail tile → the acoustic-array detention scene.
  const [jailFx, setJailFx] = useState(false)
  const [bustFx, setBustFx] = useState<string | null>(null)
  const wasJailed = useRef(me.inJail)
  useEffect(() => {
    if (me.inJail && !wasJailed.current) {
      const bustLog = state.log
        .slice(0, 3)
        .find((e) => e.kind === 'crime' && e.actor === me.name && /BUSTED/.test(e.text))
      if (bustLog) {
        const m = bustLog.text.match(/BUSTED — (.+?)\./)
        setBustFx(m ? m[1] : 'the cops got you')
        sfx('bust')
      } else {
        setJailFx(true)
        sfx('jail')
      }
    }
    wasJailed.current = me.inJail
  }, [me.inJail])

  // Sound effects driven by the newest feed entry (covers bots too).
  const lastLogId = useRef(state.log[0]?.id)
  useEffect(() => {
    const e = state.log[0]
    if (!e || e.id === lastLogId.current) return
    lastLogId.current = e.id
    if (e.kind === 'win') sfx(state.winner === me.id ? 'win' : e.text.includes('walks free') ? 'lose' : 'win')
    else if (e.kind === 'intel') sfx('intel')
    else if (e.kind === 'sweep') sfx('sweep')
    else if (e.kind === 'money' && /rent/.test(e.text)) sfx('rent')
    else if (e.kind === 'money' && /bought|jackpot/.test(e.text)) sfx('buy')
  }, [state.log])

  const tile = currentTile(state)

  // Dice-roll animation. Host/single compute the roll locally, show the die,
  // then commit. Guests just send the roll and show the die reactively when the
  // host's new state arrives (see the rollSeq effect below).
  const [dice, setDice] = useState<{ value: number; next: GameState | null } | null>(null)
  const onRoll = () => {
    if (role === 'guest') {
      net!.sendAction('rollDice', [])
      return
    }
    const next = ACTIONS.rollDice(state, seat, [])
    sfx('roll')
    setDice({ value: next.dice, next })
  }
  const onDiceDone = () => {
    if (dice?.next) commit(dice.next)
    setDice(null)
  }
  // Guests: show the die when their own roll lands in the broadcast state.
  const lastRollSeq = useRef(state.rollSeq)
  useEffect(() => {
    if (state.rollSeq !== lastRollSeq.current) {
      lastRollSeq.current = state.rollSeq
      if (role === 'guest' && state.currentPlayer === seat && !dice) {
        sfx('roll')
        setDice({ value: state.dice, next: null })
      }
    }
  }, [state.rollSeq]) // eslint-disable-line react-hooks/exhaustive-deps

  const onSuggest = (suspect: string, device: string) => {
    setShowSuggest(false)
    setSuggestedThisTurn(true)
    act('makeSuggestion', suspect, device)
  }
  const onAccuse = (s: string, d: string, l: string) => {
    setShowAccuse(false)
    sfx('accuse')
    act('makeAccusation', s, d, l)
  }
  const onSweepResult = (realContact: boolean) => {
    setShowSweep(false)
    act('ultrasonicSweep', realContact)
  }
  const onChallenge = (success: boolean) => act('resolveChallenge', success)
  const onReveal = (cardId: string) => act('humanReveal', cardId)
  const onNote = (cardId: string) => act('cycleNote', cardId)
  const onEnd = () => act('endTurn')
  const onBuy = () => {
    sfx('buy')
    act('buyProperty')
  }
  const onDecline = () => act('declineBuy')
  const onStoreBuy = () => {
    sfx('buy')
    act('buyStoreIntel', true)
  }
  const onStoreSkip = () => act('buyStoreIntel', false)
  const onBail = () => act('payBail')
  const onServe = () => act('serveJail')
  const onTake = () => act('takeProduct')
  const onRepay = () => act('repayDebt')
  const onSell = () => act('sellProduct')
  const onLeaveDecision = () => act('leaveDecision')
  const onSnitch = (idx: number, level: 1 | 2 | 3) => {
    setShowSnitch(false)
    act('snitch', idx, level)
  }

  // Keyboard shortcuts for the human's turn.
  const canSweepNow = tile.type === 'location' || tile.type === 'sweep'
  const onLocationNow = tile.type === 'location'
  useEffect(() => {
    const anyModal = showSuggest || showAccuse || showSweep || !!dice || jailFx
    const handler = (ev: KeyboardEvent) => {
      const el = ev.target as HTMLElement
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (ev.key === 'Escape') {
        setShowSuggest(false)
        setShowAccuse(false)
        setShowSweep(false)
        return
      }
      if (!myTurn || gameover || anyModal || state.pending?.humanPick) return
      const k = ev.key.toLowerCase()
      if (k === 'r' && state.phase === 'rolling') onRoll()
      else if (state.phase === 'suggesting') {
        if (k === 'g' && onLocationNow && !suggestedThisTurn) setShowSuggest(true)
        else if (k === 's' && canSweepNow && !state.sweptThisTurn) setShowSweep(true)
        else if (k === 'a') setShowAccuse(true)
        else if (k === 'e') onEnd()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  })

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
            onOpenSnitch={() => setShowSnitch(true)}
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

        <DeductionBar state={state} seat={seat} />
        <Feed state={state} />
      </section>

      <aside className="col-right">
        <Notebook state={state} seat={seat} onToggle={onNote} />
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
      {myTurn && state.phase === 'dealer' && (
        <DealerModal state={state} onTake={onTake} onRepay={onRepay} onLeave={onLeaveDecision} />
      )}
      {myTurn && state.phase === 'drophouse' && (
        <DropHouseModal state={state} onSell={onSell} onLeave={onLeaveDecision} />
      )}
      {showSnitch && (
        <SnitchModal
          state={state}
          targets={snitchTargets(state)}
          onSnitch={onSnitch}
          onClose={() => setShowSnitch(false)}
        />
      )}
      {state.pending?.humanPick && <DisproveModal state={state} onReveal={onReveal} />}

      {dice && (
        <Suspense fallback={null}>
          <Dice3D value={dice.value} color={me.color} onDone={onDiceDone} />
        </Suspense>
      )}
      {bustFx && (
        <BustScene
          icon={TOKEN_BY_ID[me.token]?.icon ?? '★'}
          name={me.name}
          reason={bustFx}
          onDone={() => setBustFx(null)}
        />
      )}
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

      {gameover && <GameOver state={state} me={me} seat={seat} onQuit={onQuit} />}
    </div>
  )
}

/* ---------------- Helpers ---------------- */

/** Net worth = cash + purchase price of every property owned. */
function netWorth(state: GameState, p: GameState['players'][0]): number {
  return p.money + p.properties.reduce((sum, pos) => sum + (state.board[pos]?.price ?? 0), 0)
}

/** How many non-solution cards you've ruled out, toward the 18 that exist. */
function DeductionBar({ state, seat }: { state: GameState; seat: number }) {
  const nb = state.notebooks[seat] ?? {}
  const ruledOut = ALL_CARDS.filter((c) => nb[c.id] === '✗').length
  const total = ALL_CARDS.length - 3 // 3 are the solution; the rest are findable
  const pct = Math.min(100, Math.round((ruledOut / total) * 100))
  return (
    <div className="deduction-bar" title="Cards you've ruled out">
      <span className="db-label">Case cracked</span>
      <div className="db-track">
        <div className="db-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="db-count">
        {ruledOut}/{total}
      </span>
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
            <span className="pc-money">{money(netWorth(state, p))}</span>
            {p.properties.length > 0 && <span className="pc-props">🏠{p.properties.length}</span>}
            {p.product > 0 && <span className="pc-crime" title="product">💊{p.product}</span>}
            {p.heat > 0 && <span className="pc-heat" title={`heat ${p.heat}`}>{'🔥'.repeat(Math.min(3, p.heat))}</span>}
            {p.debt > 0 && <span className="pc-debt" title={`owes ${p.debt}, due turn ${p.debtDue}`}>owe {money(p.debt)}</span>}
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
  onOpenSnitch,
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
  onOpenSnitch: () => void
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
          <button
            className="secondary"
            disabled={state.snitchedThisTurn || state.players.filter((p) => !p.out).length < 2}
            onClick={onOpenSnitch}
            title="Rat out a rival for a police bounty"
          >
            🐀 Snitch{state.snitchedThisTurn ? ' ✓' : ''}
          </button>
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

function GameOver({ state, me, seat, onQuit }: { state: GameState; me: GameState['players'][0]; seat: number; onQuit: () => void }) {
  const sol = state.solution!
  const winner = state.players.find((p) => p.id === state.winner)
  const iWon = winner?.id === me.id
  const ruledOut = ALL_CARDS.filter((c) => (state.notebooks[seat] ?? {})[c.id] === '✗').length
  return (
    <div className="overlay">
      {iWon && <Confetti />}
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
        <div className="go-stats">
          <div className="go-stat"><b>{state.turn}</b><span>turns</span></div>
          <div className="go-stat"><b>{money(me.money)}</b><span>your cash</span></div>
          <div className="go-stat"><b>{me.properties.length}</b><span>properties</span></div>
          <div className="go-stat"><b>{ruledOut}/{ALL_CARDS.length - 3}</b><span>cards cleared</span></div>
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
  return (
    <div className="sol-card">
      <span className="sol-label">{label}</span>
      <span className="sol-name">{cardName(id)}</span>
      <span className="sol-hint">{cardAddressOrHint(id)}</span>
    </div>
  )
}

function cardAddressOrHint(id: string): string {
  return cardAddress(id) ?? CARD_BY_ID[id]?.hint ?? ''
}

/** Lightweight CSS confetti burst for a win. */
function Confetti() {
  const colors = ['#4fd1c5', '#f6ad55', '#fc8181', '#b794f4', '#68d391', '#63b3ed']
  const pieces = Array.from({ length: 80 }, (_, i) => i)
  return (
    <div className="confetti">
      {pieces.map((i) => (
        <span
          key={i}
          className="confetti-piece"
          style={{
            left: `${(i * 12.5) % 100}%`,
            background: colors[i % colors.length],
            animationDelay: `${(i % 10) * 0.12}s`,
            animationDuration: `${2.2 + (i % 5) * 0.4}s`,
          }}
        />
      ))}
    </div>
  )
}
