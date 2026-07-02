import { useCallback, useEffect, useRef, useState } from 'react'
import {
  DEFAULT_CONFIG,
  ModemConfig,
  UltrasonicReceiver,
  UltrasonicTransmitter,
  DecodeResult,
} from './ultrasonic'

export interface UltrasonicState {
  listening: boolean
  transmitting: boolean
  /** Smoothed near-ultrasonic band energy, 0..1-ish (log-scaled). */
  level: number
  lastMessage: DecodeResult | null
  error: string | null
}

export function useUltrasonic(cfg: ModemConfig = DEFAULT_CONFIG) {
  const txRef = useRef<UltrasonicTransmitter | null>(null)
  const rxRef = useRef<UltrasonicReceiver | null>(null)
  const levelRef = useRef(0)

  const [state, setState] = useState<UltrasonicState>({
    listening: false,
    transmitting: false,
    level: 0,
    lastMessage: null,
    error: null,
  })

  // Message subscribers (game logic wires into these).
  const subscribers = useRef<Set<(m: DecodeResult) => void>>(new Set())

  const subscribe = useCallback((fn: (m: DecodeResult) => void) => {
    subscribers.current.add(fn)
    return () => {
      subscribers.current.delete(fn)
    }
  }, [])

  const transmit = useCallback(
    async (text: string, gain = 0.9) => {
      if (!txRef.current) txRef.current = new UltrasonicTransmitter()
      setState((s) => ({ ...s, transmitting: true, error: null }))
      try {
        await txRef.current.transmit(text, cfg, gain)
      } catch (e: any) {
        setState((s) => ({ ...s, error: e?.message ?? 'Transmit failed' }))
      } finally {
        setState((s) => ({ ...s, transmitting: false }))
      }
    },
    [cfg]
  )

  const startListening = useCallback(async (): Promise<boolean> => {
    if (rxRef.current?.active) return true
    const rx = new UltrasonicReceiver(cfg, {
      onLevel: (dominance) => {
        // `dominance` is already a stable 0..1 ratio; light smoothing for the UI.
        levelRef.current = levelRef.current * 0.6 + dominance * 0.4
      },
      onMessage: (m) => {
        setState((s) => ({ ...s, lastMessage: m }))
        subscribers.current.forEach((fn) => fn(m))
      },
    })
    try {
      await rx.start()
      rxRef.current = rx
      setState((s) => ({ ...s, listening: true, error: null }))
      return true
    } catch (e: any) {
      setState((s) => ({
        ...s,
        error:
          e?.name === 'NotAllowedError'
            ? 'Microphone permission denied. Ultrasonic detection needs mic access.'
            : e?.message ?? 'Could not start microphone',
      }))
      return false
    }
  }, [cfg])

  const stopListening = useCallback(async () => {
    await rxRef.current?.stop()
    rxRef.current = null
    levelRef.current = 0
    setState((s) => ({ ...s, listening: false, level: 0 }))
  }, [])

  // Animation-frame pump so the level meter updates smoothly without
  // thrashing React state on every audio callback.
  useEffect(() => {
    let raf = 0
    const tick = () => {
      setState((s) => (Math.abs(s.level - levelRef.current) > 0.005 ? { ...s, level: levelRef.current } : s))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  useEffect(() => {
    return () => {
      rxRef.current?.stop()
      txRef.current?.close()
    }
  }, [])

  return { state, transmit, startListening, stopListening, subscribe }
}
