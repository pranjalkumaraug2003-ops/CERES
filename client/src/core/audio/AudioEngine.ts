import type { CeresDispatch } from '../state/ceresMachine'
import { AudioQueue } from './AudioQueue'
import { RenderScheduler } from '../RenderScheduler'

interface AudioChunkInput {
  audioBase64: string
  interactionId?: string | null
  generationId?: string | null
}

export class AudioEngine {
  private queue = new AudioQueue()
  private dispatch: CeresDispatch
  private isLooping = false
  private activeInteractionId: string | null = null
  private activeGenerationId: string | null = null
  private lastAmplitudeAt = 0
  private lastAmplitude = -1

  constructor(dispatch: CeresDispatch) {
    this.dispatch = dispatch
  }

  enqueue({ audioBase64, interactionId = null, generationId = null }: AudioChunkInput) {
    const wasPlaying = this.queue.isPlaying
    this.activeInteractionId = interactionId
    this.activeGenerationId = generationId
    // F-1: reset() clears the _flushed flag from a prior interrupt; only needed
    // when starting a new session, not on every streaming chunk.
    if (!wasPlaying) {
      this.queue.reset()
    }
    this.dispatch({ type: 'AUDIO_CHUNK_RECEIVED', interactionId, generationId })
    // F-1: Only fire AUDIO_STARTED for the first chunk of a new playback session.
    // Firing it on every chunk was resetting the state-machine timer and locking
    // speech-state transitions indefinitely.
    if (!wasPlaying) {
      this.dispatch({ type: 'AUDIO_STARTED', interactionId, generationId })
    }
    this.startAmplitudeLoop()
    void this.queue.enqueue({ audioBase64, interactionId, generationId }, () => this.handleEnded())
  }

  interrupt() {
    this.queue.flush()
    this.stopAmplitudeLoop()
    this.dispatch({ type: 'AUDIO_AMPLITUDE', amplitude: 0 })
    this.dispatch({ type: 'INTERRUPT_COMPLETED' })
  }

  flushOnly() {
    this.queue.flush()
    this.stopAmplitudeLoop()
    this.dispatch({ type: 'AUDIO_AMPLITUDE', amplitude: 0 })
  }

  private handleEnded() {
    if (this.queue.isPlaying) return
    const interactionId = this.activeInteractionId
    const generationId = this.activeGenerationId
    this.stopAmplitudeLoop()
    this.dispatch({ type: 'AUDIO_FINISHED', interactionId, generationId })
  }

  private startAmplitudeLoop() {
    if (this.isLooping) return
    this.isLooping = true
    RenderScheduler.subscribe('audio-amplitude', () => {
      const amplitude = this.queue.getAmplitude()
      const now = performance.now()

      // Throttle to ~20Hz and ignore imperceptible changes. This used to
      // dispatch on every animation frame (60Hz), and each dispatch produced a
      // new store object that re-rendered every subscriber — 60 full re-renders
      // per second for the entire duration of every spoken reply. 20Hz is still
      // smoother than the eye resolves for a glow/pulse effect.
      if (now - this.lastAmplitudeAt < 50) return
      if (Math.abs(amplitude - this.lastAmplitude) < 0.01) return

      this.lastAmplitudeAt = now
      this.lastAmplitude = amplitude
      this.dispatch({ type: 'AUDIO_AMPLITUDE', amplitude })
    })
  }

  private stopAmplitudeLoop() {
    if (!this.isLooping) return
    this.isLooping = false
    // Reset the throttle baseline so the next playback session isn't
    // suppressed by a stale "unchanged amplitude" comparison.
    this.lastAmplitude = -1
    this.lastAmplitudeAt = 0
    RenderScheduler.unsubscribe('audio-amplitude')
  }
}

