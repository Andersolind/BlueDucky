import { useState } from 'react'
import { PlayerConfig } from '../game/engine'

interface Props {
  onStart: (configs: PlayerConfig[]) => void
  onOpenLab: () => void
}

export default function Lobby({ onStart, onOpenLab }: Props) {
  const [name, setName] = useState('Agent Nova')
  const [bots, setBots] = useState(3)

  const begin = () => {
    const configs: PlayerConfig[] = [{ name: name.trim() || 'You', isBot: false }]
    const botNames = ['CIPHER', 'ECHO', 'RAVEN', 'HALO', 'DELTA']
    for (let i = 0; i < bots; i++) configs.push({ name: botNames[i], isBot: true })
    onStart(configs)
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
          <span>Rival agents (bots): {bots}</span>
          <input
            type="range"
            min={1}
            max={5}
            value={bots}
            onChange={(e) => setBots(Number(e.target.value))}
          />
        </label>

        <div className="lobby-buttons">
          <button className="primary big" onClick={begin}>
            ▶ Open the case
          </button>
          <button className="ghost big" onClick={onOpenLab}>
            ⚡ Try the Signal Lab
          </button>
        </div>
      </div>

      <div className="how">
        <h3>How the hunt works</h3>
        <ol>
          <li>
            <b>Roll & move</b> through the building. You can only investigate the room your agent
            stands in.
          </li>
          <li>
            <b>Suggest</b> a suspect + device in your current room. Rivals must secretly reveal a
            card that disproves you — narrowing the truth.
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
