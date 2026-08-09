import type { CeresDispatch } from '../state/ceresMachine'
import { makeInteractionId } from '../state/ceresEvents'

export class RecorderEngine {
  private dispatch: CeresDispatch
  private mediaRecorder: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []
  private silenceTimer = 0
  
  // Web Audio VAD variables
  private audioCtx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private vadInterval = 0

  constructor(dispatch: CeresDispatch) {
    this.dispatch = dispatch
  }

  async start(onTextReady: (text: string, interactionId: string) => void) {
    if (this.mediaRecorder?.state === 'recording') return
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      this.mediaRecorder = new MediaRecorder(this.stream)
      this.chunks = []
      this.dispatch({ type: 'RECORDER_STARTED' })

      this.mediaRecorder.ondataavailable = event => {
        if (event.data.size > 0) this.chunks.push(event.data)
      }

      this.mediaRecorder.onstop = async () => {
        window.clearTimeout(this.silenceTimer)
        if (this.vadInterval) {
          window.clearInterval(this.vadInterval)
          this.vadInterval = 0
        }
        if (this.audioCtx) {
          void this.audioCtx.close()
          this.audioCtx = null
        }
        this.analyser = null
        this.source = null

        this.dispatch({ type: 'RECORDER_STOPPED' })
        this.stream?.getTracks().forEach(track => track.stop())
        this.stream = null

        const blob = new Blob(this.chunks, { type: 'audio/webm' })
        const formData = new FormData()
        formData.append('audio', blob, 'audio.webm')

        try {
          const response = await fetch('http://localhost:8000/api/stt', { method: 'POST', body: formData })
          const data = await response.json()
          if (data.text) {
            const interactionId = makeInteractionId()
            this.dispatch({ type: 'STT_TEXT_READY', text: data.text, interactionId })
            onTextReady(data.text, interactionId)
          } else if (data.error) {
            this.dispatch({ type: 'RECORDER_ERROR', error: data.error })
          }
        } catch (error) {
          this.dispatch({ type: 'RECORDER_ERROR', error: error instanceof Error ? error.message : 'STT upload failed' })
        }
      }

      this.mediaRecorder.start()
      
      // Initialize Web Audio RMS VAD
      try {
        const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
        if (AudioContextClass) {
          this.audioCtx = new AudioContextClass()
          this.analyser = this.audioCtx.createAnalyser()
          this.analyser.fftSize = 512
          this.source = this.audioCtx.createMediaStreamSource(this.stream)
          this.source.connect(this.analyser)

          const bufferLength = this.analyser.fftSize
          const dataArray = new Float32Array(bufferLength)
          const threshold = 0.012 // sensitive threshold for speech activity detection
          const silenceTimeout = 400 // 400ms silence window
          let hasSpoken = false
          let lastActiveTime = Date.now()

          this.vadInterval = window.setInterval(() => {
            if (!this.analyser) return
            this.analyser.getFloatTimeDomainData(dataArray)
            let sum = 0
            for (let i = 0; i < bufferLength; i++) {
              sum += dataArray[i] * dataArray[i]
            }
            const rms = Math.sqrt(sum / bufferLength)
            const now = Date.now()

            if (rms > threshold) {
              hasSpoken = true
              lastActiveTime = now
            } else if (hasSpoken && (now - lastActiveTime > silenceTimeout)) {
              console.log("[VAD] Silence detected after speech. Stopping recorder.");
              this.stop()
            }
          }, 50)
        }
      } catch (vadError) {
        console.warn("[VAD] Failed to initialize Web Audio VAD:", vadError)
      }

      // Hard cap fallback of 9 seconds
      this.silenceTimer = window.setTimeout(() => this.stop(), 9000)
    } catch (error) {
      this.dispatch({ type: 'RECORDER_ERROR', error: error instanceof Error ? error.message : 'Microphone unavailable' })
    }
  }

  stop() {
    if (this.mediaRecorder?.state === 'recording') this.mediaRecorder.stop()
  }
}
