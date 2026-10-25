import { Card, TokenDef } from './types'

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

/**
 * DEVICES double as the "acoustic hardware" sub-layer: each carries a
 * complexity `tier` (1 basic … 3 black-ops) and the `band` / technique it works
 * on. Higher-tier hardware is rarer and harder to reason about.
 */
export const DEVICES: Card[] = [
  { id: 'dev_ultra', name: 'Ultrasonic Implant', category: 'device', hint: 'Beams audio out above 18 kHz.', emits: true, tier: 3, band: '18–22 kHz ultrasonic carrier' },
  { id: 'dev_laser', name: 'Laser Microphone', category: 'device', hint: 'Reads glass vibration from afar.', emits: false, tier: 3, band: 'IR laser vibrometry' },
  { id: 'dev_gsm', name: 'GSM Bug', category: 'device', hint: 'Phones home over the cell network.', emits: true, tier: 2, band: '900 / 1800 MHz GSM uplink' },
  { id: 'dev_contact', name: 'Contact Mic', category: 'device', hint: 'Glued to a wall or pipe. Passive.', emits: false, tier: 1, band: 'structure-borne, wired' },
  { id: 'dev_retro', name: 'RF Retroreflector', category: 'device', hint: 'Lights up under a radar flood.', emits: true, tier: 3, band: 'passive RF, radar-lit' },
  { id: 'dev_parabolic', name: 'Parabolic Dish', category: 'device', hint: 'Aimed from across the street.', emits: false, tier: 1, band: 'line-of-sight acoustic' },
]

/**
 * LOCATIONS are the nine "where was the bug planted" cards — real Mimico
 * (Etobicoke, Toronto) streets and schools by default. Their ids (loc_1..loc_9)
 * are STABLE; the display names can be overridden per-game by geolocation (see
 * buildBoard / setLocationNames), so the deduction logic never depends on the
 * label. Six streets + three schools, matching the board's location slots.
 */
export const LOCATIONS: Card[] = [
  { id: 'loc_1', name: 'Royal York Road', category: 'location', hint: "Mimico's arterial spine.", address: 'Royal York Rd @ Mimico Ave' },
  { id: 'loc_2', name: 'Bishop Allen Academy', category: 'location', hint: 'Catholic high school.', address: '721 Royal York Rd' },
  { id: 'loc_3', name: 'Lake Shore Blvd W', category: 'location', hint: 'Waterfront strip, lake wind.', address: 'Lake Shore Blvd W' },
  { id: 'loc_4', name: 'David Hornell School', category: 'location', hint: 'Junior school by the Queensway.', address: '640 The Queensway' },
  { id: 'loc_5', name: 'Mimico Avenue', category: 'location', hint: 'Old main street, tight sightlines.', address: 'Mimico Ave' },
  { id: 'loc_6', name: 'Station Road', category: 'location', hint: 'By the Mimico GO tracks.', address: 'Station Rd @ Judson St' },
  { id: 'loc_7', name: 'John English School', category: 'location', hint: 'Junior middle school.', address: '95 Ourland Ave' },
  { id: 'loc_8', name: 'Superior Avenue', category: 'location', hint: 'Quiet residential run.', address: 'Superior Ave' },
  { id: 'loc_9', name: 'Melrose Street', category: 'location', hint: 'Leafy side street.', address: 'Melrose St' },
]

/**
 * Monopoly-style playing tokens — a car, a person, or an item. Each agent is
 * dealt a unique one at the start with a slot-machine reveal.
 */
export const TOKENS: TokenDef[] = [
  // cars / vehicles
  { id: 'tok_roadster', icon: '🚗', name: 'The Roadster', kind: 'car' },
  { id: 'tok_getaway', icon: '🏎️', name: 'Getaway Car', kind: 'car' },
  { id: 'tok_speedboat', icon: '🛥️', name: 'The Speedboat', kind: 'car' },
  { id: 'tok_bus', icon: '🚌', name: 'The Night Bus', kind: 'car' },
  { id: 'tok_taxi', icon: '🚕', name: 'The Cab', kind: 'car' },
  { id: 'tok_scooter', icon: '🛵', name: 'The Scooter', kind: 'car' },
  { id: 'tok_chopper', icon: '🚁', name: 'The Chopper', kind: 'car' },
  // people
  { id: 'tok_operative', icon: '🕵️', name: 'The Operative', kind: 'person' },
  { id: 'tok_fixer', icon: '🎩', name: 'The Fixer', kind: 'person' },
  { id: 'tok_tail', icon: '🚶', name: 'The Tail', kind: 'person' },
  { id: 'tok_k9', icon: '🐕', name: 'The K-9', kind: 'person' },
  // gadgets / items
  { id: 'tok_scanner', icon: '📻', name: 'The Scanner', kind: 'item' },
  { id: 'tok_headset', icon: '🎧', name: 'The Headset', kind: 'item' },
  { id: 'tok_torch', icon: '🔦', name: 'The Torch', kind: 'item' },
  { id: 'tok_key', icon: '🗝️', name: 'Skeleton Key', kind: 'item' },
  { id: 'tok_sat', icon: '🛰️', name: 'The Satellite', kind: 'item' },
  { id: 'tok_shades', icon: '🕶️', name: 'The Shades', kind: 'item' },
]

export const TOKEN_BY_ID: Record<string, TokenDef> = Object.fromEntries(TOKENS.map((t) => [t.id, t]))

export const ALL_CARDS: Card[] = [...SUSPECTS, ...DEVICES, ...LOCATIONS]

export const CARD_BY_ID: Record<string, Card> = Object.fromEntries(ALL_CARDS.map((c) => [c.id, c]))

export const PLAYER_COLORS = ['#4fd1c5', '#f6ad55', '#fc8181', '#b794f4', '#68d391', '#63b3ed']

/* ------------------------------------------------------------------ *
 *  Monopoly-style ring board (POI-driven, geolocation-aware)
 * ------------------------------------------------------------------ */

export type TileType =
  | 'go'
  | 'location' // a buyable street/school property + deduction "room"
  | 'estate' // a buyable street property that is NOT a deduction room
  | 'station' // GO / rail station — a buyable "railroad"
  | 'store' // convenience store — pay for intel (service, not owned)
  | 'busstop' // small utility tile
  | 'intel' // draw a clue challenge
  | 'sweep' // run an ultrasonic sweep
  | 'jail' // detention cell (also "just visiting")
  | 'gotojail' // sends you to jail
  | 'corner' // Safehouse (free parking)
  | 'dealer' // the Supplier — take product on consignment / repay your debt
  | 'drophouse' // sell product for cash (raises heat, risk of a bust)
  | 'police' // police checkpoint — busted if your heat is too high

export type PoiKind = 'street' | 'school' | 'station' | 'store' | 'busstop'

export interface Tile {
  type: TileType
  label: string
  sub?: string
  /** For location tiles: the deduction location id (loc_1..loc_9). */
  locationId?: string
  poiKind?: PoiKind
  address?: string
  /** Buyable tiles: purchase price and rent charged to visitors. */
  price?: number
  rent?: number
  /** Player id who owns this tile (assigned during play). */
  owner?: string
}

/** A point of interest used to name a tile. */
export interface Poi {
  name: string
  address?: string
}

/** A full set of nearby POIs — from geolocation, or the Mimico default. */
export interface PoiSet {
  streets: Poi[]
  schools: Poi[]
  stations: Poi[]
  stores: Poi[]
  busstops: Poi[]
  /** Human label for where this board is set (e.g. "Mimico" or "your area"). */
  place: string
}

/** The base Mimico environment used by default and as the geolocation fallback. */
export const MIMICO_POI: PoiSet = {
  place: 'Mimico',
  streets: [
    { name: 'Royal York Road', address: 'Royal York Rd @ Mimico Ave' },
    { name: 'Lake Shore Blvd W', address: 'Lake Shore Blvd W' },
    { name: 'Mimico Avenue', address: 'Mimico Ave' },
    { name: 'Station Road', address: 'Station Rd @ Judson St' },
    { name: 'Superior Avenue', address: 'Superior Ave' },
    { name: 'Melrose Street', address: 'Melrose St' },
    { name: 'Cavell Avenue', address: 'Cavell Ave' },
    { name: 'Hillside Avenue', address: 'Hillside Ave' },
    { name: 'Manchester Street', address: 'Manchester St' },
    { name: 'Wesley Street', address: 'Wesley St' },
    { name: 'Portland Street', address: 'Portland St' },
    { name: 'Drummond Street', address: 'Drummond St' },
  ],
  schools: [
    { name: 'Bishop Allen Academy', address: '721 Royal York Rd' },
    { name: 'David Hornell School', address: '640 The Queensway' },
    { name: 'John English School', address: '95 Ourland Ave' },
    { name: 'Second Street School', address: '121 Second St' },
    { name: 'Norseman School', address: '105 Guthrie Ave' },
    { name: 'St. Leo Catholic School', address: '165 Stanley Ave' },
  ],
  // Royal York Station leads so it lands on the mid-board station slot.
  stations: [
    { name: 'Mimico GO Station', address: 'Royal York Rd' },
    { name: 'Royal York Station', address: 'Bloor & Royal York · Line 2' },
    { name: 'Long Branch GO', address: 'Brown’s Line' },
  ],
  stores: [
    { name: 'Mimico Variety', address: 'Mimico Ave' },
    { name: 'Lakeshore Convenience', address: 'Lake Shore Blvd W' },
    { name: 'Royal York Mini Mart', address: 'Royal York Rd' },
    { name: 'Superior Variety', address: 'Superior Ave' },
  ],
  busstops: [
    { name: 'Royal York & Judson', address: 'TTC 76' },
    { name: 'Lake Shore & Superior', address: 'TTC 501' },
    { name: 'Mimico & Station', address: 'TTC 44' },
  ],
}

/** Nine stable deduction-location ids, in board-slot order. */
export const LOCATION_IDS = LOCATIONS.map((c) => c.id)

/**
 * The fixed 24-slot template. Tile *types* and positions are constant (so the
 * geometry and hop math never change); the POI *content* is filled per-game by
 * buildBoard from either geolocation or the Mimico default.
 */
type Slot = { type: TileType; poiKind?: PoiKind; label?: string; sub?: string }
// A 32-tile ring on a 9×9 perimeter (corners at 0, 8, 16, 24).
const LAYOUT: Slot[] = [
  { type: 'go', label: 'Field HQ', sub: 'collect $200' }, // 0  corner
  { type: 'location', poiKind: 'street' }, // 1
  { type: 'store' }, // 2
  { type: 'estate', poiKind: 'street' }, // 3
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 4
  { type: 'location', poiKind: 'school' }, // 5
  { type: 'intel', label: 'Dead Drop', sub: 'clue challenge' }, // 6
  { type: 'station' }, // 7  (Mimico GO)
  { type: 'jail', label: 'Detention', sub: 'just visiting' }, // 8  corner
  { type: 'location', poiKind: 'street' }, // 9
  { type: 'busstop' }, // 10
  { type: 'estate', poiKind: 'street' }, // 11
  { type: 'store' }, // 12
  { type: 'location', poiKind: 'school' }, // 13
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 14
  { type: 'station' }, // 15 (Royal York Station)
  { type: 'corner', label: 'Safehouse', sub: 'free parking' }, // 16 corner
  { type: 'location', poiKind: 'street' }, // 17
  { type: 'intel', label: 'Cipher Cache', sub: 'clue challenge' }, // 18
  { type: 'dealer', label: 'The Supplier', sub: 'take product / repay' }, // 19
  { type: 'station' }, // 20 (Long Branch GO)
  { type: 'location', poiKind: 'school' }, // 21
  { type: 'drophouse', label: 'Drop House', sub: 'sell product' }, // 22
  { type: 'sweep', label: 'Signal Node', sub: 'ultrasonic sweep' }, // 23
  { type: 'gotojail', label: 'Interception', sub: 'go to detention' }, // 24 corner
  { type: 'location', poiKind: 'street' }, // 25
  { type: 'drophouse', label: 'Drop House', sub: 'sell product' }, // 26
  { type: 'police', label: 'Police Check', sub: 'busted if hot' }, // 27
  { type: 'intel', label: 'Wiretap', sub: 'clue challenge' }, // 28
  { type: 'location', poiKind: 'street' }, // 29
  { type: 'store' }, // 30
  { type: 'location', poiKind: 'school' }, // 31
]

export const JAIL_POS = 8
export const GOTOJAIL_POS = 24
export const SAFEHOUSE_POS = 16
export const STATION_PRICE = 200
export const BUS_FARE = 25

/** Tiles that draw a clue challenge when landed on. */
export const CHALLENGE_TILES = new Set<TileType>(['intel'])
/** Buyable property tiles. */
export const BUYABLE = new Set<TileType>(['location', 'estate', 'station'])

/** Pull items cyclically so a short POI list still fills every slot. */
function cyc<T>(arr: T[], i: number, fallback: T): T {
  return arr.length ? arr[i % arr.length] : fallback
}

/**
 * Build the 24-tile board from a POI set. Location slots (1..9 in encounter
 * order) get the stable loc ids and are priced as properties; stations/stores/
 * busstops draw their names from the POI pools.
 */
export function buildBoard(poi: PoiSet): Tile[] {
  let locN = 0
  let estateN = 0
  let stationN = 0
  let storeN = 0
  let busN = 0
  let streetN = 0
  let schoolN = 0

  return LAYOUT.map((slot, i): Tile => {
    switch (slot.type) {
      case 'location': {
        const locId = LOCATION_IDS[locN]
        const p =
          slot.poiKind === 'school'
            ? cyc(poi.schools, schoolN++, { name: 'School' })
            : cyc(poi.streets, streetN++, { name: 'Street' })
        const price = 120 + locN * 18
        locN++
        return {
          type: 'location',
          label: p.name,
          address: p.address,
          locationId: locId,
          poiKind: slot.poiKind,
          price,
          rent: Math.round(price * 0.2),
        }
      }
      case 'estate': {
        // Buyable street property, not a deduction room.
        const p = cyc(poi.streets, streetN++, { name: 'Street' })
        const price = 100 + estateN++ * 14
        return {
          type: 'estate',
          label: p.name,
          address: p.address,
          poiKind: 'street',
          price,
          rent: Math.round(price * 0.18),
        }
      }
      case 'station': {
        const p = cyc(poi.stations, stationN++, { name: 'GO Station' })
        return {
          type: 'station',
          label: p.name,
          address: p.address,
          poiKind: 'station',
          price: STATION_PRICE,
          rent: 50,
        }
      }
      case 'store': {
        const p = cyc(poi.stores, storeN++, { name: 'Convenience Store' })
        return { type: 'store', label: p.name, address: p.address, poiKind: 'store', sub: 'buy intel $100' }
      }
      case 'busstop': {
        const p = cyc(poi.busstops, busN++, { name: 'Bus Stop' })
        return { type: 'busstop', label: p.name, address: p.address, poiKind: 'busstop', sub: `hop a bus $${BUS_FARE}` }
      }
      default:
        return { type: slot.type, label: slot.label ?? '', sub: slot.sub }
    }
  })
}

export const BOARD_DIM = 9 // 9×9 grid; perimeter = 4*(9-1) = 32 tiles
export const RING_LEN = 32

/** Grid (row, col) for ring index, clockwise from the top-left corner. */
export function ringCoord(index: number, dim = BOARD_DIM): { row: number; col: number } {
  const n = ((index % (4 * (dim - 1))) + 4 * (dim - 1)) % (4 * (dim - 1))
  if (n < dim) return { row: 0, col: n } // top row L→R
  if (n < 2 * dim - 1) return { row: n - (dim - 1), col: dim - 1 } // right col T→B
  if (n < 3 * dim - 2) return { row: dim - 1, col: dim - 1 - (n - (2 * dim - 2)) } // bottom R→L
  return { row: dim - 1 - (n - (3 * dim - 3)), col: 0 } // left col B→T
}

export const STATION_POSITIONS = LAYOUT.map((s, i) => (s.type === 'station' ? i : -1)).filter((i) => i >= 0)
