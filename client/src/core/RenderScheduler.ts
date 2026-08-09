type RenderCallback = (time: number, deltaTime: number) => void

class RenderSchedulerClass {
  private callbacks: Map<string, RenderCallback> = new Map()
  private running = false
  private lastTime = 0
  private rafId = 0

  subscribe(id: string, callback: RenderCallback) {
    this.callbacks.set(id, callback)
    if (!this.running) {
      this.running = true
      this.lastTime = performance.now()
      this.rafId = requestAnimationFrame(this.tick)
    }
  }

  unsubscribe(id: string) {
    this.callbacks.delete(id)
    if (this.callbacks.size === 0 && this.running) {
      this.running = false
      cancelAnimationFrame(this.rafId)
    }
  }

  private tick = (time: number) => {
    if (!this.running) return
    const deltaTime = time - this.lastTime
    this.lastTime = time

    this.callbacks.forEach((callback, id) => {
      try {
        callback(time, deltaTime)
      } catch (err) {
        console.error(`Error in RenderScheduler callback [${id}]:`, err)
      }
    })

    this.rafId = requestAnimationFrame(this.tick)
  }
}

export const RenderScheduler = new RenderSchedulerClass()
