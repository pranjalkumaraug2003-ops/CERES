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

function useCinematicIntensity(state: OrbState, audioAmplitude: number) {
  const [value, setValue] = useState(baseIntensity[state])
  const targetRef = useRef(baseIntensity[state])
  const valueRef = useRef(value)

  useEffect(() => {
    targetRef.current = Math.max(baseIntensity[state], 0.2 + audioAmplitude * 0.72)
  }, [state, audioAmplitude])

  useEffect(() => {
    RenderScheduler.subscribe('cinematic-intensity', () => {
      const target = targetRef.current
      const current = valueRef.current
      const rate = target > current ? 0.035 : 0.006
      const next = current + (target - current) * rate
      valueRef.current = next
      setValue(next)
    })
    return () => RenderScheduler.unsubscribe('cinematic-intensity')
  }, [])

  return value
}


export function JarvisOrb() {
  const {
    orbState,
    audioAmplitude,
    entryEffect,
    isRecording,
    connectionState,
    stats,
    connect,
    sendQuery,
    interrupt,
    startRecording,
    stopRecording,
    startWakeWord,
    dispatch,
  } = useCeresStore()

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
