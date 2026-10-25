import { NetMsg } from './types'

/**
 * A duplex message channel between this client and one peer. WebRTC data
 * channels and a plain WebSocket relay both implement this, so the game-sync
 * layer is transport-agnostic (and unit-testable with a mock).
 *
 * On the HOST there is one Transport per connected guest; on a GUEST there is a
 * single Transport to the host.
 */
export interface Transport {
  readonly peerId: string
  send(msg: NetMsg): void
  onMessage(cb: (msg: NetMsg) => void): void
  onClose(cb: () => void): void
  close(): void
}

/** In-memory transport pair for tests — two ends wired directly together. */
export function mockTransportPair(a = 'host', b = 'guest'): [Transport, Transport] {
  const cbA: { msg?: (m: NetMsg) => void; close?: () => void } = {}
  const cbB: { msg?: (m: NetMsg) => void; close?: () => void } = {}
  const A: Transport = {
    peerId: b,
    send: (m) => queueMicrotask(() => cbB.msg?.(structuredClone(m))),
    onMessage: (cb) => (cbA.msg = cb),
    onClose: (cb) => (cbA.close = cb),
    close: () => cbB.close?.(),
  }
  const B: Transport = {
    peerId: a,
    send: (m) => queueMicrotask(() => cbA.msg?.(structuredClone(m))),
    onMessage: (cb) => (cbB.msg = cb),
    onClose: (cb) => (cbB.close = cb),
    close: () => cbA.close?.(),
  }
  return [A, B]
}
