import { useEffect, useMemo, useRef, useState } from 'react'
import { CeresOrb } from './orb/CeresOrb'
import { EnvironmentField } from './environment/EnvironmentField'
import { CeresHud } from './hud/CeresHud'
import { useCeresStore } from '../store/useCeresStore'
import type { OrbState } from '../core/state/ceresTypes'
import { RenderScheduler } from '../core/RenderScheduler'

const baseIntensity: Record<OrbState, number> = {
  BOOTING: 0.18,
  AUTH: 0.2,
  IDLE: 0.16,
  LISTENING: 0.44,
  THINKING: 0.84,
  SPEAKING: 0.58,
  INTERRUPTING: 0.28,
  ERROR: 0.5,
}

// Below this delta the animation is visually settled, so we stop the loop.
const INTENSITY_EPSILON = 0.002

function useCinematicIntensity(state: OrbState, audioAmplitude: number) {
  const [value, setValue] = useState(baseIntensity[state])
  const targetRef = useRef(baseIntensity[state])
  const valueRef = useRef(value)
  const animatingRef = useRef(false)

  // Drives the easing loop, and — critically — SHUTS IT DOWN once converged.
  // The old version subscribed once on mount with [] deps and called setValue()
  // on every frame forever, so the whole orb tree re-rendered at 60fps even
  // when CERES was sitting idle doing nothing. That was the main source of the
  // UI feeling laggy.
  const ensureAnimating = () => {
    if (animatingRef.current) return
    animatingRef.current = true
    RenderScheduler.subscribe('cinematic-intensity', () => {
      const target = targetRef.current
      const current = valueRef.current
      const delta = target - current

      if (Math.abs(delta) < INTENSITY_EPSILON) {
        // Snap to target, emit once, then stop burning frames.
        if (current !== target) {
          valueRef.current = target
          setValue(target)
        }
        animatingRef.current = false
        RenderScheduler.unsubscribe('cinematic-intensity')
        return
      }

      const rate = delta > 0 ? 0.035 : 0.006
      const next = current + delta * rate
      valueRef.current = next
      setValue(next)
    })
  }

  useEffect(() => {
    targetRef.current = Math.max(baseIntensity[state], 0.2 + audioAmplitude * 0.72)
    if (Math.abs(targetRef.current - valueRef.current) >= INTENSITY_EPSILON) {
      ensureAnimating()
    }
  }, [state, audioAmplitude])

  useEffect(() => () => {
    animatingRef.current = false
    RenderScheduler.unsubscribe('cinematic-intensity')
  }, [])

  return value
}


export function JarvisOrb() {
  // Field-level selectors instead of `useCeresStore()` with no selector. The
  // bare call subscribed to the ENTIRE store, so every dispatch — including the
  // per-frame AUDIO_AMPLITUDE during speech — re-rendered this component and
  // its whole subtree (EnvironmentField, the 650-line CeresOrb, CeresHud).
  const orbState = useCeresStore(s => s.orbState)
  const audioAmplitude = useCeresStore(s => s.audioAmplitude)
  const entryEffect = useCeresStore(s => s.entryEffect)
  const isRecording = useCeresStore(s => s.isRecording)
  const connectionState = useCeresStore(s => s.connectionState)
  const stats = useCeresStore(s => s.stats)

  // Actions are stable identities on the store, so selecting them individually
  // never causes a re-render.
  const connect = useCeresStore(s => s.connect)
  const sendQuery = useCeresStore(s => s.sendQuery)
  const interrupt = useCeresStore(s => s.interrupt)
  const startRecording = useCeresStore(s => s.startRecording)
  const stopRecording = useCeresStore(s => s.stopRecording)
  const startWakeWord = useCeresStore(s => s.startWakeWord)
  const dispatch = useCeresStore(s => s.dispatch)

  const visualIntensity = useCinematicIntensity(orbState, audioAmplitude)
  const connected = connectionState === 'connected'

  useEffect(() => {
    connect()
    startWakeWord()

    const statsSocket = new WebSocket('ws://localhost:8000/ws/stats')
    statsSocket.onmessage = event => {
      try {
        dispatch({ type: 'STATS_UPDATE', stats: JSON.parse(event.data) })
      } catch {}
    }

    return () => {
      statsSocket.close()
    }
  }, [connect, dispatch, startWakeWord])

  const orbView = useMemo(() => ({
    state: orbState,
    visualIntensity,
    audioAmplitude,
    entryEffect,
  }), [orbState, visualIntensity, audioAmplitude, entryEffect])

  return (
    <main className="ceres-celestial-stage">
      <EnvironmentField
        state={orbView.state}
        visualIntensity={orbView.visualIntensity}
        audioAmplitude={orbView.audioAmplitude}
      />

      <section className="orb-stage" aria-label="CERES celestial intelligence">
        <CeresOrb
          state={orbView.state}
          visualIntensity={orbView.visualIntensity}
          audioAmplitude={orbView.audioAmplitude}
          entryEffect={orbView.entryEffect}
          onInterrupt={interrupt}
        />
      </section>

      <div className="idle-presence" style={{ opacity: orbState === 'IDLE' ? 1 : 0 }}>
        <div>{new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }).toUpperCase()}</div>
      </div>

      <CeresHud
        state={orbState}
        connected={connected}
        stats={stats}
        isRecording={isRecording}
        onSend={sendQuery}
        onMic={() => isRecording ? stopRecording() : startRecording()}
        onInterrupt={interrupt}
      />
    </main>
  )
}
