import { Card, GameState } from '../game/types'
import { SUSPECTS, DEVICES, LOCATIONS } from '../game/data'
import { cardAddress, cardName } from '../game/engine'

interface Props {
  state: GameState
  onToggle: (cardId: string) => void
}

const SECTIONS: { title: string; icon: string; cards: Card[] }[] = [
  { title: 'Suspects', icon: '🕵', cards: SUSPECTS },
  { title: 'Devices', icon: '🎧', cards: DEVICES },
  { title: 'Locations', icon: '📍', cards: LOCATIONS },
]

export default function Notebook({ state, onToggle }: Props) {
  const human = state.players.find((p) => !p.isBot)
  const hand = new Set(human?.hand ?? [])

  return (
    <div className="notebook">
      <div className="notebook-head">
        <h3>Detective Notebook</h3>
        <span className="hint">click a marker to cycle · ✗ ruled out · ? maybe · ✓ the one</span>
      </div>
      {SECTIONS.map((sec) => (
        <div className="nb-section" key={sec.title}>
          <div className="nb-section-title">
            <span>{sec.icon}</span> {sec.title}
          </div>
          {sec.cards.map((card) => {
            const mark = state.notebook[card.id] ?? ''
            const mine = hand.has(card.id)
            return (
              <div className={`nb-row ${mine ? 'mine' : ''}`} key={card.id}>
                <div className="nb-card">
                  <span className="nb-card-name">
                    {cardName(card.id)}
                    {card.tier != null && (
                      <span className={`tier-badge tier-${card.tier}`} title={`Tier ${card.tier} hardware`}>
                        {'◆'.repeat(card.tier)}
                      </span>
                    )}
                  </span>
                  <span className="nb-card-hint">
                    {mine ? 'in your hand' : card.band ?? cardAddress(card.id) ?? card.hint}
                  </span>
                </div>
                <button
                  className={`nb-mark m-${markClass(mark)}`}
                  onClick={() => onToggle(card.id)}
                  aria-label={`mark ${card.name}`}
                >
                  {mark || '·'}
                </button>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function markClass(mark: string): string {
  if (mark === '✓') return 'yes'
  if (mark === '✗') return 'no'
  if (mark === '?') return 'maybe'
  return 'empty'
}
