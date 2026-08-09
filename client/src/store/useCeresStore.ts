import { create } from 'zustand'
import { AudioEngine } from '../core/audio/AudioEngine'
import { WebSocketManager } from '../core/ws/WebSocketManager'
import { RecorderEngine } from '../core/voice/RecorderEngine'
import { WakeWordEngine } from '../core/wakeword/WakeWordEngine'
import { makeInteractionId, type CeresAction } from '../core/state/ceresEvents'
import { initialCeresState, reduceCeresState, type CeresDispatch } from '../core/state/ceresMachine'
import type { CeresState, PendingApproval } from '../core/state/ceresTypes'

interface CeresStore extends CeresState {
  dispatch: CeresDispatch
  connect: () => void
  disconnect: () => void
  sendQuery: (query: string, suppliedInteractionId?: string) => void
  interrupt: () => void
  startRecording: () => void
  stopRecording: () => void
  startWakeWord: () => void
  stopWakeWord: () => void
  approveAction: (action: 'approve' | 'deny') => Promise<void>
  clearEvents: () => void
  setPendingApproval: (approval: PendingApproval | null) => void
}

let wsManager: WebSocketManager | null = null
let audioEngine: AudioEngine | null = null
let recorderEngine: RecorderEngine | null = null
let wakeWordEngine: WakeWordEngine | null = null

function extractIds(event: any) {
  return {
    interactionId: event.interaction_id ?? event.data?.interaction_id ?? null,
    generationId: event.data?.gen_id ?? event.data?.generation_id ?? null,
  }
}

function ensureEngines(dispatch: CeresDispatch) {
  wsManager ??= new WebSocketManager(dispatch)
  audioEngine ??= new AudioEngine(dispatch)
  recorderEngine ??= new RecorderEngine(dispatch)
  wakeWordEngine ??= new WakeWordEngine(dispatch)
}

export const useCeresStore = create<CeresStore>((set, get) => {
  const dispatch: CeresDispatch = (action: CeresAction) => {
    if (action.type === 'STREAM_EVENT') {
      const event = action.event
      if (event.type === 'tts_start') {
        const ids = extractIds(event)
        audioEngine?.flushOnly()
        set(state => reduceCeresState(state, { type: 'TTS_START', ...ids }))
      }
      if (event.type === 'tts_chunk') {
        const audioBase64 = event.data?.audio_base64
        if (audioBase64) {
          const ids = extractIds(event)
          audioEngine?.enqueue({ audioBase64, ...ids })
        }
      }
    }
    // Auto-recover from WS_ERROR after 4s — prevents the orb from being
    // permanently stuck in ERROR state after a transient connection hiccup.
    if (action.type === 'WS_ERROR') {
      window.setTimeout(() => {
        const { orbState } = get()
        if (orbState === 'ERROR') {
          set(state => reduceCeresState(state, { type: 'FORCE_STATE', state: 'IDLE' }))
        }
      }, 4000)
    }
    set(state => reduceCeresState(state, action))
  }

  ensureEngines(dispatch)

  return {
    ...initialCeresState,
    dispatch,

    connect: () => {
      ensureEngines(dispatch)
      wsManager?.connect()
    },

    disconnect: () => {
      wsManager?.disconnect()
      dispatch({ type: 'WS_DISCONNECTED' })
    },

    sendQuery: (query: string, suppliedInteractionId?: string) => {
      const clean = query.trim()
      if (!clean) return
      const interactionId = suppliedInteractionId ?? makeInteractionId()
      const threadId = get().threadId
      audioEngine?.flushOnly()
      dispatch({ type: 'CLIENT_QUERY_START', query: clean, interactionId, threadId })
      wsManager?.sendQuery(clean, interactionId, threadId)
    },

    interrupt: () => {
      const { interactionId, threadId } = get()
      dispatch({ type: 'INTERRUPT_REQUESTED' })
      audioEngine?.flushOnly()
      wsManager?.interrupt(interactionId, threadId)
      window.setTimeout(() => dispatch({ type: 'INTERRUPT_COMPLETED' }), 120)
    },

    startRecording: () => {
      ensureEngines(dispatch)
      // If we're stuck in ERROR state (e.g. from a prior failed mic attempt),
      // reset to IDLE first so the state machine can accept RECORDER_STARTED.
      const currentState = get().orbState
      if (currentState === 'ERROR') {
        dispatch({ type: 'FORCE_STATE', state: 'IDLE' })
      }
      void recorderEngine?.start((text, interactionId) => get().sendQuery(text, interactionId))
    },

    stopRecording: () => recorderEngine?.stop(),

    startWakeWord: () => {
      ensureEngines(dispatch)
      wakeWordEngine?.start(
        () => get().startRecording(),
        () => get().interrupt(),
        () => get().orbState === 'SPEAKING',
        () => get().isRecording,
      )
    },

    stopWakeWord: () => wakeWordEngine?.stop(),

    approveAction: async (action: 'approve' | 'deny') => {
      const approval = get().pendingApproval
      if (!approval) return
      try {
        await fetch(`http://localhost:8000/api/resume/${approval.threadId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action }),
        })
      } finally {
        dispatch({ type: 'PENDING_APPROVAL', approval: null })
      }
    },

    clearEvents: () => dispatch({ type: 'CLEAR_EVENTS' }),
    setPendingApproval: approval => dispatch({ type: 'PENDING_APPROVAL', approval }),
  }
})
