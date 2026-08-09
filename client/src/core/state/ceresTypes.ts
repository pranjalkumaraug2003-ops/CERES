export type OrbState =
  | 'BOOTING'
  | 'AUTH'
  | 'IDLE'
  | 'LISTENING'
  | 'THINKING'
  | 'SPEAKING'
  | 'INTERRUPTING'
  | 'ERROR'

export type ConnectionState = 'disconnected' | 'connecting' | 'connected'

export interface CeresStreamEvent {
  type: string
  agent: string
  message: string
  timestamp?: number
  interaction_id?: string
  data?: Record<string, any>
}

export interface PendingApproval {
  threadId: string
  action: any
  message: string
}

export interface SystemStats {
  cpu_percent: number
  ram_used_gb: number
  ram_total_gb: number
  battery_percent: number
  network_mbps: number
  disk_used_gb: number
  disk_total_gb: number
}

export interface CeresState {
  orbState: OrbState
  previousOrbState: OrbState
  stateEnteredAt: number
  transitionLockUntil: number
  entryEffect: string | null
  interactionId: string | null
  generationId: string | null
  threadId: string | null
  deadInteractionIds: string[]
  visualIntensity: number
  audioAmplitude: number
  isRecording: boolean
  isPlaying: boolean
  connectionState: ConnectionState
  events: CeresStreamEvent[]
  pendingApproval: PendingApproval | null
  stats: SystemStats
  error: string | null
}

export const defaultStats: SystemStats = {
  cpu_percent: 0,
  ram_used_gb: 0,
  ram_total_gb: 8,
  battery_percent: 100,
  network_mbps: 0,
  disk_used_gb: 0,
  disk_total_gb: 500,
}
