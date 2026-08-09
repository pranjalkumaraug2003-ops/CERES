import type { CeresStreamEvent } from '../state/ceresTypes'

export function parseStreamEvent(raw: MessageEvent<string>): CeresStreamEvent | null {
  try {
    const parsed = JSON.parse(raw.data)
    if (!parsed || typeof parsed.type !== 'string') return null
    return {
      type: parsed.type,
      agent: parsed.agent ?? 'System',
      message: parsed.message ?? '',
      timestamp: parsed.timestamp,
      interaction_id: parsed.interaction_id ?? parsed.data?.interaction_id,
      data: parsed.data ?? {},
    }
  } catch {
    return null
  }
}
