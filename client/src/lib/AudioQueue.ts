export class AudioQueue {
  private ctx: AudioContext | null = null
  private endTime = 0
  private sources: AudioBufferSourceNode[] = []
  private _flushed = false

  private getCtx(): AudioContext {
    if (!this.ctx || this.ctx.state === 'closed') {
      this.ctx    = new AudioContext()
      this.endTime = 0
    }
    return this.ctx
  }

  async enqueue(base64Audio: string): Promise<void> {
    if (this._flushed) return            // ignore chunks after flush until reset()

    let ctx: AudioContext
    try {
      ctx = this.getCtx()
    } catch {
      return
    }

    const bytes  = Uint8Array.from(atob(base64Audio), c => c.charCodeAt(0))
    let   buffer: AudioBuffer
    try {
      buffer = await ctx.decodeAudioData(bytes.buffer)
    } catch {
      return                             // ignore malformed audio
    }

    if (this._flushed) return            // re-check after async decode

    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)

    const startAt = Math.max(ctx.currentTime + 0.02, this.endTime)  // 20ms crossfade gap
    source.start(startAt)
    this.endTime = startAt + buffer.duration

    this.sources.push(source)
    source.onended = () => {
      this.sources = this.sources.filter(s => s !== source)
    }
  }

  /** Call before starting any new response. Stops all playing audio immediately. */
  flush(): void {
    this._flushed = true
    this.sources.forEach(s => { try { s.stop(0) } catch {} })
    this.sources  = []
    this.endTime  = 0
    if (this.ctx && this.ctx.state !== 'closed') {
      this.ctx.close()
    }
    this.ctx = null
  }

  /** Call after flush() to re-arm the queue for the next response. */
  reset(): void {
    this._flushed = false
  }

  get isPlaying(): boolean {
    return this.sources.length > 0
  }
}
