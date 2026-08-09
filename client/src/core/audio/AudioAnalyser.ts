export class AudioAnalyser {
  private analyser: AnalyserNode | null = null
  private smoothedAmplitude = 0

  constructor(analyser: AnalyserNode | null) {
    this.analyser = analyser
  }

  setAnalyser(analyser: AnalyserNode | null) {
    this.analyser = analyser
  }

  getAmplitude(): number {
    if (!this.analyser) {
      // Decay back to 0 slowly if no analyser is connected
      this.smoothedAmplitude += (0 - this.smoothedAmplitude) * 0.08
      return this.smoothedAmplitude
    }

    const data = new Uint8Array(this.analyser.frequencyBinCount)
    this.analyser.getByteFrequencyData(data)

    let sum = 0
    for (let i = 0; i < data.length; i++) {
      sum += data[i]
    }

    // Normalized raw average amplitude
    const raw = Math.min(1, sum / data.length / 120)

    // Smooth amplitude: fast rise (0.35), slow decay (0.06)
    if (raw > this.smoothedAmplitude) {
      this.smoothedAmplitude += (raw - this.smoothedAmplitude) * 0.38
    } else {
      this.smoothedAmplitude += (raw - this.smoothedAmplitude) * 0.06
    }

    return this.smoothedAmplitude
  }
}
