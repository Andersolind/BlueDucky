import { Transport } from './transport'
import { NetMsg } from './types'

/**
 * WebRTC transport over the signaling server. The server only brokers the
 * SDP/ICE handshake; game messages then flow peer-to-peer over data channels.
 */

const ICE = [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:global.stun.twilio.com:3478' }]

/** Default signaling URL: env override, else same host on :8080. */
export function defaultSignalUrl(): string {
  const env = (import.meta as any).env?.VITE_SIGNAL_URL
  if (env) return env
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.hostname}:8080`
}

function channelTransport(peerId: string, dc: RTCDataChannel): Transport {
  let onMsg: ((m: NetMsg) => void) | undefined
  let onCl: (() => void) | undefined
  dc.onmessage = (e) => {
    try {
      onMsg?.(JSON.parse(e.data))
    } catch {
      /* ignore malformed */
    }
  }
  dc.onclose = () => onCl?.()
  return {
    peerId,
    send: (m) => {
      if (dc.readyState === 'open') dc.send(JSON.stringify(m))
    },
    onMessage: (cb) => (onMsg = cb),
    onClose: (cb) => (onCl = cb),
    close: () => dc.close(),
  }
}

export interface HostConn {
  onCode: (cb: (code: string) => void) => void
  onGuest: (cb: (t: Transport, name: string) => void) => void
  onError: (cb: (e: string) => void) => void
  close: () => void
}

export function createHost(signalUrl = defaultSignalUrl()): HostConn {
  const ws = new WebSocket(signalUrl)
  const peers = new Map<string, RTCPeerConnection>()
  let codeCb: (c: string) => void = () => {}
  let guestCb: (t: Transport, name: string) => void = () => {}
  let errCb: (e: string) => void = () => {}

  ws.onopen = () => ws.send(JSON.stringify({ t: 'host' }))
  ws.onerror = () => errCb('Could not reach the signaling server.')
  ws.onmessage = async (ev) => {
    const m = JSON.parse(ev.data)
    if (m.t === 'room') codeCb(m.code)
    else if (m.t === 'peer') {
      // A guest joined — create a peer connection and offer them a channel.
      const pc = new RTCPeerConnection({ iceServers: ICE })
      peers.set(m.id, pc)
      pc.onicecandidate = (e) => {
        if (e.candidate) ws.send(JSON.stringify({ t: 'signal', to: m.id, data: { candidate: e.candidate } }))
      }
      const dc = pc.createDataChannel('game', { ordered: true })
      dc.onopen = () => guestCb(channelTransport(m.id, dc), m.name || 'Agent')
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      ws.send(JSON.stringify({ t: 'signal', to: m.id, data: { sdp: pc.localDescription } }))
    } else if (m.t === 'signal') {
      const pc = peers.get(m.from)
      if (!pc) return
      if (m.data.sdp) await pc.setRemoteDescription(m.data.sdp)
      else if (m.data.candidate) await pc.addIceCandidate(m.data.candidate).catch(() => {})
    } else if (m.t === 'peer-left') {
      peers.get(m.id)?.close()
      peers.delete(m.id)
    }
  }

  return {
    onCode: (cb) => (codeCb = cb),
    onGuest: (cb) => (guestCb = cb),
    onError: (cb) => (errCb = cb),
    close: () => {
      peers.forEach((p) => p.close())
      ws.close()
    },
  }
}

export interface GuestConn {
  onHost: (cb: (t: Transport) => void) => void
  onError: (cb: (e: string) => void) => void
  close: () => void
}

export function createGuest(code: string, name: string, signalUrl = defaultSignalUrl()): GuestConn {
  const ws = new WebSocket(signalUrl)
  let pc: RTCPeerConnection | null = null
  let hostCb: (t: Transport) => void = () => {}
  let errCb: (e: string) => void = () => {}

  ws.onopen = () => ws.send(JSON.stringify({ t: 'join', code, name }))
  ws.onerror = () => errCb('Could not reach the signaling server.')
  ws.onmessage = async (ev) => {
    const m = JSON.parse(ev.data)
    if (m.t === 'error') errCb(m.error)
    else if (m.t === 'host-left') errCb('The host left the game.')
    else if (m.t === 'signal') {
      if (!pc) {
        pc = new RTCPeerConnection({ iceServers: ICE })
        pc.onicecandidate = (e) => {
          if (e.candidate) ws.send(JSON.stringify({ t: 'signal', to: m.from, data: { candidate: e.candidate } }))
        }
        pc.ondatachannel = (e) => {
          const dc = e.channel
          dc.onopen = () => hostCb(channelTransport(m.from, dc))
        }
      }
      if (m.data.sdp) {
        await pc.setRemoteDescription(m.data.sdp)
        const answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        ws.send(JSON.stringify({ t: 'signal', to: m.from, data: { sdp: pc.localDescription } }))
      } else if (m.data.candidate) {
        await pc.addIceCandidate(m.data.candidate).catch(() => {})
      }
    }
  }

  return {
    onHost: (cb) => (hostCb = cb),
    onError: (cb) => (errCb = cb),
    close: () => {
      pc?.close()
      ws.close()
    },
  }
}
