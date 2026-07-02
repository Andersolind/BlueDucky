import { Card } from './types'

/**
 * The case file. Three categories, Clue-style:
 *   SUSPECTS  — who is the hidden eavesdropper
 *   DEVICES   — which bug they used ("weapon")
 *   LOCATIONS — where the bug was planted ("room")
 */

export const SUSPECTS: Card[] = [
  { id: 'sus_vesper', name: 'Vesper Kane', category: 'suspect', hint: 'Ex-signals officer. Reads lips.' },
  { id: 'sus_finch', name: 'Dr. Aldous Finch', category: 'suspect', hint: 'Acoustics researcher, disgraced.' },
  { id: 'sus_mir', name: 'Mireille Devereaux', category: 'suspect', hint: 'Corporate fixer. Never on record.' },
  { id: 'sus_hollis', name: 'Sgt. Bo Hollis', category: 'suspect', hint: 'Building security. Keys to everything.' },
  { id: 'sus_volkov', name: 'Nadia Volkov', category: 'suspect', hint: 'Freelance interceptor.' },
  { id: 'sus_marsh', name: 'Prof. Ivo Marsh', category: 'suspect', hint: 'Tenured. Suspiciously well-funded.' },
]

export const DEVICES: Card[] = [
  { id: 'dev_ultra', name: 'Ultrasonic Implant', category: 'device', hint: 'Beams audio out above 18 kHz.', emits: true },
  { id: 'dev_laser', name: 'Laser Microphone', category: 'device', hint: 'Reads glass vibration from afar.', emits: false },
  { id: 'dev_gsm', name: 'GSM Bug', category: 'device', hint: 'Phones home over the cell network.', emits: true },
  { id: 'dev_contact', name: 'Contact Mic', category: 'device', hint: 'Glued to a wall or pipe. Passive.', emits: false },
  { id: 'dev_retro', name: 'RF Retroreflector', category: 'device', hint: 'Lights up under a radar flood.', emits: true },
  { id: 'dev_parabolic', name: 'Parabolic Dish', category: 'device', hint: 'Aimed from across the room.', emits: false },
]

export const LOCATIONS: Card[] = [
  { id: 'loc_vault', name: 'Server Vault', category: 'location', hint: 'Cold aisle, colder secrets.' },
  { id: 'loc_exec', name: 'Executive Suite', category: 'location', hint: 'Corner office, thin walls.' },
  { id: 'loc_boiler', name: 'Boiler Room', category: 'location', hint: 'Nobody looks twice down here.' },
  { id: 'loc_roof', name: 'Rooftop Garden', category: 'location', hint: 'Line of sight to three buildings.' },
  { id: 'loc_archive', name: 'Records Archive', category: 'location', hint: 'Paper trails and dead zones.' },
  { id: 'loc_comms', name: 'Comms Closet', category: 'location', hint: 'Where every wire meets.' },
  { id: 'loc_parking', name: 'Parking Level', category: 'location', hint: 'Echoes, exhaust, and blind spots.' },
  { id: 'loc_atrium', name: 'The Atrium', category: 'location', hint: 'Open, bright, and always watched.' },
  { id: 'loc_loft', name: 'Safehouse Loft', category: 'location', hint: 'Off-books. Should be empty.' },
]

export const ALL_CARDS: Card[] = [...SUSPECTS, ...DEVICES, ...LOCATIONS]

export const CARD_BY_ID: Record<string, Card> = Object.fromEntries(ALL_CARDS.map((c) => [c.id, c]))

export const PLAYER_COLORS = ['#4fd1c5', '#f6ad55', '#fc8181', '#b794f4', '#68d391', '#63b3ed']

/**
 * Board layout: rooms arranged on a 3×3 grid of location cards. Adjacency is
 * grid-neighbor plus a couple of "corridor" shortcuts. Movement cost between
 * adjacent rooms is 1; the die roll caps how far you can travel per turn.
 */
export const ROOM_GRID: string[][] = [
  ['loc_vault', 'loc_exec', 'loc_boiler'],
  ['loc_roof', 'loc_archive', 'loc_comms'],
  ['loc_parking', 'loc_atrium', 'loc_loft'],
]

/* ------------------------------------------------------------------ *
 *  Monopoly-style ring board
 * ------------------------------------------------------------------ */

export type TileType = 'go' | 'location' | 'intel' | 'sweep' | 'corner'

export interface Tile {
  type: TileType
  label: string
  /** For location tiles: which room this tile represents. */
  locationId?: string
  /** Short flavor / sublabel. */
  sub?: string
}

/**
 * 24 tiles laid clockwise around a 7×7 perimeter. Four corners, all nine
 * location "rooms" on the edges, plus INTEL tiles (draw a clue challenge) and
 * SWEEP tiles (run an ultrasonic sweep). You roll a die and hop this many tiles
 * clockwise, then the tile you land on decides what happens.
 */
export const RING: Tile[] = [
  { type: 'go', label: 'Field HQ', sub: 'pass for intel' }, // 0  (top-left corner)
  { type: 'location', label: 'Server Vault', locationId: 'loc_vault' }, // 1
  { type: 'intel', label: 'Dead Drop', sub: 'clue challenge' }, // 2
  { type: 'location', label: 'Executive Suite', locationId: 'loc_exec' }, // 3
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 4
  { type: 'location', label: 'Boiler Room', locationId: 'loc_boiler' }, // 5
  { type: 'corner', label: 'Interception', sub: 'clue challenge' }, // 6  (top-right)
  { type: 'location', label: 'Rooftop Garden', locationId: 'loc_roof' }, // 7
  { type: 'intel', label: 'Cipher Cache', sub: 'clue challenge' }, // 8
  { type: 'location', label: 'Records Archive', locationId: 'loc_archive' }, // 9
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 10
  { type: 'location', label: 'Comms Closet', locationId: 'loc_comms' }, // 11
  { type: 'corner', label: 'Safehouse', sub: 'lie low' }, // 12 (bottom-right)
  { type: 'location', label: 'Parking Level', locationId: 'loc_parking' }, // 13
  { type: 'intel', label: 'Dead Drop', sub: 'clue challenge' }, // 14
  { type: 'location', label: 'The Atrium', locationId: 'loc_atrium' }, // 15
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 16
  { type: 'location', label: 'Safehouse Loft', locationId: 'loc_loft' }, // 17
  { type: 'corner', label: 'Lockdown', sub: 'clue challenge' }, // 18 (bottom-left)
  { type: 'intel', label: 'Wiretap', sub: 'clue challenge' }, // 19
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 20
  { type: 'intel', label: 'Cipher Cache', sub: 'clue challenge' }, // 21
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 22
  { type: 'intel', label: 'Wiretap', sub: 'clue challenge' }, // 23
]

/** Tiles that draw a clue challenge when landed on. */
export const CHALLENGE_TILES = new Set<TileType>(['intel', 'corner'])

export const BOARD_DIM = 7 // 7×7 grid; perimeter = 4*(7-1) = 24 tiles

/** Grid (row, col) for ring index, clockwise from the top-left corner. */
export function ringCoord(index: number, dim = BOARD_DIM): { row: number; col: number } {
  const n = index % (4 * (dim - 1))
  if (n < dim) return { row: 0, col: n } // top row L→R
  if (n < 2 * dim - 1) return { row: n - (dim - 1), col: dim - 1 } // right col T→B
  if (n < 3 * dim - 2) return { row: dim - 1, col: dim - 1 - (n - (2 * dim - 2)) } // bottom R→L
  return { row: dim - 1 - (n - (3 * dim - 3)), col: 0 } // left col B→T
}

export const ROOM_ADJACENCY: Record<string, string[]> = buildAdjacency()

function buildAdjacency(): Record<string, string[]> {
  const adj: Record<string, string[]> = {}
  const rows = ROOM_GRID.length
  const cols = ROOM_GRID[0].length
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const id = ROOM_GRID[r][c]
      const n: string[] = []
      if (r > 0) n.push(ROOM_GRID[r - 1][c])
      if (r < rows - 1) n.push(ROOM_GRID[r + 1][c])
      if (c > 0) n.push(ROOM_GRID[r][c - 1])
      if (c < cols - 1) n.push(ROOM_GRID[r][c + 1])
      adj[id] = n
    }
  }
  // Diagonal "service corridors" from the center room — classic Clue secret passages.
  adj['loc_archive'].push('loc_vault', 'loc_boiler', 'loc_parking', 'loc_loft')
  adj['loc_vault'].push('loc_archive')
  adj['loc_boiler'].push('loc_archive')
  adj['loc_parking'].push('loc_archive')
  adj['loc_loft'].push('loc_archive')
  return adj
}
