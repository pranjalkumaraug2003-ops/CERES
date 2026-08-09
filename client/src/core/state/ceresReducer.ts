import type { CeresAction } from './ceresEvents'
import type { CeresState, OrbState } from './ceresTypes'
import { defaultStats } from './ceresTypes'

const LOCK_MS: Partial<Record<OrbState, number>> = {
  LISTENING: 220,
  THINKING: 260,
  SPEAKING: 220,
  INTERRUPTING: 90,
}

const stateEntryEffect: Record<OrbState, string | null> = {
  BOOTING: 'boot',
  AUTH: 'auth',
  IDLE: 'settle',
  LISTENING: 'converge',
  THINKING: 'propagate',
  SPEAKING: 'resonate',
  INTERRUPTING: 'collapse',
  ERROR: 'fracture',
}

const stateBaseIntensity: Record<OrbState, number> = {
  BOOTING: 0.18,
  AUTH: 0.22,
  IDLE: 0.16,
  LISTENING: 0.44,
  THINKING: 0.82,
  SPEAKING: 0.58,
  INTERRUPTING: 0.25,
  ERROR: 0.5,
}

export const initialCeresState: CeresState = {
  orbState: 'BOOTING',
  previousOrbState: 'BOOTING',
  stateEnteredAt: Date.now(),
  transitionLockUntil: 0,
  entryEffect: 'boot',
  interactionId: null,
  generationId: null,
  threadId: null,
  deadInteractionIds: [],
  visualIntensity: stateBaseIntensity.BOOTING,
  audioAmplitude: 0,
  isRecording: false,
  isPlaying: false,
  connectionState: 'disconnected',
  events: [],
  pendingApproval: null,
  stats: defaultStats,
  error: null,
}

function withState(state: CeresState, orbState: OrbState, extra: Partial<CeresState> = {}): CeresState {
  const now = Date.now()
  return {
    ...state,
    ...extra,
    previousOrbState: state.orbState,
    orbState,
    stateEnteredAt: now,
    transitionLockUntil: now + (LOCK_MS[orbState] ?? 0),
    entryEffect: stateEntryEffect[orbState],
    visualIntensity: Math.max(state.visualIntensity, stateBaseIntensity[orbState]),
  }
}

function isStale(state: CeresState, action: { interactionId?: string | null; generationId?: string | null }) {
  if (action.interactionId && state.deadInteractionIds.includes(action.interactionId)) return true
  if (action.interactionId && state.interactionId && action.interactionId !== state.interactionId) return true
  if (action.generationId && state.generationId && action.generationId !== state.generationId) return true
  return false
}

function idsFromEvent(event: any) {
  return {
    interactionId: event.interaction_id ?? event.data?.interaction_id ?? null,
    generationId: event.data?.gen_id ?? event.data?.generation_id ?? null,
    threadId: event.data?.thread_id ?? null,
  }
}

export function ceresReducer(state: CeresState, action: CeresAction): CeresState {
  switch (action.type) {
    case 'BOOT_COMPLETE':
      return withState(state, 'AUTH')
    case 'AUTH_REQUIRED':
      return withState(state, 'AUTH')
    case 'AUTH_COMPLETE':
      return withState(state, 'IDLE')
    case 'WS_CONNECTING':
      return { ...state, connectionState: 'connecting' }
    case 'WS_CONNECTED':
      return { ...state, connectionState: 'connected', error: null }
    case 'WS_DISCONNECTED':
      return { ...state, connectionState: 'disconnected' }
    case 'WS_ERROR':
      return withState(state, 'ERROR', { error: action.error })
    case 'RECORDER_ERROR':
      // Mic / STT errors are non-fatal — recover to IDLE so the user can try again.
      // Do NOT crash into ERROR state for a microphone permission or network blip.
      console.warn('[CERES] Recorder error (non-fatal):', action.error)
      return withState(state, 'IDLE', { isRecording: false, error: action.error })
    case 'CLIENT_QUERY_START':
      return withState(state, 'THINKING', {
        interactionId: action.interactionId,
        threadId: action.threadId ?? state.threadId,
        generationId: null,
        isPlaying: false,
        isRecording: false,
        events: [{ type: 'user_query', agent: 'USR', message: action.query, data: { interaction_id: action.interactionId } }],
      })
    case 'WAKE_WORD_DETECTED':
      if (state.orbState === 'SPEAKING') return ceresReducer(state, { type: 'INTERRUPT_REQUESTED' })
      return withState(state, 'LISTENING', { isRecording: true })
    case 'RECORDER_STARTED':
      return withState(state, 'LISTENING', { isRecording: true })
    case 'RECORDER_STOPPED':
      return { ...state, isRecording: false }
    case 'STT_TEXT_READY':
      if (isStale(state, action)) return state
      return withState(state, 'THINKING', { isRecording: false })
    case 'STREAM_EVENT': {
      const event = action.event
      const ids = idsFromEvent(event)
      if (isStale(state, ids)) return state

      const nextBase = {
        ...state,
        generationId: ids.generationId ?? state.generationId,
        threadId: ids.threadId ?? state.threadId,
      }

      if (event.type === 'stream_start') {
        return withState(nextBase, 'THINKING', { events: [...state.events, event] })
      }
      if (event.type === 'token_chunk') {
        return { ...nextBase, events: [...state.events, event] }
      }
      if (event.type === 'tts_start') {
        return withState(nextBase, 'SPEAKING', { isPlaying: true, events: [...state.events, event] })
      }
      if (event.type === 'tts_chunk') {
        return { ...nextBase, isPlaying: true }
      }
      if (event.type === 'stream_end') {
        return { ...nextBase, events: [...state.events, event] }
      }
      if (event.type === 'stream_cancelled' || event.type === 'interrupt_ack') {
        return withState(nextBase, 'LISTENING', { isPlaying: false, isRecording: true })
      }
      if (event.type === 'action_required') {
        return {
          ...nextBase,
          pendingApproval: {
            threadId: event.data?.thread_id ?? state.threadId ?? '',
            action: event.data?.action_payload,
            message: event.message,
          },
          events: [...state.events, event],
        }
      }
      if (event.type === 'proactive_alert' || event.type === 'agent_state_update' || event.type === 'agent_update') {
        return { ...nextBase, events: [...state.events, event] }
      }
      if (event.type === 'stream_error') {
        return withState(nextBase, 'ERROR', { error: event.message, events: [...state.events, event] })
      }
      return { ...nextBase, events: [...state.events, event] }
    }
    case 'TTS_START':
    case 'AUDIO_STARTED':
      if (isStale(state, action)) return state
      return withState(state, 'SPEAKING', { isPlaying: true, generationId: action.generationId ?? state.generationId })
    case 'AUDIO_CHUNK_RECEIVED':
      if (isStale(state, action)) return state
      return { ...state, isPlaying: true, generationId: action.generationId ?? state.generationId }
    case 'AUDIO_AMPLITUDE':
      return { ...state, audioAmplitude: action.amplitude, visualIntensity: Math.max(state.visualIntensity, 0.2 + action.amplitude * 0.7) }
    case 'AUDIO_FINISHED':
      if (isStale(state, action)) return state
      return withState(state, 'IDLE', { isPlaying: false, audioAmplitude: 0, interactionId: null, generationId: null })
    case 'INTERRUPT_REQUESTED': {
      const dead = state.interactionId ? [...state.deadInteractionIds.slice(-8), state.interactionId] : state.deadInteractionIds
      return withState(state, 'INTERRUPTING', {
        deadInteractionIds: dead,
        interactionId: null,
        generationId: null,
        isPlaying: false,
        audioAmplitude: 0,
      })
    }
    case 'INTERRUPT_ACK':
    case 'INTERRUPT_COMPLETED':
      return withState(state, 'LISTENING', { isRecording: true, isPlaying: false })
    case 'PENDING_APPROVAL':
      return { ...state, pendingApproval: action.approval }
    case 'STATS_UPDATE':
      return { ...state, stats: action.stats }
    case 'CLEAR_EVENTS':
      return { ...state, events: [] }
    case 'FORCE_STATE':
      return withState(state, action.state, { error: action.reason ?? state.error })
    default:
      return state
  }
}
