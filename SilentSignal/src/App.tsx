import { useEffect, useRef, useState } from 'react'
import { GameState } from './game/types'
import { botStep, createGame, beginGame, PlayerConfig } from './game/engine'
import { MIMICO_POI } from './game/data'
import { getLocalPoi } from './game/geo'
import { useUltrasonic } from './audio/useUltrasonic'
import Lobby from './components/Lobby'
import GameScreen from './components/GameScreen'
import SignalLab from './components/SignalLab'
import TokenDraw from './components/TokenDraw'

type Screen = 'lobby' | 'locating' | 'assign' | 'game'

export default function App() {
  const [screen, setScreen] = useState<Screen>('lobby')
  const [state, setState] = useState<GameState | null>(null)
  const [showLab, setShowLab] = useState(false)
  const [geoNote, setGeoNote] = useState('')

  // One shared ultrasonic engine for the whole app (Signal Lab + in-game sweep).
  const ultra = useUltrasonic()

  const start = async (configs: PlayerConfig[], clearance: number, useGeo: boolean) => {
    let poi = MIMICO_POI
    if (useGeo) {
      setScreen('locating')
      setGeoNote('Locating you…')
      try {
        poi = await getLocalPoi()
        setGeoNote(`Board set to ${poi.place}.`)
      } catch (e: any) {
        poi = MIMICO_POI
        setGeoNote('Could not use your location — playing Mimico.')
      }
    }
    // Tokens are dealt in createGame; show the reveal animation before play.
    setState(beginGame(createGame(configs, clearance, poi)))
    setScreen('assign')
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
        {screen === 'locating' && (
          <div className="locating">
            <div className="locating-radar" />
            <h2>{geoNote}</h2>
            <p className="lede">Scanning OpenStreetMap for nearby streets, schools, stations and stores…</p>
          </div>
        )}
        {screen === 'assign' && state && (
          <TokenDraw players={state.players} onDone={() => setScreen('game')} />
        )}
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
