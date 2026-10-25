import { GameState } from '../game/types'

const ICON: Record<string, string> = {
  move: '➜',
  suggest: '❓',
  disprove: '🃏',
  'no-disprove': '∅',
  accuse: '⚑',
  sweep: '📡',
  system: '•',
  win: '★',
  intel: '🔓',
  money: '💵',
  crime: '🚨',
}

export default function Feed({ state }: { state: GameState }) {
  return (
    <div className="feed">
      <div className="feed-head">Case Feed</div>
      <div className="feed-list">
        {state.log.map((e) => (
          <div className={`feed-row k-${e.kind}`} key={e.id}>
            <span className="feed-icon">{ICON[e.kind] ?? '•'}</span>
            <span className="feed-text">{e.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
