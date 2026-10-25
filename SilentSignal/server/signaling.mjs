/**
 * SnitchesAreAmongUs — WebRTC signaling server.
 *
 * A tiny WebSocket relay whose only job is to shuttle SDP offers/answers and
 * ICE candidates between a host and the guests joining its room code. Once the
 * peer connection is up, game traffic flows peer-to-peer over WebRTC data
 * channels — this server sees none of it.
 *
 * Run:  node server/signaling.mjs           (defaults to port 8080)
 *       PORT=9000 node server/signaling.mjs
 *
 * For LAN play the guests connect to ws://<host-ip>:8080. For play over the
 * internet, deploy this somewhere public (Render/Fly/a VPS) and point the app's
 * VITE_SIGNAL_URL at it — and note that restrictive NATs may also need a TURN
 * server (STUN alone isn't always enough).
 */
import { WebSocketServer } from 'ws'

const PORT = Number(process.env.PORT || 8080)
const wss = new WebSocketServer({ port: PORT })

/** code -> { host: ws, guests: Map<id, ws> } */
const rooms = new Map()

function code() {
  const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789' // no ambiguous chars
  let c = ''
  for (let i = 0; i < 4; i++) c += alphabet[Math.floor(Math.random() * alphabet.length)]
  return c
}
function id() {
  return Math.random().toString(36).slice(2, 10)
}
function send(ws, obj) {
  if (ws && ws.readyState === ws.OPEN) ws.send(JSON.stringify(obj))
}

wss.on('connection', (ws) => {
  ws.meta = { role: null, room: null, id: id() }

  ws.on('message', (raw) => {
    let msg
    try {
      msg = JSON.parse(raw.toString())
    } catch {
      return
    }

    switch (msg.t) {
      case 'host': {
        let c = code()
        while (rooms.has(c)) c = code()
        rooms.set(c, { host: ws, guests: new Map() })
        ws.meta.role = 'host'
        ws.meta.room = c
        send(ws, { t: 'room', code: c, id: ws.meta.id })
        break
      }
      case 'join': {
        const room = rooms.get(String(msg.code || '').toUpperCase())
        if (!room) return send(ws, { t: 'error', error: 'No such room' })
        ws.meta.role = 'guest'
        ws.meta.room = String(msg.code).toUpperCase()
        room.guests.set(ws.meta.id, ws)
        send(ws, { t: 'joined', code: ws.meta.room, id: ws.meta.id })
        // Tell the host a peer arrived so it can start the WebRTC offer.
        send(room.host, { t: 'peer', id: ws.meta.id, name: msg.name || 'Agent' })
        break
      }
      case 'signal': {
        // Relay an SDP/ICE payload to a specific peer in the same room.
        const room = rooms.get(ws.meta.room)
        if (!room) return
        const target =
          ws.meta.role === 'host' ? room.guests.get(msg.to) : room.host
        send(target, { t: 'signal', from: ws.meta.id, data: msg.data })
        break
      }
    }
  })

  ws.on('close', () => {
    const room = rooms.get(ws.meta.room)
    if (!room) return
    if (ws.meta.role === 'host') {
      for (const g of room.guests.values()) send(g, { t: 'host-left' })
      rooms.delete(ws.meta.room)
    } else {
      room.guests.delete(ws.meta.id)
      send(room.host, { t: 'peer-left', id: ws.meta.id })
    }
  })
})

console.log(`[signaling] SnitchesAreAmongUs signaling server on ws://0.0.0.0:${PORT}`)
