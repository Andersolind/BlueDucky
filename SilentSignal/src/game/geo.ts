import { MIMICO_POI, Poi, PoiSet } from './data'

/**
 * Geolocation → live board. On opt-in we ask the browser for the user's
 * position, then query OpenStreetMap's Overpass API for nearby streets,
 * schools, GO/rail stations, bus stops and convenience stores — turning the
 * player's real neighbourhood into the board. Anything missing is topped up
 * from the Mimico default so every slot is always filled.
 *
 * This is best-effort and entirely optional: if geolocation is denied, the
 * network is unavailable, or too few POIs come back, we fall back to Mimico.
 */

const OVERPASS = 'https://overpass-api.de/api/interpreter'
const RADIUS_M = 1200

function getPosition(timeoutMs = 8000): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) return reject(new Error('Geolocation unsupported'))
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      timeout: timeoutMs,
      maximumAge: 60000,
    })
  })
}

function overpassQuery(lat: number, lon: number): string {
  const r = RADIUS_M
  // One query, several sub-queries — streets by name, plus tagged POIs.
  return `[out:json][timeout:20];
    (
      way(around:${r},${lat},${lon})[highway~"^(residential|tertiary|secondary|primary|living_street)$"][name];
      node(around:${r},${lat},${lon})[amenity=school];
      way(around:${r},${lat},${lon})[amenity=school];
      node(around:${r},${lat},${lon})[railway=station];
      node(around:${r},${lat},${lon})[public_transport=station];
      node(around:${r},${lat},${lon})[highway=bus_stop];
      node(around:${r},${lat},${lon})[shop=convenience];
    );
    out center tags 80;`
}

interface OsmEl {
  type: string
  tags?: Record<string, string>
}

function uniqByName(items: Poi[]): Poi[] {
  const seen = new Set<string>()
  const out: Poi[] = []
  for (const p of items) {
    const key = p.name.toLowerCase()
    if (p.name && !seen.has(key)) {
      seen.add(key)
      out.push(p)
    }
  }
  return out
}

function classify(elements: OsmEl[]): PoiSet {
  const streets: Poi[] = []
  const schools: Poi[] = []
  const stations: Poi[] = []
  const stores: Poi[] = []
  const busstops: Poi[] = []

  for (const el of elements) {
    const t = el.tags ?? {}
    const name = t.name
    if (!name) continue
    if (t.amenity === 'school') schools.push({ name, address: t['addr:street'] })
    else if (t.railway === 'station' || t.public_transport === 'station')
      stations.push({ name, address: 'transit' })
    else if (t.highway === 'bus_stop') busstops.push({ name, address: t.route_ref ? `route ${t.route_ref}` : 'bus stop' })
    else if (t.shop === 'convenience') stores.push({ name, address: t['addr:street'] })
    else if (t.highway) streets.push({ name, address: name })
  }

  // Fill any thin category from the Mimico defaults so the board is complete.
  const topUp = (got: Poi[], base: Poi[], min: number) =>
    uniqByName(got.length >= min ? got : [...got, ...base]).slice(0, Math.max(min, got.length))

  return {
    place: 'your area',
    streets: topUp(uniqByName(streets), MIMICO_POI.streets, 6),
    schools: topUp(uniqByName(schools), MIMICO_POI.schools, 3),
    stations: topUp(uniqByName(stations), MIMICO_POI.stations, 2),
    stores: topUp(uniqByName(stores), MIMICO_POI.stores, 3),
    busstops: topUp(uniqByName(busstops), MIMICO_POI.busstops, 2),
  }
}

/**
 * Resolve a POI set for the player's location, or throw so the caller can fall
 * back to Mimico. Returns the Mimico set unchanged if too little data is found.
 */
export async function getLocalPoi(): Promise<PoiSet> {
  const pos = await getPosition()
  const { latitude, longitude } = pos.coords

  const res = await fetch(OVERPASS, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: overpassQuery(latitude, longitude),
  })
  if (!res.ok) throw new Error(`Overpass ${res.status}`)
  const data = (await res.json()) as { elements: OsmEl[] }
  const poi = classify(data.elements ?? [])

  // Sanity: if we didn't get enough real streets, it's not worth it.
  if (poi.streets.length < 6) throw new Error('Not enough nearby streets found')
  return poi
}
