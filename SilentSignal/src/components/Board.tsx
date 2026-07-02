import { GameState } from '../game/types'
import { CARD_BY_ID, ROOM_GRID } from '../game/data'

interface Props {
  state: GameState
  onMove: (roomId: string) => void
}

export default function Board({ state, onMove }: Props) {
  const isMoving = state.phase === 'moving'
  const current = state.players[state.currentPlayer]

  return (
    <div className="board">
      <div className="board-grid">
        {ROOM_GRID.flat().map((roomId) => {
          const room = CARD_BY_ID[roomId]
          const occupants = state.players.filter((p) => p.room === roomId && !p.out)
          const reachable = isMoving && state.reachable.includes(roomId)
          const isCurrentRoom = current.room === roomId
          return (
            <button
              key={roomId}
              className={`room ${reachable ? 'reachable' : ''} ${isCurrentRoom ? 'current' : ''} ${
                isMoving && !reachable ? 'dim' : ''
              }`}
              disabled={!reachable}
              onClick={() => reachable && onMove(roomId)}
            >
              <div className="room-name">{room.name}</div>
              <div className="room-hint">{room.hint}</div>
              <div className="room-tokens">
                {occupants.map((p) => (
                  <span
                    key={p.id}
                    className="token"
                    style={{ background: p.color }}
                    title={p.name}
                  >
                    {p.isBot ? '🤖' : '★'}
                  </span>
                ))}
              </div>
              {reachable && <span className="reach-tag">move here</span>}
            </button>
          )
        })}
      </div>
      {isMoving && (
        <div className="board-help">
          You rolled <b>{state.dice}</b> — pick a highlighted room to investigate.
        </div>
      )}
    </div>
  )
}
