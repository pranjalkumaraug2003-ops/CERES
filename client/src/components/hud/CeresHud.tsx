import { useEffect, useState } from 'react'
import { Mic, Send, Square, Wifi, WifiOff } from 'lucide-react'
import type { OrbState, SystemStats } from '../../core/state/ceresTypes'

export function CeresHud({
  state,
  connected,
  stats,
  isRecording,
  onSend,
  onMic,
  onInterrupt,
}: {
  state: OrbState
  connected: boolean
  stats: SystemStats
  isRecording: boolean
  onSend: (query: string) => void
  onMic: () => void
  onInterrupt: () => void
}) {
  const [input, setInput] = useState('')
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const id = window.setInterval(() => setTime(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const submit = (query = input) => {
    const clean = query.trim()
    if (!clean) return
    onSend(clean)
    setInput('')
  }

  return (
    <>
      <header className="celestial-hud-top">
        <div className="hud-identity">
          {connected ? <Wifi size={14} /> : <WifiOff size={14} />}
          <span>CERES</span>
          <small>{state}</small>
        </div>
        <div className="hud-clock">{time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}</div>
        <div className="hud-telemetry">
          <span>CPU {stats.cpu_percent.toFixed(0)}%</span>
          <span>BAT {stats.battery_percent.toFixed(0)}%</span>
          <span>MEM {stats.ram_used_gb.toFixed(1)}G</span>
        </div>
      </header>

      <footer className="celestial-command">
        <button className={`celestial-icon-button ${isRecording ? 'active' : ''}`} onClick={onMic} title="Voice input">
          <Mic size={15} />
        </button>
        <div className="celestial-input">
          <input
            value={input}
            onChange={event => setInput(event.target.value)}
            onKeyDown={event => event.key === 'Enter' && submit()}
            placeholder="Awaiting directive..."
          />
        </div>
        <button className="celestial-icon-button" onClick={() => submit()} title="Send">
          <Send size={15} />
        </button>
        <button className="celestial-icon-button interrupt" onClick={onInterrupt} title="Interrupt">
          <Square size={13} />
        </button>
      </footer>
    </>
  )
}
