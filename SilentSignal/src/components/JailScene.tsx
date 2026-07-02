import { useEffect, useRef } from 'react'
import * as THREE from 'three'

interface Props {
  /** Player token emoji shown as the piece being shocked. */
  icon: string
  /** Player colour (hex string). */
  color: string
  name: string
  onDone: () => void
}

const DURATION = 4200 // ms

/**
 * A live Three.js "detention" sequence: the player's token is pinned in the
 * middle of a ring of acoustic-array emitters that blast it with ultrasonic
 * beams — arcs, sparks and a screen shake — while a skull looms behind. Plays
 * once when a human is sent to Detention, then closes.
 */
export default function JailScene({ icon, color, name, onDone }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    const mount = mountRef.current!
    const width = mount.clientWidth
    const height = mount.clientHeight
    const col = new THREE.Color(color)

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
    renderer.setSize(width, height)
    mount.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2(0x05070d, 0.11)

    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100)
    camera.position.set(0, 0.6, 7)
    camera.lookAt(0, 0.2, 1)

    // ---- Lighting ----
    const ambient = new THREE.AmbientLight(0x33405a, 0.9)
    scene.add(ambient)
    const key = new THREE.PointLight(col.getHex(), 2.2, 40)
    key.position.set(0, 0.5, 3)
    scene.add(key)
    const rim = new THREE.PointLight(0x4fd1c5, 1.4, 30)
    rim.position.set(-4, 3, -2)
    scene.add(rim)

    // ---- Skull (procedural, looming behind) ----
    const skull = new THREE.Group()
    const bone = new THREE.MeshStandardMaterial({ color: 0xd8d2c0, roughness: 0.75, metalness: 0.05 })
    const cranium = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 24), bone)
    cranium.scale.set(1, 1.05, 1.08)
    skull.add(cranium)
    const jaw = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.4, 0.7), bone)
    jaw.position.set(0, -0.98, 0.18)
    skull.add(jaw)
    // teeth
    for (let i = 0; i < 6; i++) {
      const tooth = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.18, 0.08), bone)
      tooth.position.set(-0.34 + i * 0.135, -0.78, 0.52)
      skull.add(tooth)
    }
    // nasal cavity
    const nasal = new THREE.Mesh(
      new THREE.ConeGeometry(0.12, 0.32, 6),
      new THREE.MeshStandardMaterial({ color: 0x14100c })
    )
    nasal.position.set(0, -0.28, 0.92)
    skull.add(nasal)
    // glowing eye sockets
    const eyeMat = new THREE.MeshStandardMaterial({
      color: 0x120608,
      emissive: new THREE.Color(0xff2a2a),
      emissiveIntensity: 0.2,
    })
    const eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.28, 20, 16), eyeMat)
    eyeL.position.set(-0.42, 0.12, 0.72)
    eyeL.scale.set(1, 1, 0.7)
    const eyeR = eyeL.clone()
    eyeR.position.x = 0.42
    skull.add(eyeL, eyeR)

    skull.position.set(0, 0.7, -1.6)
    skull.scale.setScalar(1.5)
    scene.add(skull)

    // ---- The token being shocked ----
    const tokenGroup = new THREE.Group()
    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.5, 1),
      new THREE.MeshStandardMaterial({
        color: col,
        emissive: col,
        emissiveIntensity: 0.6,
        roughness: 0.3,
        metalness: 0.4,
      })
    )
    tokenGroup.add(core)
    // token emoji sprite riding on the core
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: emojiTexture(icon), transparent: true })
    )
    sprite.scale.setScalar(0.9)
    tokenGroup.add(sprite)
    tokenGroup.position.set(0, 0.1, 2.2)
    scene.add(tokenGroup)

    // ---- Acoustic beam array: a ring of emitters firing at the token ----
    const ARRAY_N = 16
    const ringR = 1.7
    const emitters: THREE.Mesh[] = []
    const beams: { mesh: THREE.Mesh; mat: THREE.MeshBasicMaterial; phase: number }[] = []
    const beamColor = new THREE.Color(0x4fd1c5)
    const target = tokenGroup.position

    for (let i = 0; i < ARRAY_N; i++) {
      const a = (i / ARRAY_N) * Math.PI * 2
      const from = new THREE.Vector3(
        target.x + Math.cos(a) * ringR,
        target.y + Math.sin(a) * ringR * 0.85,
        target.z + Math.sin(a * 2) * 0.25
      )
      // emitter (a small cone pointing at the token)
      const em = new THREE.Mesh(
        new THREE.ConeGeometry(0.12, 0.32, 8),
        new THREE.MeshStandardMaterial({ color: 0x1b2740, emissive: beamColor, emissiveIntensity: 0.4, metalness: 0.6, roughness: 0.4 })
      )
      em.position.copy(from)
      em.lookAt(target)
      em.rotateX(Math.PI / 2)
      scene.add(em)
      emitters.push(em)

      // beam (thin cylinder from emitter to token)
      const dir = target.clone().sub(from)
      const len = dir.length()
      const mat = new THREE.MeshBasicMaterial({ color: beamColor, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false })
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.06, len, 6), mat)
      beam.position.copy(from).add(dir.clone().multiplyScalar(0.5))
      beam.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize())
      scene.add(beam)
      beams.push({ mesh: beam, mat, phase: (i / ARRAY_N) * Math.PI * 2 })
    }

    // ---- Spark particles ----
    const SPARKS = 120
    const sparkGeo = new THREE.BufferGeometry()
    const sparkPos = new Float32Array(SPARKS * 3)
    const sparkVel: THREE.Vector3[] = []
    for (let i = 0; i < SPARKS; i++) {
      resetSpark(i)
    }
    function resetSpark(i: number) {
      sparkPos[i * 3] = target.x
      sparkPos[i * 3 + 1] = target.y
      sparkPos[i * 3 + 2] = target.z
      sparkVel[i] = new THREE.Vector3(
        (Math.random() - 0.5) * 6,
        (Math.random() - 0.5) * 6,
        (Math.random() - 0.5) * 6
      )
    }
    sparkGeo.setAttribute('position', new THREE.BufferAttribute(sparkPos, 3))
    const sparks = new THREE.Points(
      sparkGeo,
      new THREE.PointsMaterial({ color: 0xfff2cc, size: 0.06, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false })
    )
    scene.add(sparks)

    // ---- Animation loop ----
    let raf = 0
    const start = performance.now()
    const basePos = camera.position.clone()

    const tick = () => {
      const now = performance.now()
      const t = (now - start) / 1000
      const prog = Math.min(1, (now - start) / DURATION)

      // charge in first 0.5s, blast until ~0.85, ease out
      const blast = prog < 0.12 ? prog / 0.12 : prog > 0.86 ? Math.max(0, (1 - prog) / 0.14) : 1

      skull.rotation.y = Math.sin(t * 0.6) * 0.25
      eyeMat.emissiveIntensity = 0.3 + blast * (1.4 + Math.sin(t * 22) * 0.8)

      // token convulses under the beams
      const jitter = 0.12 * blast
      tokenGroup.position.set(
        (Math.random() - 0.5) * jitter,
        0.1 + (Math.random() - 0.5) * jitter,
        2.2 + (Math.random() - 0.5) * jitter
      )
      const pulse = 1 + Math.sin(t * 30) * 0.12 * blast
      core.scale.setScalar(pulse)
      ;(core.material as THREE.MeshStandardMaterial).emissiveIntensity = 0.5 + blast * (1.2 + Math.sin(t * 40) * 0.6)
      key.intensity = 1.6 + blast * (2.5 + Math.sin(t * 35) * 1.5)
      sprite.material.rotation = (Math.random() - 0.5) * 0.3 * blast

      // beams fire in a travelling pulse around the ring
      for (const b of beams) {
        const fire = Math.max(0, Math.sin(t * 12 - b.phase * 2))
        b.mat.opacity = fire * 0.85 * blast
      }
      for (const em of emitters) {
        ;(em.material as THREE.MeshStandardMaterial).emissiveIntensity = 0.4 + blast * 1.4
      }

      // sparks stream outward then respawn
      const pos = sparkGeo.getAttribute('position') as THREE.BufferAttribute
      for (let i = 0; i < SPARKS; i++) {
        const v = sparkVel[i]
        pos.array[i * 3] += v.x * 0.016
        pos.array[i * 3 + 1] += v.y * 0.016
        pos.array[i * 3 + 2] += v.z * 0.016
        v.multiplyScalar(0.94)
        if (Math.random() < 0.03 || v.lengthSq() < 0.02) resetSpark(i)
      }
      pos.needsUpdate = true
      ;(sparks.material as THREE.PointsMaterial).opacity = 0.9 * blast

      // screen shake at peak
      const shake = 0.06 * blast
      camera.position.set(
        basePos.x + (Math.random() - 0.5) * shake,
        basePos.y + (Math.random() - 0.5) * shake,
        basePos.z + (Math.random() - 0.5) * shake
      )
      camera.lookAt(0, 0.2, 1.6)

      renderer.render(scene, camera)
      if (now - start < DURATION) raf = requestAnimationFrame(tick)
      else doneRef.current()
    }
    raf = requestAnimationFrame(tick)

    const onResize = () => {
      const w = mount.clientWidth
      const h = mount.clientHeight
      renderer.setSize(w, h)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      renderer.dispose()
      scene.traverse((o) => {
        const m = o as THREE.Mesh
        if (m.geometry) m.geometry.dispose()
        const mat = (m as any).material
        if (Array.isArray(mat)) mat.forEach((x: THREE.Material) => x.dispose())
        else if (mat) mat.dispose()
      })
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="overlay jail-overlay">
      <div className="jail-scene">
        <div className="jail-canvas" ref={mountRef} />
        <div className="jail-caption">
          <div className="jail-title">◈ DETAINED ◈</div>
          <div className="jail-sub">
            {name} is pinned under the acoustic array
          </div>
        </div>
        <button className="ghost jail-skip" onClick={() => doneRef.current()}>
          Skip ✕
        </button>
      </div>
    </div>
  )
}

/** Render an emoji to a small canvas texture for the token sprite. */
function emojiTexture(emoji: string): THREE.Texture {
  const size = 128
  const c = document.createElement('canvas')
  c.width = c.height = size
  const ctx = c.getContext('2d')!
  ctx.font = '92px serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(emoji, size / 2, size / 2 + 6)
  const tex = new THREE.CanvasTexture(c)
  tex.needsUpdate = true
  return tex
}
