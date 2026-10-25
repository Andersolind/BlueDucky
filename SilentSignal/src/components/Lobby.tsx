import { useState } from 'react'
import { PlayerConfig } from '../game/engine'

interface Props {
  onStart: (configs: PlayerConfig[], clearance: number, useGeo: boolean) => void
  onOpenLab: () => void
  onHostOnline: (name: string, clearance: number, bots: number, useGeo: boolean) => void
  onJoinOnline: (code: string, name: string) => void
}

const CLEARANCES = [
  { level: 1, name: 'Rookie', desc: 'Gentle challenges. Short ciphers, simple patterns.' },
  { level: 2, name: 'Field Agent', desc: 'Tougher — geometric patterns, longer ciphers.' },
  { level: 3, name: 'Black-Ops', desc: 'Brutal — hidden shifts, square sequences.' },
]

export default function Lobby({ onStart, onOpenLab, onHostOnline, onJoinOnline }: Props) {
  const [name, setName] = useState('Agent Nova')
  const [bots, setBots] = useState(3)
  const [clearance, setClearance] = useState(2)
  const [useGeo, setUseGeo] = useState(false)
  const [joinCode, setJoinCode] = useState('')

  const begin = () => {
    const configs: PlayerConfig[] = [{ name: name.trim() || 'You', isBot: false }]
    const botNames = ['CIPHER', 'ECHO', 'RAVEN', 'HALO', 'DELTA']
    for (let i = 0; i < bots; i++) configs.push({ name: botNames[i], isBot: true })
    onStart(configs, clearance, useGeo)
  }

  return (
    <div className="lobby">
      <div className="lobby-hero">
        <h1>
          Someone is <span className="glitch">listening.</span>
        </h1>
        <p className="lede">
          A hidden operative has planted a bug and is quietly exfiltrating audio. Deduce{' '}
          <b>who</b>, with <b>which device</b>, in <b>which location</b> — before your rivals do.
          Your edge: an <b>ultrasonic sweep</b> that can hear active bugs the way the tool in this
          repo hears data over sound.
        </p>
      </div>

      <div className="lobby-card">
        <label className="field">
          <span>Your codename</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={20} />
        </label>

        <label className="field">
          <span>Rival AI agents: {bots}</span>
          <input
            type="range"
            min={1}
            max={5}
            value={bots}
            onChange={(e) => setBots(Number(e.target.value))}
          />
        </label>

        <div className="field">
          <span>Clearance level — sets challenge difficulty</span>
          <div className="clearance-row">
            {CLEARANCES.map((c) => (
              <button
                key={c.level}
                className={`clearance-opt ${clearance === c.level ? 'sel' : ''}`}
                onClick={() => setClearance(c.level)}
                title={c.desc}
              >
                <span className="cl-pips">{'◆'.repeat(c.level)}{'◇'.repeat(3 - c.level)}</span>
                <span className="cl-name">{c.name}</span>
                <span className="cl-desc">{c.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <button
          className={`geo-toggle ${useGeo ? 'on' : ''}`}
          onClick={() => setUseGeo((v) => !v)}
        >
          <span className="geo-check">{useGeo ? '◉' : '○'}</span>
          <span className="geo-text">
            <b>Use my location</b>
            <span>Build the board from real streets & schools near you (asks for location; falls back to Mimico).</span>
          </span>
          <span className="geo-pin">📍</span>
        </button>

        <div className="lobby-buttons">
          <button className="primary big" onClick={begin}>
            ▶ Play vs AI
          </button>
          <button className="ghost big" onClick={onOpenLab}>
            ⚡ Try the Signal Lab
          </button>
        </div>

        <div className="online-row">
          <button
            className="secondary"
            onClick={() => onHostOnline(name.trim() || 'Host', clearance, bots, useGeo)}
          >
            🌐 Host online game
          </button>
          <div className="join-inline">
            <input
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase().slice(0, 4))}
              placeholder="ROOM"
              maxLength={4}
            />
            <button
              className="secondary"
              disabled={joinCode.length < 4}
              onClick={() => onJoinOnline(joinCode, name.trim() || 'Agent')}
            >
              Join
            </button>
          </div>
        </div>
        <p className="tiny">
          Online play needs the signaling server running (<code>npm run signal</code>) and the HTTPS app
          (<code>npm run dev:https</code>). Same Wi-Fi works out of the box.
        </p>
      </div>

      <div className="how">
        <h3>How the hunt works</h3>
        <ol>
          <li>
            <b>Roll & hop</b> the Monopoly-style ring around Mimico's streets and schools. You can
            only investigate the location you land on.
          </li>
          <li>
            <b>Suggest</b> a suspect + device at your current address. Rivals must secretly reveal a
            card that disproves you. Land on a <b>Dead Drop / Cipher Cache</b> tile and crack a clue
            challenge for free intel.
          </li>
          <li>
            <b>Sweep</b> for ultrasound. If the true bug is an active emitter and it's planted in
            your room, your mic will hear it. Co-located players can even transmit a real beacon
            from the Signal Lab.
          </li>
          <li>
            <b>Accuse</b> once you're sure. Right = case closed, you win. Wrong = you're burned and
            out.
          </li>
        </ol>
      </div>
    </div>
  )
}
