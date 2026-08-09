export type AudioEngineEvent =
  | { type: 'AUDIO_CHUNK_RECEIVED'; interactionId?: string | null; generationId?: string | null }
  | { type: 'AUDIO_STARTED'; interactionId?: string | null; generationId?: string | null }
  | { type: 'AUDIO_AMPLITUDE'; amplitude: number }
  | { type: 'AUDIO_FINISHED'; interactionId?: string | null; generationId?: string | null }
  | { type: 'AUDIO_INTERRUPTED' }
