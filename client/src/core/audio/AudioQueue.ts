import { AudioAnalyser } from './AudioAnalyser'

export interface QueuedAudio {
  audioBase64: string
  interactionId?: string | null
  generationId?: string | null
}

export class AudioQueue {
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private audioAnalyser: AudioAnalyser = new AudioAnalyser(null)
  private endTime = 0
  private sources: AudioBufferSourceNode[] = []
  private _flushed = false

  private getCtx(): AudioContext {
    if (!this.ctx || this.ctx.state === 'closed') {
      this.ctx = new AudioContext()
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = 256
      this.analyser.connect(this.ctx.destination)
      this.audioAnalyser.setAnalyser(this.analyser)
      this.endTime = 0
    }
    return this.ctx
  }

  async enqueue(item: QueuedAudio, onEnded: () => void): Promise<void> {
    if (this._flushed) return

    let ctx: AudioContext
    try {
      ctx = this.getCtx()
    } catch {
      return
    }

    const bytes = Uint8Array.from(atob(item.audioBase64), c => c.charCodeAt(0))
    let buffer: AudioBuffer
    try {
      buffer = await ctx.decodeAudioData(bytes.buffer)
    } catch {
      return
    }

    if (this._flushed) return

    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(this.analyser ?? ctx.destination)

    const startAt = Math.max(ctx.currentTime + 0.02, this.endTime)
    source.start(startAt)
    this.endTime = startAt + buffer.duration

    this.sources.push(source)
    source.onended = () => {
      this.sources = this.sources.filter(s => s !== source)
      onEnded()
    }
  }

  getAmplitude(): number {
    return this.audioAnalyser.getAmplitude()
  }

  flush(): void {
    this._flushed = true
    this.sources.forEach(source => {
      try { source.stop(0) } catch {}
    })
    this.sources = []
    this.endTime = 0
    if (this.ctx && this.ctx.state !== 'closed') this.ctx.close()
    this.ctx = null
    this.analyser = null
    this.audioAnalyser.setAnalyser(null)
  }

  reset(): void {
    this._flushed = false
  }

  get isPlaying(): boolean {
    return this.sources.length > 0
  }
}

