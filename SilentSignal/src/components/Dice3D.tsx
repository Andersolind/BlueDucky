import { useEffect, useRef } from 'react'
import * as THREE from 'three'

interface Props {
  value: number // 1..6 — the face to settle on
  color: string
  onDone: () => void
}

const SPIN_MS = 900
const SETTLE_MS = 650

/** Face → outward normal, for the BoxGeometry material order [px,nx,py,ny,pz,nz]. */
const FACE_VALUE = [3, 4, 5, 2, 1, 6]
const VALUE_NORMAL: Record<number, THREE.Vector3> = {
  1: new THREE.Vector3(0, 0, 1),
  6: new THREE.Vector3(0, 0, -1),
  3: new THREE.Vector3(1, 0, 0),
  4: new THREE.Vector3(-1, 0, 0),
  5: new THREE.Vector3(0, 1, 0),
  2: new THREE.Vector3(0, -1, 0),
}

/** A quick tumbling 3D die that settles showing `value` toward the camera. */
export default function Dice3D({ value, color, onDone }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    const mount = mountRef.current!
    const size = mount.clientWidth
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
    renderer.setSize(size, size)
    mount.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100)
    camera.position.set(0, 0, 5)

    scene.add(new THREE.AmbientLight(0xffffff, 0.75))
    const key = new THREE.DirectionalLight(0xffffff, 1.4)
    key.position.set(3, 5, 4)
    scene.add(key)
    const tint = new THREE.PointLight(new THREE.Color(color).getHex(), 1.2, 20)
    tint.position.set(-3, -2, 3)
    scene.add(tint)

    const mats = FACE_VALUE.map((v) => new THREE.MeshStandardMaterial({ map: pipTexture(v, color), roughness: 0.35, metalness: 0.1 }))
    const die = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.6, 1.6), mats)
    scene.add(die)

    const targetQuat = new THREE.Quaternion().setFromUnitVectors(
      VALUE_NORMAL[value].clone(),
      new THREE.Vector3(0, 0, 1)
    )
    const wx = 6 + Math.random() * 6
    const wy = 5 + Math.random() * 6

    let raf = 0
    const start = performance.now()
    let handoff: THREE.Quaternion | null = null
    let last = start

    const tick = () => {
      const now = performance.now()
      const dt = (now - last) / 1000
      last = now
      const el = now - start

      if (el < SPIN_MS) {
        die.rotation.x += wx * dt
        die.rotation.y += wy * dt
        die.position.y = Math.sin(el / 90) * 0.25
      } else {
        if (!handoff) handoff = die.quaternion.clone()
        const k = Math.min(1, (el - SPIN_MS) / SETTLE_MS)
        const e = 1 - Math.pow(1 - k, 3) // easeOutCubic
        die.quaternion.slerpQuaternions(handoff, targetQuat, e)
        die.position.y = Math.sin(Math.min(1, k) * Math.PI) * 0.12 * (1 - k)
      }

      renderer.render(scene, camera)
      if (el < SPIN_MS + SETTLE_MS + 250) raf = requestAnimationFrame(tick)
      else doneRef.current()
    }
    raf = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(raf)
      renderer.dispose()
      die.geometry.dispose()
      mats.forEach((m) => {
        m.map?.dispose()
        m.dispose()
      })
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="overlay dice-overlay" onClick={() => doneRef.current()}>
      <div className="dice-stage">
        <div className="dice-canvas" ref={mountRef} />
        <div className="dice-value">rolled {value}</div>
      </div>
    </div>
  )
}

/** Draw a die face (rounded square + pips) to a texture. */
function pipTexture(n: number, color: string): THREE.CanvasTexture {
  const S = 128
  const c = document.createElement('canvas')
  c.width = c.height = S
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#f4f1e8'
  roundRect(ctx, 4, 4, S - 8, S - 8, 18)
  ctx.fill()
  ctx.strokeStyle = color
  ctx.lineWidth = 4
  roundRect(ctx, 4, 4, S - 8, S - 8, 18)
  ctx.stroke()

  const g = S / 4
  const pts: Record<number, [number, number][]> = {
    1: [[2, 2]],
    2: [[1, 1], [3, 3]],
    3: [[1, 1], [2, 2], [3, 3]],
    4: [[1, 1], [1, 3], [3, 1], [3, 3]],
    5: [[1, 1], [1, 3], [2, 2], [3, 1], [3, 3]],
    6: [[1, 1], [1, 2], [1, 3], [3, 1], [3, 2], [3, 3]],
  }
  ctx.fillStyle = '#1a1a22'
  for (const [gx, gy] of pts[n]) {
    ctx.beginPath()
    ctx.arc(gx * g, gy * g, 11, 0, Math.PI * 2)
    ctx.fill()
  }
  const tex = new THREE.CanvasTexture(c)
  tex.needsUpdate = true
  return tex
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}
