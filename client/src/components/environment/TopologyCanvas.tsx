import { useEffect, useRef } from 'react'
import type { OrbState } from '../../core/state/ceresTypes'
import { RenderScheduler } from '../../core/RenderScheduler'

interface Node {
  x: number; y: number; vx: number; vy: number; phase: number; lit: number
}

interface Wave {
  radius: number; speed: number; max: number; strength: number
}

// Environment target energies — deliberately LOW for cinematic silence
const targets: Record<OrbState, number> = {
  BOOTING: 0.08,
  AUTH: 0.10,
  IDLE: 0.08,
  LISTENING: 0.20,
  THINKING: 0.14,       // pressure silence — environment dims during thinking
  SPEAKING: 0.32,
  INTERRUPTING: 0.00,   // hard freeze
  ERROR: 0.22,
}

export function TopologyCanvas({ state, visualIntensity, audioAmplitude }: {
  state: OrbState
  visualIntensity: number
  audioAmplitude: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef = useRef(state)
  const visualRef = useRef(visualIntensity)
  const audioRef = useRef(audioAmplitude)
  const nodesRef = useRef<Node[]>([])
  const wavesRef = useRef<Wave[]>([])
  const intensityRef = useRef(targets[state])
  const waveClockRef = useRef(0)

  // 260ms propagation delay buffer (environment reacts last)
  const delayMs = 260
  const targetHistoryRef = useRef<{ time: number; val: number; amp: number }[]>([])

  // Resonance afterwave memory (lingers ~2.5s after speech)
  const resMemRef = useRef(0)

  // Mouse parallax (slowest layer — furthest depth)
  const mouseRef = useRef({ x: 0, y: 0, targetX: 0, targetY: 0 })

  useEffect(() => { stateRef.current = state }, [state])
  useEffect(() => { visualRef.current = visualIntensity }, [visualIntensity])
  useEffect(() => { audioRef.current = audioAmplitude }, [audioAmplitude])

  useEffect(() => {
    // Sparse node field — cinematic restraint
    nodesRef.current = Array.from({ length: 20 }, () => ({
      x: Math.random(), y: Math.random(),
      vx: (Math.random() - 0.5) * 0.000035,
      vy: (Math.random() - 0.5) * 0.000035,
      phase: Math.random() * Math.PI * 2,
      lit: 0,
    }))

    const onMove = (ev: MouseEvent) => {
      mouseRef.current.targetX = (ev.clientX / window.innerWidth) * 2 - 1
      mouseRef.current.targetY = (ev.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      canvas.width = window.innerWidth * devicePixelRatio
      canvas.height = window.innerHeight * devicePixelRatio
      canvas.style.width = `${window.innerWidth}px`
      canvas.style.height = `${window.innerHeight}px`
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    RenderScheduler.subscribe('ceres-topology-canvas', (time) => {
      const width = window.innerWidth
      const height = window.innerHeight
      const cx = width / 2, cy = height / 2
      const stateNow = stateRef.current
      const now = performance.now()
      const isThinking = stateNow === 'THINKING'
      const isInterrupt = stateNow === 'INTERRUPTING'

      // ── Resonance Memory (afterwaves from speech) ──
      if (isInterrupt) {
        resMemRef.current = 0
      } else {
        resMemRef.current = Math.max(resMemRef.current, audioRef.current * 0.6)
        resMemRef.current *= 0.984  // ~2.5s decay
      }
      const resMem = resMemRef.current

      // ── Delayed Propagation (260ms buffer) ──
      const rawTarget = Math.max(targets[stateNow], visualRef.current * 0.4)
      targetHistoryRef.current.push({ time: now, val: rawTarget, amp: audioRef.current })

      while (targetHistoryRef.current.length > 1 && now - targetHistoryRef.current[0].time > delayMs) {
        targetHistoryRef.current.shift()
      }

      const delayedTarget = targetHistoryRef.current[0].val
      const delayedAmp = targetHistoryRef.current[0].amp
      intensityRef.current += (delayedTarget - intensityRef.current) * (delayedTarget > intensityRef.current ? 0.02 : 0.004)
      const intensity = intensityRef.current

      ctx.clearRect(0, 0, width, height)
      waveClockRef.current += 1

      // ── Background parallax (slowest layer: 0.5px shift, LERP 0.025) ──
      const m = mouseRef.current
      m.x += (m.targetX - m.x) * 0.025
      m.y += (m.targetY - m.y) * 0.025
      const px = m.x * 0.5, py = m.y * 0.5

      // ── Thinking Pressure Silence: reduce wave emission rate drastically ──
      if (isThinking && waveClockRef.current % 110 === 0) {
        wavesRef.current.push({ radius: 20, speed: 0.9, max: Math.hypot(cx, cy) * 1.1, strength: 0.45 })
      }
      // Speaking + afterwaves from resonance memory
      if ((stateNow === 'SPEAKING' || resMem > 0.03) && waveClockRef.current % 52 === 0) {
        const str = stateNow === 'SPEAKING'
          ? 0.35 + delayedAmp * 0.65
          : resMem * 0.6  // faint residual afterwaves
        wavesRef.current.push({ radius: 25, speed: 0.8 + delayedAmp * 1.2, max: Math.hypot(cx, cy) * 0.82, strength: str })
      }
      if (isInterrupt) {
        wavesRef.current.length = 0  // hard kill
      }

      wavesRef.current = wavesRef.current.filter(w => w.radius < w.max)
      for (const wave of wavesRef.current) {
        wave.radius += wave.speed
        const fade = Math.max(0, 1 - wave.radius / wave.max)
        ctx.beginPath()
        ctx.arc(cx + px, cy + py, wave.radius, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(80, 200, 240, ${fade * intensity * 0.14 * wave.strength})`
        ctx.lineWidth = 0.7
        ctx.stroke()

        for (const node of nodesRef.current) {
          const dist = Math.hypot(node.x * width - cx, node.y * height - cy)
          if (Math.abs(dist - wave.radius) < 40) {
            node.lit = Math.min(1, node.lit + 0.3 * wave.strength)
          }
        }
      }

      // ── Node motion (thinking: reduce by 35%) ──
      const motionDamper = isThinking ? 0.65 : 1.0
      for (const node of nodesRef.current) {
        const vxEff = node.vx * motionDamper
        const vyEff = node.vy * motionDamper
        if (stateNow === 'LISTENING') {
          node.x += vxEff + (0.5 - node.x) * 0.00005
          node.y += vyEff + (0.5 - node.y) * 0.00005
        } else {
          node.x += vxEff
          node.y += vyEff
        }
        if (node.x < -0.05) node.x = 1.05
        if (node.x > 1.05) node.x = -0.05
        if (node.y < -0.05) node.y = 1.05
        if (node.y > 1.05) node.y = -0.05
        node.lit *= 0.95
      }

      // ── Mesh lines (max opacity 0.08 for cinematic silence) ──
      const nodes = nodesRef.current
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j]
          const ax = a.x * width + px, ay = a.y * height + py
          const bx = b.x * width + px, by = b.y * height + py
          const dist = Math.hypot(ax - bx, ay - by)
          const maxDist = Math.min(width, height) * 0.20
          if (dist > maxDist) continue
          const alpha = (1 - dist / maxDist) * intensity * 0.08 * (1 + (a.lit + b.lit) * 0.7)
          ctx.beginPath()
          ctx.moveTo(ax, ay)
          ctx.lineTo(bx, by)
          ctx.strokeStyle = `rgba(60, 175, 215, ${alpha})`
          ctx.lineWidth = 0.45
          ctx.stroke()
        }
      }

      // ── Node dots ──
      for (const node of nodes) {
        const pulse = Math.sin(time * 0.00045 + node.phase) * 0.5 + 0.5
        const radius = 0.9 + pulse * 0.7 + node.lit * 2.2
        ctx.beginPath()
        ctx.arc(node.x * width + px, node.y * height + py, radius, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(90, 210, 240, ${(0.09 + pulse * 0.12 + node.lit * 0.4) * intensity})`
        ctx.fill()
      }
    })

    return () => {
      window.removeEventListener('resize', resize)
      RenderScheduler.unsubscribe('ceres-topology-canvas')
    }
  }, [])

  return <canvas className="topology-canvas" ref={canvasRef} />
}
