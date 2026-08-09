import type { CeresDispatch } from '../state/ceresMachine'
import { parseStreamEvent } from './streamParser'

export class WebSocketManager {
  private ws: WebSocket | null = null
  private dispatch: CeresDispatch
  private reconnectTimer = 0

  constructor(dispatch: CeresDispatch) {
    this.dispatch = dispatch
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return
    this.dispatch({ type: 'WS_CONNECTING' })
    const socket = new WebSocket('ws://localhost:8000/ws/chat')
    this.ws = socket

    socket.onopen = () => this.dispatch({ type: 'WS_CONNECTED' })
    socket.onmessage = raw => {
      const event = parseStreamEvent(raw)
      if (!event) return
      this.dispatch({ type: 'STREAM_EVENT', event })
    }
    socket.onerror = () => this.dispatch({ type: 'WS_ERROR', error: 'WebSocket connection error' })
    socket.onclose = () => {
      this.ws = null
      this.dispatch({ type: 'WS_DISCONNECTED' })
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = window.setTimeout(() => this.connect(), 1400)
    }
  }

  sendQuery(query: string, interactionId: string, threadId?: string | null) {
    this.connect()
    if (this.ws?.readyState !== WebSocket.OPEN) return
    this.ws.send(JSON.stringify({ query, interaction_id: interactionId, thread_id: threadId ?? undefined }))
  }

  interrupt(interactionId?: string | null, threadId?: string | null) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'interrupt', interaction_id: interactionId ?? undefined, thread_id: threadId ?? undefined }))
    }
  }

  confirm(action: 'approve' | 'deny', threadId?: string | null) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'confirmation', action, thread_id: threadId ?? undefined }))
    }
  }

  disconnect() {
    window.clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }
}
