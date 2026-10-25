import { useEffect, useRef, useState } from 'react'
import { GameState } from '../game/types'
import { BOARD_DIM, RING_LEN, ringCoord, TOKEN_BY_ID } from '../game/data'

interface Props {
  state: GameState
}

const TILE_ICON: Record<string, string> = {
  go: '⌂',
  location: '',
  estate: '🏘️',
  station: '🚉',
  store: '🏪',
  busstop: '🚌',
  intel: '❔',
  sweep: '📡',
  jail: '🚧',
  gotojail: '👮',
  corner: '🅿️',
  dealer: '🕴️',
  drophouse: '🏚️',
  police: '🚓',
}

const POI_ICON: Record<string, string> = { street: '🏙️', school: '🏫' }

/** Tile center as a percentage of the board (accounting for the 7×7 grid). */
function centerOf(index: number): { x: number; y: number } {
  const { row, col } = ringCoord(index, BOARD_DIM)
  return { x: ((col + 0.5) / BOARD_DIM) * 100, y: ((row + 0.5) / BOARD_DIM) * 100 }
}

interface TokenView {
  id: string
  x: number
  y: number
  lean: number
  moving: boolean
}

/**
 * A Monopoly-style ring board in 3D (CSS perspective). Tokens glide smoothly
 * around the ring — a "segway" lean into the direction of travel plus a hover
 * bob — instead of teleporting.
 */
export default function Board3D({ state }: Props) {
  const [tilt, setTilt] = useState(true)
  const board = state.board

  // Continuous animated ring position per player (float in [0, 24)).
  const animPos = useRef<Record<string, number>>(
    Object.fromEntries(state.players.map((p) => [p.id, p.pos]))
  )
  const prevXY = useRef<Record<string, { x: number; y: number }>>({})
  const [views, setViews] = useState<TokenView[]>([])
  const lastT = useRef(0)

  useEffect(() => {
    let raf = 0
    const SPEED = 7 // tiles per second
    const step = (t: number) => {
      const dt = lastT.current ? Math.min(0.05, (t - lastT.current) / 1000) : 0
      lastT.current = t
      const out: TokenView[] = []
      for (const p of state.players) {
        if (p.out) continue
        let cur = animPos.current[p.id] ?? p.pos
        const dist = (((p.pos - cur) % RING_LEN) + RING_LEN) % RING_LEN
        let moving = false
        if (dist > 0.001 && dist < RING_LEN - 0.001) {
          const advance = Math.min(SPEED * dt, dist)
          cur = (cur + advance) % RING_LEN
          moving = advance > 0.0001
        } else {
          cur = p.pos
        }
        animPos.current[p.id] = cur

        // Interpolate between the two ring tiles we're between.
        const i = Math.floor(cur) % RING_LEN
        const frac = cur - Math.floor(cur)
        const a = centerOf(i)
        const b = centerOf((i + 1) % RING_LEN)
        const x = a.x + (b.x - a.x) * frac
        const y = a.y + (b.y - a.y) * frac

        const prev = prevXY.current[p.id]
        const lean = prev && moving ? Math.max(-22, Math.min(22, (x - prev.x) * 8)) : 0
        prevXY.current[p.id] = { x, y }
        out.push({ id: p.id, x, y, lean, moving })
      }
      setViews(out)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [state.players])

  const current = state.players[state.currentPlayer]

  return (
    <div className="board3d-wrap">
      <div className="board-place">📍 {state.place}</div>
      <button className="tilt-toggle" onClick={() => setTilt((t) => !t)}>
        {tilt ? '▱ 2D' : '◈ 3D'}
      </button>

      <div className={`board3d-stage ${tilt ? 'tilted' : 'flat'}`}>
        <div
          className="board3d"
          style={{ gridTemplateColumns: `repeat(${BOARD_DIM}, 1fr)`, gridTemplateRows: `repeat(${BOARD_DIM}, 1fr)` }}
        >
          {board.map((tile, i) => {
            const { row, col } = ringCoord(i, BOARD_DIM)
            const isCurrentTile = current && !current.out && current.pos === i
            const ownerColor = tile.owner
              ? state.players.find((p) => p.id === tile.owner)?.color
              : undefined
            const icon = tile.poiKind ? POI_ICON[tile.poiKind] ?? TILE_ICON[tile.type] : TILE_ICON[tile.type]
            return (
              <div
                key={i}
                className={`tile t-${tile.type} ${isCurrentTile ? 'here' : ''}`}
                style={{
                  gridRow: row + 1,
                  gridColumn: col + 1,
                  ...(ownerColor ? { boxShadow: `inset 0 0 0 2px ${ownerColor}` } : {}),
                }}
              >
                <div className="tile-face">
                  <div className="tile-top">
                    <span className="tile-idx">{i}</span>
                    {icon && <span className="tile-ic">{icon}</span>}
                  </div>
                  <div className="tile-label">{tile.label}</div>
                  {tile.price != null ? (
                    <div className="tile-sub">${tile.price}</div>
                  ) : (
                    tile.sub && <div className="tile-sub">{tile.sub}</div>
                  )}
                  {ownerColor && <span className="tile-owner" style={{ background: ownerColor }} />}
                </div>
              </div>
            )
          })}

          {/* Gliding token layer sits above the tiles on the tilted plane. */}
          <div className="token-layer">
            {views.map((v) => {
              const p = state.players.find((pl) => pl.id === v.id)!
              return (
                <span
                  key={v.id}
                  className={`glider ${v.moving ? 'moving' : ''} ${p.id === current?.id ? 'active' : ''}`}
                  style={{
                    left: `${v.x}%`,
                    top: `${v.y}%`,
                    background: p.color,
                    transform: `translate(-50%, -60%) translateZ(22px) rotateX(-55deg) rotate(${v.lean}deg)`,
                  }}
                  title={`${p.name} · ${TOKEN_BY_ID[p.token]?.name ?? ''}`}
                >
                  {TOKEN_BY_ID[p.token]?.icon ?? '★'}
                  <span className="glider-shadow" />
                </span>
              )
            })}
          </div>

          {/* Center dossier. */}
          <div
            className="board-center"
            style={{ gridRow: `2 / ${BOARD_DIM}`, gridColumn: `2 / ${BOARD_DIM}` }}
          >
            <div className="center-mark">◊</div>
            <div className="center-title">CASE FILE</div>
            <div className="center-sub">Who is the eavesdropper?</div>
            {state.pot > 0 && (
              <div className="center-pot">🅿️ Safehouse pot ${state.pot.toLocaleString('en-US')}</div>
            )}
            <div className="center-legend">
              <span><i className="lg loc" /> property</span>
              <span><i className="lg intel" /> challenge</span>
              <span><i className="lg sweep" /> sweep</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
