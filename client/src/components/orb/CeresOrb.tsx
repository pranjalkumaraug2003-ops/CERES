import { useEffect, useRef } from 'react'
import type { OrbState } from '../../core/state/ceresTypes'
import { RenderScheduler } from '../../core/RenderScheduler'

interface CeresOrbProps {
  state: OrbState
  visualIntensity: number
  audioAmplitude: number
  entryEffect: string | null
  onInterrupt: () => void
}

interface Vector3D { x: number; y: number; z: number }

interface Particle {
  orbitRadius: number
  theta: number
  speed: number
  pitch: number
  roll: number
  size: number
  alpha: number
  type: 'star' | 'debris' | 'spark'
}

// ── Energy targets per state ──
const stateTargets: Record<OrbState, { orb: number; env: number; res: number; focus: number }> = {
  BOOTING:      { orb: 0.15, env: 0.12, res: 0.00, focus: 0.20 },
  AUTH:         { orb: 0.20, env: 0.18, res: 0.00, focus: 0.30 },
  IDLE:         { orb: 0.18, env: 0.12, res: 0.00, focus: 0.10 },
  LISTENING:    { orb: 0.42, env: 0.28, res: 0.08, focus: 0.90 },
  THINKING:     { orb: 0.82, env: 0.35, res: 0.12, focus: 0.60 }, // env LOW = pressure silence
  SPEAKING:     { orb: 0.68, env: 0.50, res: 0.85, focus: 0.40 },
  INTERRUPTING: { orb: 0.05, env: 0.02, res: 0.00, focus: 0.00 },
  ERROR:        { orb: 0.50, env: 0.35, res: 0.20, focus: 0.30 },
}

// ── Plasma timing targets per state ──
const plasmaTargets: Record<OrbState, { flow: number; pulse: number }> = {
  BOOTING:      { flow: 0.10, pulse: 0.14 },
  AUTH:         { flow: 0.12, pulse: 0.16 },
  IDLE:         { flow: 0.12, pulse: 0.18 },
  LISTENING:    { flow: 0.28, pulse: 0.36 },
  THINKING:     { flow: 0.62, pulse: 0.78 },
  SPEAKING:     { flow: 0.46, pulse: 0.50 }, // pulse overridden by audio
  INTERRUPTING: { flow: 0.00, pulse: 0.00 },
  ERROR:        { flow: 0.20, pulse: 0.30 },
}

export function CeresOrb({ state, visualIntensity, audioAmplitude, entryEffect, onInterrupt }: CeresOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // ── Continuous energy fields (lerped, never jumped) ──
  const energyRef = useRef({
    orb: 0.18, env: 0.12, res: 0.0, focus: 0.1, scale: 1.0,
    plasmaFlow: 0.12, plasmaPulse: 0.18,
    resonanceMemory: 0,
  })

  // ── Causal propagation history buffer ──
  // Stores { time, amplitude, orbEnergy } snapshots so subsystems can read delayed values
  const historyRef = useRef<{ time: number; amp: number; orb: number }[]>([])

  // ── Two-layer inertia parallax ──
  const innerCoreRef = useRef({ x: 0, y: 0 })   // heavy, slow
  const outerShellRef = useRef({ x: 0, y: 0 })   // gaseous, laggy
  const mouseRef = useRef({ x: 0, y: 0, targetX: 0, targetY: 0 })

  // ── Low-frequency planetary drift ──
  const driftRef = useRef({ shellAngle: 0, coreOffX: 0, coreOffY: 0, ringTilt: 0 })

  // ── Cached surface texture ──
  const surfaceRef = useRef<HTMLCanvasElement | null>(null)

  // ── Orbital particles ──
  const particlesRef = useRef<Particle[]>([])


  // ── State ref for RAF access ──
  const stateRef = useRef(state)
  const ampRef = useRef(audioAmplitude)
  const viRef = useRef(visualIntensity)

  useEffect(() => { stateRef.current = state }, [state])
  useEffect(() => { ampRef.current = audioAmplitude }, [audioAmplitude])
  useEffect(() => { viRef.current = visualIntensity }, [visualIntensity])

  // ── One-time initialization ──
  useEffect(() => {

    // Generate orbital particles
    const particles: Particle[] = []
    for (let i = 0; i < 115; i++) {
      particles.push({
        orbitRadius: 96 + Math.random() * 95, // Gracefully spaced orbital particles
        theta: Math.random() * Math.PI * 2,
        speed: (0.0003 + Math.random() * 0.0007) * (Math.random() < 0.5 ? 1 : -1),
        pitch: (55 + Math.random() * 22) * Math.PI / 180,
        roll: (-35 + Math.random() * 70) * Math.PI / 180,
        size: Math.random() < 0.2 ? 1.4 : 1,
        alpha: 0.15 + Math.random() * 0.55,
        type: Math.random() < 0.2 ? 'spark' : Math.random() < 0.4 ? 'debris' : 'star',
      })
    }
    particlesRef.current = particles

    // Build cached mineral surface texture
    const tex = document.createElement('canvas')
    tex.width = 256; tex.height = 256
    const tc = tex.getContext('2d')
    if (tc) {
      // Deep mineral base
      tc.fillStyle = '#060f1a'
      tc.fillRect(0, 0, 256, 256)

      // Fine noise with muted cold tones
      const imgData = tc.createImageData(256, 256)
      for (let i = 0; i < imgData.data.length; i += 4) {
        const v = Math.floor(Math.random() * 22)
        imgData.data[i] = v
        imgData.data[i + 1] = v + 8
        imgData.data[i + 2] = v + 18
        imgData.data[i + 3] = 50
      }
      tc.putImageData(imgData, 0, 0)

      // Craters — muted, subtle
      tc.fillStyle = 'rgba(255, 255, 255, 0.025)'
      tc.strokeStyle = 'rgba(0, 0, 0, 0.3)'
      for (let i = 0; i < 20; i++) {
        const cx = Math.random() * 256, cy = Math.random() * 256, r = 3 + Math.random() * 14
        tc.beginPath(); tc.arc(cx, cy, r, 0, Math.PI * 2); tc.fill()
        tc.beginPath(); tc.arc(cx + 1, cy + 1, r, Math.PI * 0.7, Math.PI * 1.8); tc.stroke()
      }

      // Icy fracture lines
      tc.strokeStyle = 'rgba(80, 200, 230, 0.10)'
      tc.lineWidth = 0.7
      for (let i = 0; i < 10; i++) {
        tc.beginPath()
        tc.moveTo(Math.random() * 256, Math.random() * 256)
        for (let j = 0; j < 5; j++) tc.lineTo(Math.random() * 256, Math.random() * 256)
        tc.stroke()
      }
    }
    surfaceRef.current = tex

    // Mouse listener
    const onMove = (ev: MouseEvent) => {
      mouseRef.current.targetX = (ev.clientX / window.innerWidth) * 2 - 1
      mouseRef.current.targetY = (ev.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  // ── Canvas + RenderScheduler ──
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const onResize = () => {
      const r = canvas.getBoundingClientRect()
      canvas.width = r.width * devicePixelRatio
      canvas.height = r.height * devicePixelRatio
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
    }
    onResize()
    window.addEventListener('resize', onResize)

    // 3D projection
    const project = (r: number, theta: number, pitch: number, roll: number): Vector3D => {
      const lx = r * Math.cos(theta), ly = r * Math.sin(theta)
      const y1 = ly * Math.cos(pitch), z1 = ly * Math.sin(pitch)
      return { x: lx * Math.cos(roll) - y1 * Math.sin(roll), y: lx * Math.sin(roll) + y1 * Math.cos(roll), z: z1 }
    }

    // Delayed value lookup from history buffer
    const getDelayed = (delayMs: number, field: 'amp' | 'orb'): number => {
      const hist = historyRef.current
      if (hist.length === 0) return 0
      const target = performance.now() - delayMs
      // Walk backwards to find the entry closest to `target`
      for (let i = hist.length - 1; i >= 0; i--) {
        if (hist[i].time <= target) return hist[i][field]
      }
      return hist[0][field]
    }

    RenderScheduler.subscribe('ceres-orb-canvas', (time) => {
      const w = canvas.width / devicePixelRatio
      const h = canvas.height / devicePixelRatio
      const centerX = w / 2, centerY = h / 2
      const now = performance.now()
      const st = stateRef.current
      const amp = ampRef.current

      ctx.clearRect(0, 0, w, h)

      // ════════════════════════════════════════════
      // 1. ENERGY STATE LERPS
      // ════════════════════════════════════════════
      const tgt = stateTargets[st] || stateTargets.IDLE
      const ptgt = plasmaTargets[st] || plasmaTargets.IDLE
      const isInterrupt = st === 'INTERRUPTING'
      const lerpRate = isInterrupt ? 0.35 : 0.04

      const e = energyRef.current
      e.orb += (tgt.orb - e.orb) * lerpRate
      e.env += (tgt.env - e.env) * lerpRate
      e.res += (tgt.res - e.res) * lerpRate
      e.focus += (tgt.focus - e.focus) * lerpRate
      e.plasmaFlow += (ptgt.flow - e.plasmaFlow) * (isInterrupt ? 0.5 : 0.06)
      e.plasmaPulse += (ptgt.pulse - e.plasmaPulse) * (isInterrupt ? 0.5 : 0.06)

      // Scale
      const tgtScale = isInterrupt ? 0.72 : st === 'LISTENING' ? 0.96
        : st === 'THINKING' ? 0.92 : 1.0  // thinking compresses shell inward
      e.scale += (tgtScale - e.scale) * (isInterrupt ? 0.4 : 0.05)

      // ════════════════════════════════════════════
      // 2. RESONANCE MEMORY
      // ════════════════════════════════════════════
      if (isInterrupt) {
        e.resonanceMemory = 0  // kill instantly
      } else {
        e.resonanceMemory = Math.max(e.resonanceMemory, amp * e.res)
        e.resonanceMemory *= 0.982  // ~2.5s half-life decay
      }
      const resMem = e.resonanceMemory

      // ════════════════════════════════════════════
      // 3. HISTORY BUFFER for causal propagation
      // ════════════════════════════════════════════
      historyRef.current.push({ time: now, amp, orb: e.orb })
      // Purge entries older than 300ms
      while (historyRef.current.length > 1 && now - historyRef.current[0].time > 300) {
        historyRef.current.shift()
      }

      // Delayed reads
      const ampGlow = getDelayed(60, 'amp')     // inner glow reacts 60ms late
      const ampShell = getDelayed(120, 'amp')    // shell reacts 120ms late
      const ampRings = getDelayed(180, 'amp')    // rings react 180ms late
      const orbGlow = getDelayed(60, 'orb')
      const orbShell = getDelayed(120, 'orb')
      const orbRings = getDelayed(180, 'orb')

      // ════════════════════════════════════════════
      // 4. PLANETARY INERTIA PARALLAX
      // ════════════════════════════════════════════
      const m = mouseRef.current
      m.x += (m.targetX - m.x) * 0.06
      m.y += (m.targetY - m.y) * 0.06

      // Inner core: heavy, gravitationally anchored (factor 1.2, LERP 0.05)
      const ic = innerCoreRef.current
      ic.x += (m.x * 1.2 - ic.x) * 0.05
      ic.y += (m.y * 1.2 - ic.y) * 0.05

      // Outer shell: gaseous, atmospheric, delayed (factor 2.2, LERP 0.03)
      const os = outerShellRef.current
      os.x += (m.x * 2.2 - os.x) * 0.03
      os.y += (m.y * 2.2 - os.y) * 0.03

      // ════════════════════════════════════════════
      // 5. SYSTEMIC BREATHING
      // ════════════════════════════════════════════
      const breathFreq = st === 'THINKING' ? 0.0014 : 0.0005
      const breath = Math.sin(time * breathFreq)
      const breathAmt = 1.0 - e.focus * 0.4  // less breathing when focused

      const driftY = breath * 4.0 * breathAmt
      const breathScale = 1.0 + breath * 0.012 * breathAmt
      const breathGlow = 1.0 + breath * 0.08 * breathAmt           // core glow fluctuation
      const breathPlasmaSlowdown = 1.0 - breath * 0.15 * breathAmt // veins slow at breath peak
      const breathShellExpand = 1.0 + breath * 0.02 * breathAmt    // shell expands with breath
      const breathRingRelax = breath * 3.0 * breathAmt              // ring radius relaxation px
      const breathParticleDrift = breath * 1.5 * breathAmt          // vertical particle drift px

      // ════════════════════════════════════════════
      // 6. LOW-FREQUENCY PLANETARY DRIFT
      // ════════════════════════════════════════════
      const d = driftRef.current
      d.shellAngle = Math.sin(time * 0.00012) * 0.008
      d.coreOffX = Math.sin(time * 0.00009) * 1.2
      d.coreOffY = Math.cos(time * 0.00011) * 0.9
      d.ringTilt = Math.sin(time * 0.00015) * 0.6

      // ════════════════════════════════════════════
      // 7. COMPUTE COORDINATES
      // ════════════════════════════════════════════
      const activeScale = e.scale * breathScale
      const planetR = 78 * activeScale

      // Core center (heavy, anchored)
      const coreX = centerX + ic.x + d.coreOffX
      const coreY = centerY + ic.y + d.coreOffY + driftY

      // Shell center (gaseous, lagging)
      const shellX = centerX + os.x + d.coreOffX * 0.7
      const shellY = centerY + os.y + d.coreOffY * 0.7 + driftY

      // ════════════════════════════════════════════
      // 8. RING PROJECTION (eccentric, wobbling, magnetically tensioned)
      // ════════════════════════════════════════════
      // Magnetic tension: thinking/speaking tightens rings, interrupt collapses
      const tension = st === 'THINKING' ? 0.94 : st === 'SPEAKING' ? (0.96 + amp * 0.04)
        : isInterrupt ? 0.82 : 1.0

      const ringConfigs = [
        { radius: planetR * 1.45 * tension, pitch: 70, roll: 15 + d.ringTilt, speed: 0.00135, color: 'rgba(90, 210, 255, 0.35)', width: 1.0, eccentX: 1.05, eccentY: 0.95, wobbleAmp: 2.0, wobbleFreq: 3.0 },
        { radius: planetR * 1.75 * tension, pitch: 62, roll: -28 + d.ringTilt * 0.7, speed: -0.00105, color: 'rgba(55, 170, 245, 0.25)', width: 0.8, eccentX: 0.96, eccentY: 1.04, wobbleAmp: 1.5, wobbleFreq: 4.0 },
        { radius: planetR * 2.05 * tension, pitch: 55, roll: 38 + d.ringTilt * 0.5, speed: 0.00084, color: 'rgba(80, 220, 245, 0.20)', width: 0.9, eccentX: 1.02, eccentY: 0.98, wobbleAmp: 2.5, wobbleFreq: 2.5 },
        { radius: planetR * 2.35 * tension, pitch: 48, roll: -18 + d.ringTilt * 0.4, speed: -0.00066, color: 'rgba(40, 160, 230, 0.15)', width: 0.7, eccentX: 0.98, eccentY: 1.02, wobbleAmp: 1.2, wobbleFreq: 5.0 },
      ]

      // Resonance ring (additive, only when speaking energy exists)
      const showResRing = e.res > 0.04 || resMem > 0.02

      type Seg = { p1: Vector3D; p2: Vector3D; z: number; theta: number; color: string; width: number; isRes: boolean }
      const allSegs: Seg[] = []
      const steps = 80

      for (const rc of ringConfigs) {
        // Change orientation of the rings dynamically based on the mouse tracker (m.x and m.y)
        const pitchRad = (rc.pitch + m.y * 14.0) * Math.PI / 180
        const rollRad = (rc.roll + m.x * 18.0) * Math.PI / 180
        const rotationOffset = time * rc.speed // Revolving rotation over time
        for (let i = 0; i < steps; i++) {
          const t1 = (i / steps) * Math.PI * 2 + rotationOffset
          const t2 = ((i + 1) / steps) * Math.PI * 2 + rotationOffset

          // Eccentric wobble
          const r1 = rc.radius + Math.sin(t1 * rc.wobbleFreq + time * 0.0004) * rc.wobbleAmp + breathRingRelax
          const r2 = rc.radius + Math.sin(t2 * rc.wobbleFreq + time * 0.0004) * rc.wobbleAmp + breathRingRelax

          // Apply eccentricity to the local-space coords before projection
          const p1 = project(r1, t1, pitchRad, rollRad)
          const p2 = project(r2, t2, pitchRad, rollRad)
          p1.x *= rc.eccentX; p1.y *= rc.eccentY
          p2.x *= rc.eccentX; p2.y *= rc.eccentY

          allSegs.push({ p1, p2, z: (p1.z + p2.z) / 2, theta: t1, color: rc.color, width: rc.width, isRes: false })
        }
      }

      // Speaking resonance ring
      if (showResRing) {
        const resR = planetR * (1.30 + ampRings * 0.20 + resMem * 0.12)
        const resPitch = (66 + m.y * 14.0) * Math.PI / 180
        const resRoll = (18 + d.ringTilt * 0.5 + m.x * 18.0) * Math.PI / 180
        const resRotationOffset = time * 0.0015 // Revolving resonance ring
        for (let i = 0; i < steps; i++) {
          const t1 = (i / steps) * Math.PI * 2 + resRotationOffset
          const t2 = ((i + 1) / steps) * Math.PI * 2 + resRotationOffset
          const p1 = project(resR, t1, resPitch, resRoll)
          const p2 = project(resR, t2, resPitch, resRoll)
          allSegs.push({ p1, p2, z: (p1.z + p2.z) / 2, theta: t1, color: 'rgba(0, 225, 175, 0.7)', width: 1.1, isRes: true })
        }
      }

      // ── Particle projection ──
      const isThinking = st === 'THINKING'
      const particleMotionDamper = isThinking ? 0.65 : 1.0  // thinking = pressure silence reduces particle motion

      const projParticles = particlesRef.current.map(p => {
        p.theta += p.speed * (1.0 + e.orb * 1.2) * particleMotionDamper
        const curR = p.orbitRadius * (1.0 - e.focus * 0.25) * tension
        // Tilt particle orbits based on mouse tracker for unified revolving feel
        const pitchRad = p.pitch + m.y * 0.22
        const rollRad = p.roll + m.x * 0.28
        const pt = project(curR, p.theta, pitchRad, rollRad)
        return { pt, p }
      })

      // ═══════════════════════════════════════════════
      // DRAW HELPER: ring segment with gaps, depth fade, parallax
      // ═══════════════════════════════════════════════
      const drawSeg = (seg: Seg, orbE: number) => {
        // Multi-frequency gap filter for organic broken dust
        if (!seg.isRes) {
          const g1 = Math.sin(seg.theta * 4.0 + time * 0.0008)
          const g2 = Math.sin(seg.theta * 7.3 + time * 0.0003)
          if (g1 * g2 < -0.42) return  // organic gaps
        }
        // Ring parallax: depth-based 3D shift centered on the core (revolves tightly)
        const rPx = seg.z * m.x * 0.08
        const rPy = seg.z * m.y * 0.08
        // Depth-based opacity
        const depthAlpha = 0.3 + 0.7 * ((seg.z + planetR * 2) / (planetR * 4))
        const ringAmp = seg.isRes ? (ampRings * 0.5 + resMem * 0.4) : 0

        ctx.beginPath()
        ctx.moveTo(coreX + seg.p1.x + rPx, coreY + seg.p1.y + rPy)
        ctx.lineTo(coreX + seg.p2.x + rPx, coreY + seg.p2.y + rPy)
        ctx.strokeStyle = seg.color
        ctx.lineWidth = seg.width + ringAmp * 0.6

        const prev = ctx.globalAlpha
        ctx.globalAlpha = prev * Math.max(0, Math.min(1, depthAlpha)) * (seg.isRes ? (e.res * 0.6 + resMem * 0.4) : (0.45 + orbE * 0.25))
        ctx.stroke()
        ctx.globalAlpha = prev
      }

      // ═══════════════════════════════════════════════
      //  PASS 1: BACK LAYERS (z < 0)
      // ═══════════════════════════════════════════════

      // Back particles
      for (const { pt, p } of projParticles) {
        if (pt.z >= 0) continue
        const px = coreX + pt.x + pt.z * m.x * 0.08
        const py = coreY + pt.y + pt.z * m.y * 0.08 + breathParticleDrift
        ctx.beginPath()
        ctx.arc(px, py, p.size, 0, Math.PI * 2)
        const depthA = p.alpha * (0.25 + 0.75 * ((pt.z + 180) / 360))
        ctx.fillStyle = p.type === 'spark' ? `rgba(0, 210, 200, ${depthA})` : `rgba(100, 200, 240, ${depthA * 0.7})`
        ctx.fill()
      }

      // Back ring segments
      ctx.globalAlpha = 1.0
      for (const seg of allSegs) {
        if (seg.z < 0) drawSeg(seg, orbRings)
      }
      ctx.globalAlpha = 1.0

      // ═══════════════════════════════════════════════
      //  PASS 2: PLANETARY BODY + INTERIOR + ATMOSPHERE
      // ═══════════════════════════════════════════════

      // ── Subsurface scattering / Internal Glow (delayed 60ms) ──
      const glowI = (0.28 + orbGlow * 0.35 + ampGlow * 0.3) * breathGlow
      // Cap thinking glow to prevent overexposure
      const glowCapped = isThinking ? Math.min(glowI, 0.45) : glowI

      const glowGrad = ctx.createRadialGradient(coreX, coreY, planetR * 0.15, coreX, coreY, planetR * 1.35)
      glowGrad.addColorStop(0, `rgba(0, 160, 235, ${0.55 * glowCapped})`)      // brighter center
      glowGrad.addColorStop(0.35, `rgba(0, 110, 210, ${0.25 * glowCapped})`)
      glowGrad.addColorStop(0.7, `rgba(0, 70, 150, ${0.08 * glowCapped})`)
      glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')

      ctx.fillStyle = glowGrad
      ctx.beginPath()
      ctx.arc(coreX, coreY, planetR * 1.35, 0, Math.PI * 2)
      ctx.fill()

      // ── Planetary Body (clipping) ──
      ctx.save()
      ctx.beginPath()
      ctx.arc(coreX, coreY, planetR, 0, Math.PI * 2)
      ctx.clip()

      // Cached mineral texture (slow tectonic rotation)
      if (surfaceRef.current) {
        ctx.save()
        ctx.translate(coreX, coreY)
        ctx.rotate(time * 0.000022 + d.shellAngle)
        ctx.drawImage(surfaceRef.current, -planetR, -planetR, planetR * 2, planetR * 2)
        ctx.restore()
      }

      // Spherical shading: centered lighting with icy translucency
      const shade = ctx.createRadialGradient(
        coreX, coreY, planetR * 0.08,
        coreX, coreY, planetR
      )
      shade.addColorStop(0, 'rgba(210, 245, 255, 0.50)')   // brighter center highlight
      shade.addColorStop(0.2, 'rgba(60, 110, 160, 0.22)')    // subsurface scatter zone
      shade.addColorStop(0.55, 'rgba(10, 28, 50, 0.55)')     // deep mineral shadow
      shade.addColorStop(1, 'rgba(2, 5, 12, 0.96)')         // dark limb

      ctx.fillStyle = shade
      ctx.beginPath()
      ctx.arc(coreX, coreY, planetR, 0, Math.PI * 2)
      ctx.fill()

      ctx.restore() // end planet clip

      // ── Atmospheric Shell (delayed 120ms, uses shellX/shellY for gaseous lag) ──
      // Dynamic uniform deformation (pulsation) during LISTENING and SPEAKING
      let uniformPulse = 0
      if (st === 'LISTENING') {
        // High frequency rhythmic breathing & responsive mic expansion
        uniformPulse = ampShell * 22.0 + Math.sin(time * 0.007) * 4.5
      } else if (st === 'SPEAKING') {
        // Smooth flowing vocal pulsation
        uniformPulse = ampShell * 28.0 + Math.sin(time * 0.009) * 6.0
      }
      
      const baseAtmosR = planetR * 1.18 * breathShellExpand
      const dynamicAtmosR = baseAtmosR + uniformPulse
      
      // Thinking: compressed inward (8% reduction already via scale), cap atmosphere brightness
      const atmosAlpha = isThinking
        ? Math.min(0.25, 0.15 + orbShell * 0.25)     // restrained
        : 0.28 + orbShell * 0.55 + ampShell * 0.35 + resMem * 0.22  // normal

      ctx.save()
      ctx.beginPath()
      const aSt = 90
      for (let i = 0; i < aSt; i++) {
        const angle = (i / aSt) * Math.PI * 2
        // Spatial wave configuration - smoother, lower frequency wave for listening/speaking to look uniform
        const distFreq = (st === 'LISTENING' || st === 'SPEAKING') ? 3.0 : isThinking ? 8.0 : 5.0
        const speedMult = st === 'LISTENING' ? 0.006 : st === 'SPEAKING' ? 0.008 : 0.003
        
        // Fluid, reactive wave ripple
        const waveVal = Math.sin(angle * distFreq - time * speedMult) * (1.2 + ampShell * 8.5 + resMem * 4.0) * e.focus
        const r = dynamicAtmosR + waveVal
        
        const ax = shellX + r * Math.cos(angle), ay = shellY + r * Math.sin(angle)
        i === 0 ? ctx.moveTo(ax, ay) : ctx.lineTo(ax, ay)
      }
      ctx.closePath()

      // Gradient adapts dynamically to the uniform expansion/contraction
      const shellGrad = ctx.createRadialGradient(shellX, shellY, planetR * 0.92, shellX, shellY, dynamicAtmosR * 1.06)
      shellGrad.addColorStop(0, 'rgba(0, 0, 0, 0)')
      shellGrad.addColorStop(0.12, `rgba(80, 205, 255, ${0.42 * atmosAlpha})`)
      shellGrad.addColorStop(0.6, `rgba(0, 150, 235, ${0.18 * atmosAlpha})`)
      shellGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')
      ctx.fillStyle = shellGrad
      ctx.fill()

      // Refraction border
      ctx.strokeStyle = `rgba(120, 220, 245, ${Math.min(0.6, 0.18 + orbShell * 0.28 + ampShell * 0.25 + resMem * 0.12)})`
      ctx.lineWidth = 0.9
      ctx.stroke()
      ctx.restore()

      // ── Speaking Resonance Pulse Overlay (ADDITIVE — never replaces the orb) ──
      if (st === 'SPEAKING' || resMem > 0.01) {
        ctx.save()
        ctx.globalCompositeOperation = 'screen'
        const pulseIntensity = amp * 0.4 + resMem * 0.35
        const pg = ctx.createRadialGradient(coreX, coreY, planetR * 0.5, coreX, coreY, planetR * 1.3)
        pg.addColorStop(0, `rgba(80, 210, 240, ${pulseIntensity * 0.3})`)
        pg.addColorStop(0.4, `rgba(0, 150, 220, ${pulseIntensity * 0.15})`)
        pg.addColorStop(1, 'rgba(0, 0, 0, 0)')
        ctx.fillStyle = pg
        ctx.beginPath()
        ctx.arc(coreX, coreY, planetR * 1.3, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
      }


      // ── Inner Core Nucleus ──
      // A tight, intensely bright point at the gravitational center
      {
        const coreEnergy = 0.3 + e.orb * 0.5 + ampGlow * 0.4
        const corePulse = 1.0 + Math.sin(time * 0.004 + 0.8) * 0.12 * (1 - e.focus * 0.5)
        const nucR = planetR * 0.18 * corePulse

        ctx.save()
        ctx.globalCompositeOperation = 'screen'

        // Deep heat core — innermost
        const heatGrad = ctx.createRadialGradient(coreX, coreY, 0, coreX, coreY, nucR * 0.5)
        heatGrad.addColorStop(0, `rgba(220, 248, 255, ${Math.min(0.95, coreEnergy * 0.9)})`)
        heatGrad.addColorStop(0.4, `rgba(80, 200, 245, ${coreEnergy * 0.5})`)
        heatGrad.addColorStop(1, 'rgba(0, 100, 200, 0)')
        ctx.fillStyle = heatGrad
        ctx.beginPath()
        ctx.arc(coreX, coreY, nucR * 0.5, 0, Math.PI * 2)
        ctx.fill()

        // Outer corona ring
        const coronaGrad = ctx.createRadialGradient(coreX, coreY, nucR * 0.3, coreX, coreY, nucR * 1.5)
        coronaGrad.addColorStop(0, `rgba(60, 180, 240, ${coreEnergy * 0.4})`)
        coronaGrad.addColorStop(0.5, `rgba(0, 120, 210, ${coreEnergy * 0.15})`)
        coronaGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')
        ctx.fillStyle = coronaGrad
        ctx.beginPath()
        ctx.arc(coreX, coreY, nucR * 1.5, 0, Math.PI * 2)
        ctx.fill()

        ctx.restore()
      }

      // ─── Edge Scattering (SPEAKING/THINKING only, capped for thinking) ──
      if (st === 'SPEAKING' || st === 'THINKING' || resMem > 0.02) {
        ctx.save()
        ctx.globalCompositeOperation = 'screen'
        const scatOpacity = isThinking
          ? Math.min(0.15, 0.08 + e.orb * 0.1)   // restrained for thinking
          : (0.12 + amp * 0.45 + resMem * 0.2)     // speaking: audio reactive + memory
        const sg = ctx.createRadialGradient(coreX, coreY, planetR * 0.96, coreX, coreY, planetR * 1.45)
        sg.addColorStop(0, `rgba(140, 230, 245, ${scatOpacity})`)
        sg.addColorStop(0.25, `rgba(0, 140, 220, ${scatOpacity * 0.4})`)
        sg.addColorStop(1, 'rgba(0, 0, 0, 0)')
        ctx.fillStyle = sg
        ctx.beginPath()
        ctx.arc(coreX, coreY, planetR * 1.45, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
      }

      // ═══════════════════════════════════════════════
      //  PASS 3: FRONT LAYERS (z >= 0)
      // ═══════════════════════════════════════════════

      ctx.globalAlpha = 1.0
      for (const seg of allSegs) {
        if (seg.z >= 0) drawSeg(seg, orbRings)
      }
      ctx.globalAlpha = 1.0

      // Front particles
      for (const { pt, p } of projParticles) {
        if (pt.z < 0) continue
        const px = coreX + pt.x + pt.z * m.x * 0.08
        const py = coreY + pt.y + pt.z * m.y * 0.08 + breathParticleDrift
        ctx.beginPath()
        ctx.arc(px, py, p.size, 0, Math.PI * 2)
        const depthA = p.alpha * (0.25 + 0.75 * ((pt.z + 180) / 360))
        ctx.fillStyle = p.type === 'spark' ? `rgba(0, 210, 200, ${depthA})` : `rgba(100, 200, 240, ${depthA * 0.7})`
        ctx.fill()
      }
    })

    return () => {
      window.removeEventListener('resize', onResize)
      RenderScheduler.unsubscribe('ceres-orb-canvas')
    }
  }, []) // Empty deps — reads via refs, no React rerenders

  const isSpeaking = state === 'SPEAKING'
  const isInterrupting = state === 'INTERRUPTING'

  return (
    <div
      className={`ceres-entity state-${state.toLowerCase()}`}
      data-entry={entryEffect ?? 'none'}
      onClick={() => isSpeaking && onInterrupt()}
      style={{
        animation: 'none',
        cursor: isSpeaking ? 'pointer' : 'default',
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          width: '100%',
          height: '100%',
          display: 'block',
          filter: `drop-shadow(0 0 ${20 + visualIntensity * 30}px rgba(0, 180, 245, ${0.15 + visualIntensity * 0.25}))`,
          transition: 'filter 1.2s ease',
        }}
      />
    </div>
  )
}
