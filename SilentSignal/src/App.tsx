import { useEffect, useRef, useState } from 'react'
import { GameState } from './game/types'
import { botStep, createGame, beginGame, PlayerConfig } from './game/engine'
import { useUltrasonic } from './audio/useUltrasonic'
import Lobby from './components/Lobby'
import GameScreen from './components/GameScreen'
import SignalLab from './components/SignalLab'

type Screen = 'lobby' | 'game'

export default function App() {
  const [screen, setScreen] = useState<Screen>('lobby')
  const [state, setState] = useState<GameState | null>(null)
  const [showLab, setShowLab] = useState(false)

  // One shared ultrasonic engine for the whole app (Signal Lab + in-game sweep).
  const ultra = useUltrasonic()

  const start = (configs: PlayerConfig[]) => {
    setState(beginGame(createGame(configs)))
    setScreen('game')
  }

  const quit = () => {
    setState(null)
    setScreen('lobby')
  }

  // --- Bot turn driver -------------------------------------------------
  // While it's a bot's turn (and no human decision is pending), advance the
  // bot one micro-step every beat so the action animates.
  const timer = useRef<number | null>(null)
  useEffect(() => {
    if (!state) return
    // A bot turn spans several micro-steps that transiently flip `phase` to
    // 'moving'/'suggesting'/'disproving', so gate on whose turn it is — not on
    // the phase. Pause only when a human must reveal a card.
    const current = state.players[state.currentPlayer]
    const humanBlocking = !!state.pending?.humanPick
    const botActive = current?.isBot && state.phase !== 'gameover' && !humanBlocking
    if (botActive) {
      timer.current = window.setTimeout(() => {
        setState((s) => (s ? botStep(s) : s))
      }, 750)
      return () => {
        if (timer.current) window.clearTimeout(timer.current)
      }
    }
  }, [state])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={quit} title="SilentSignal">
          <span className="brand-mark">◊</span>
          <span className="brand-name">SILENT<b>SIGNAL</b></span>
          <span className="brand-sub">hunt the eavesdropper</span>
        </div>
        <div className="topbar-actions">
          <div className={`mic-pill ${ultra.state.listening ? 'on' : ''}`}>
            <span className="dot" /> {ultra.state.listening ? 'MIC LIVE' : 'mic idle'}
          </div>
          <button className="ghost" onClick={() => setShowLab(true)}>
            ⚡ Signal Lab
          </button>
          {screen === 'game' && (
            <button className="ghost" onClick={quit}>
              ✕ Quit case
            </button>
          )}
        </div>
      </header>

      <main className="main">
        {screen === 'lobby' && <Lobby onStart={start} onOpenLab={() => setShowLab(true)} />}
        {screen === 'game' && state && (
          <GameScreen state={state} setState={setState} ultra={ultra} onQuit={quit} />
        )}
      </main>

      {showLab && <SignalLab ultra={ultra} onClose={() => setShowLab(false)} />}

      <footer className="footer">
        <span>
          Ultrasonic modem: multi-tone FSK · Goertzel decode · 18–21 kHz · runs entirely in your browser.
        </span>
      </footer>
    </div>
  )
}
