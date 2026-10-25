import { useEffect, useRef, useState } from 'react'
import { GameState } from './game/types'
import { botStep, createGame, beginGame, PlayerConfig } from './game/engine'
import { MIMICO_POI } from './game/data'
import { getLocalPoi } from './game/geo'
import { setMuted } from './game/sfx'
import { useUltrasonic } from './audio/useUltrasonic'
import { HostSession, GuestSession } from './net/session'
import { createHost, createGuest } from './net/webrtc'
import { NetHandle } from './net/types'
import Lobby from './components/Lobby'
import GameScreen from './components/GameScreen'
import SignalLab from './components/SignalLab'
import TokenDraw from './components/TokenDraw'

type Screen = 'lobby' | 'locating' | 'assign' | 'game' | 'host-lobby' | 'join'
type NetRole = 'off' | 'host' | 'guest'

export default function App() {
  const [screen, setScreen] = useState<Screen>('lobby')
  const [state, setState] = useState<GameState | null>(null)
  const [showLab, setShowLab] = useState(false)
  const [geoNote, setGeoNote] = useState('')
  const [mute, setMute] = useState(false)

  // --- Networking state ---
  const [netRole, setNetRole] = useState<NetRole>('off')
  const netRoleRef = useRef<NetRole>('off')
  const [room, setRoom] = useState('')
  const [guests, setGuests] = useState<string[]>([])
  const [guestSeat, setGuestSeat] = useState(1)
  const [netError, setNetError] = useState('')
  const [myName, setMyName] = useState('You')
  const hostSessionRef = useRef<HostSession | null>(null)
  const guestSessionRef = useRef<GuestSession | null>(null)
  const hostConnRef = useRef<ReturnType<typeof createHost> | null>(null)
  const guestConnRef = useRef<ReturnType<typeof createGuest> | null>(null)
  const hostPrefs = useRef<{ clearance: number; bots: number; useGeo: boolean }>({ clearance: 2, bots: 2, useGeo: false })

  const toggleMute = () => setMute((m) => (setMuted(!m), !m))

  const ultra = useUltrasonic()

  // Commit an authoritative state: update React, and if hosting, broadcast it.
  const commitState = (ns: GameState | null) => {
    setState(ns)
    if (ns && netRoleRef.current === 'host') hostSessionRef.current?.setState(ns)
  }

  /* ---------------- Local play ---------------- */
  const start = async (configs: PlayerConfig[], clearance: number, useGeo: boolean) => {
    const poi = await resolvePoi(useGeo)
    setState(beginGame(createGame(configs, clearance, poi)))
    setScreen('assign')
  }

  async function resolvePoi(useGeo: boolean) {
    if (!useGeo) return MIMICO_POI
    setScreen('locating')
    setGeoNote('Locating you…')
    try {
      const poi = await getLocalPoi()
      setGeoNote(`Board set to ${poi.place}.`)
      return poi
    } catch {
      setGeoNote('Could not use your location — playing Mimico.')
      return MIMICO_POI
    }
  }

  /* ---------------- Host online ---------------- */
  const hostOnline = (name: string, clearance: number, bots: number, useGeo: boolean) => {
    setMyName(name)
    hostPrefs.current = { clearance, bots, useGeo }
    netRoleRef.current = 'host'
    setNetRole('host')
    setGuests([])
    setNetError('')

    const hs = new HostSession()
    hostSessionRef.current = hs
    hs.onState = (s) => setState(s) // a guest's action was applied → refresh host UI

    const conn = createHost()
    hostConnRef.current = conn
    conn.onCode((c) => setRoom(c))
    conn.onError((e) => setNetError(e))
    conn.onGuest((t, gname) => {
      hs.addGuest(t)
      setGuests((g) => [...g, gname])
    })
    setScreen('host-lobby')
  }

  const startHostGame = async () => {
    const { clearance, bots, useGeo } = hostPrefs.current
    const poi = await resolvePoi(useGeo)
    const configs: PlayerConfig[] = [
      { name: myName || 'Host', isBot: false },
      ...guests.map((n) => ({ name: n, isBot: false })),
      ...Array.from({ length: bots }, (_, i) => ({ name: ['CIPHER', 'ECHO', 'RAVEN', 'HALO', 'DELTA'][i] ?? `BOT${i}`, isBot: true })),
    ]
    const g = beginGame(createGame(configs, clearance, poi))
    hostSessionRef.current?.setState(g) // broadcast initial snapshot to guests
    setState(g)
    setScreen('game')
  }

  /* ---------------- Join online ---------------- */
  const joinOnline = (code: string, name: string) => {
    setMyName(name)
    netRoleRef.current = 'guest'
    setNetRole('guest')
    setNetError('')
    const conn = createGuest(code.toUpperCase(), name)
    guestConnRef.current = conn
    conn.onError((e) => setNetError(e))
    conn.onHost((t) => {
      const gs = new GuestSession(t)
      guestSessionRef.current = gs
      gs.onSeat = (seat) => setGuestSeat(seat)
      gs.onState = (s) => {
        setState(s)
        setScreen('game')
      }
    })
    setScreen('join')
  }

  const quit = () => {
    hostConnRef.current?.close()
    guestConnRef.current?.close()
    hostSessionRef.current = null
    guestSessionRef.current = null
    netRoleRef.current = 'off'
    setNetRole('off')
    setRoom('')
    setGuests([])
    setNetError('')
    setState(null)
    setScreen('lobby')
  }

  // --- Bot turn driver (host + single only; guests never run bots) ---
  const timer = useRef<number | null>(null)
  useEffect(() => {
    if (!state || netRole === 'guest') return
    const current = state.players[state.currentPlayer]
    const humanBlocking = !!state.pending?.humanPick
    const botActive = current?.isBot && state.phase !== 'gameover' && !humanBlocking
    if (botActive) {
      timer.current = window.setTimeout(() => commitState(botStep(state)), 750)
      return () => {
        if (timer.current) window.clearTimeout(timer.current)
      }
    }
  }, [state, netRole])

  const net: NetHandle | null =
    netRole === 'host'
      ? { role: 'host', seat: 0, commit: commitState, sendAction: () => {} }
      : netRole === 'guest'
      ? { role: 'guest', seat: guestSeat, commit: () => {}, sendAction: (a, args) => guestSessionRef.current?.sendAction(a, args) }
      : null

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={quit} title="SnitchesAreAmongUs">
          <span className="brand-mark">🐀</span>
          <span className="brand-name">SNITCHES<b>AREAMONGUS</b></span>
          <span className="brand-sub">rat out the eavesdropper</span>
        </div>
        <div className="topbar-actions">
          {netRole !== 'off' && <div className="net-pill">🌐 {netRole === 'host' ? `hosting ${room}` : 'online'}</div>}
          <div className={`mic-pill ${ultra.state.listening ? 'on' : ''}`}>
            <span className="dot" /> {ultra.state.listening ? 'MIC LIVE' : 'mic idle'}
          </div>
          <button className="ghost" onClick={toggleMute} title={mute ? 'Unmute' : 'Mute'}>
            {mute ? '🔇' : '🔊'}
          </button>
          <button className="ghost" onClick={() => setShowLab(true)}>
            ⚡ Signal Lab
          </button>
          {screen !== 'lobby' && (
            <button className="ghost" onClick={quit}>
              ✕ Quit
            </button>
          )}
        </div>
      </header>

      <main className="main">
        {screen === 'lobby' && (
          <Lobby onStart={start} onOpenLab={() => setShowLab(true)} onHostOnline={hostOnline} onJoinOnline={joinOnline} />
        )}
        {screen === 'locating' && (
          <div className="locating">
            <div className="locating-radar" />
            <h2>{geoNote}</h2>
            <p className="lede">Scanning OpenStreetMap for nearby streets, schools, stations and stores…</p>
          </div>
        )}
        {screen === 'host-lobby' && (
          <div className="netlobby">
            <div className="ch-tag" style={{ borderColor: 'var(--teal-dim)', color: 'var(--teal)' }}>ONLINE · HOST</div>
            <h1>Room code</h1>
            <div className="room-code">{room || '····'}</div>
            <p className="lede">Share this code. Friends open the app, hit <b>Join online</b>, and enter it.</p>
            <div className="net-roster">
              <div className="nr-row you">★ {myName || 'You'} <span>host</span></div>
              {guests.map((g, i) => (
                <div className="nr-row" key={i}>🌐 {g} <span>seat {i + 1}</span></div>
              ))}
              {guests.length === 0 && <div className="nr-empty">waiting for players…</div>}
            </div>
            {netError && <div className="error">{netError}</div>}
            <button className="primary big" onClick={startHostGame} disabled={!room}>
              ▶ Start game ({guests.length + 1} human{guests.length ? 's' : ''} + {hostPrefs.current.bots} bots)
            </button>
          </div>
        )}
        {screen === 'join' && (
          <div className="netlobby">
            <div className="locating-radar" />
            <h2>{netError ? 'Connection problem' : 'Connecting to the host…'}</h2>
            {netError ? <div className="error">{netError}</div> : <p className="lede">Waiting for the host to start the game.</p>}
          </div>
        )}
        {screen === 'assign' && state && <TokenDraw players={state.players} onDone={() => setScreen('game')} />}
        {screen === 'game' && state && (
          <GameScreen state={state} setState={setState} ultra={ultra} onQuit={quit} net={net} />
        )}
      </main>

      {showLab && <SignalLab ultra={ultra} onClose={() => setShowLab(false)} />}

      <footer className="footer">
        <span>
          SnitchesAreAmongUs · deduction + underworld economy · WebRTC online play · real ultrasonic modem.
        </span>
      </footer>
    </div>
  )
}
