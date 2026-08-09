import type { CeresStreamEvent, OrbState, PendingApproval, SystemStats } from './ceresTypes'

export type CeresAction =
  | { type: 'BOOT_COMPLETE' }
  | { type: 'AUTH_REQUIRED' }
  | { type: 'AUTH_COMPLETE' }
  | { type: 'WS_CONNECTING' }
  | { type: 'WS_CONNECTED' }
  | { type: 'WS_DISCONNECTED' }
  | { type: 'WS_ERROR'; error: string }
  | { type: 'RECORDER_ERROR'; error: string }
  | { type: 'CLIENT_QUERY_START'; query: string; interactionId: string; threadId?: string | null }
  | { type: 'WAKE_WORD_DETECTED' }
  | { type: 'RECORDER_STARTED' }
  | { type: 'RECORDER_STOPPED' }
  | { type: 'STT_TEXT_READY'; text: string; interactionId: string }
  | { type: 'STREAM_EVENT'; event: CeresStreamEvent }
  | { type: 'TTS_START'; interactionId?: string | null; generationId?: string | null }
  | { type: 'AUDIO_CHUNK_RECEIVED'; interactionId?: string | null; generationId?: string | null }
  | { type: 'AUDIO_STARTED'; interactionId?: string | null; generationId?: string | null }
  | { type: 'AUDIO_AMPLITUDE'; amplitude: number }
  | { type: 'AUDIO_FINISHED'; interactionId?: string | null; generationId?: string | null }
  | { type: 'INTERRUPT_REQUESTED' }
  | { type: 'INTERRUPT_ACK'; interactionId?: string | null }
  | { type: 'INTERRUPT_COMPLETED' }
  | { type: 'PENDING_APPROVAL'; approval: PendingApproval | null }
  | { type: 'STATS_UPDATE'; stats: SystemStats }
  | { type: 'CLEAR_EVENTS' }
  | { type: 'FORCE_STATE'; state: OrbState; reason?: string }

export const makeInteractionId = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `ceres-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
