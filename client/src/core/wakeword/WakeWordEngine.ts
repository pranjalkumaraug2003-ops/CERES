import type { CeresDispatch } from '../state/ceresMachine'

const WAKE_PHRASES = ['hey ceres', 'ceres', 'ok ceres']

export class WakeWordEngine {
  private dispatch: CeresDispatch
  private recognition: any = null
  private listening = false
  private lastActivation = 0

  constructor(dispatch: CeresDispatch) {
    this.dispatch = dispatch
  }

  start(onActivated: () => void, onInterrupt: () => void, isSpeaking: () => boolean, isRecording: () => boolean) {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition || this.listening) return

    this.recognition = new SpeechRecognition()
    this.recognition.continuous = true
    this.recognition.interimResults = true
    this.recognition.lang = 'en-US'
    this.listening = true

    this.recognition.onresult = (event: any) => {
      if (isRecording()) return
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript.toLowerCase().trim()
        if (!WAKE_PHRASES.some(phrase => transcript.includes(phrase))) continue
        const now = Date.now()
        if (now - this.lastActivation < 1200) return
        this.lastActivation = now
        this.dispatch({ type: 'WAKE_WORD_DETECTED' })
        if (isSpeaking()) onInterrupt()
        window.setTimeout(onActivated, isSpeaking() ? 120 : 0)
        return
      }
    }

    this.recognition.onend = () => {
      if (!this.listening) return
      try { this.recognition.start() } catch {}
    }

    this.recognition.onerror = (event: any) => {
      if (event.error === 'not-allowed') this.stop()
    }

    try { this.recognition.start() } catch {}
  }

  stop() {
    this.listening = false
    try { this.recognition?.stop() } catch {}
  }
}
