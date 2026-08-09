import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Mic, MicOff, Volume2 } from 'lucide-react'
import { useCeresStore } from '../store/useCeresStore'
import { useVoiceRecorder } from '../hooks/useVoiceRecorder'
import { useAudioPlayer } from '../hooks/useAudioPlayer'

const AGENT_COLORS: Record<string, string> = {
  Orchestrator: 'text-violet-400',
  'Memory Agent': 'text-cyan-400',
  'Automation Agent': 'text-orange-400',
  'Reflection Agent': 'text-yellow-400',
  'Communication Agent': 'text-green-400',
  System: 'text-gray-400',
}

export function CeresTerminal() {
  const { events, connectionState, connect, sendQuery, clearEvents, disconnect } = useCeresStore()
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const isConnected = connectionState === 'connected'
  
  const { isPlaying, playBase64Audio } = useAudioPlayer()
  const { isRecording, startRecording, stopRecording } = useVoiceRecorder((text) => {
    setInput(text)
    handleSend(text)
  })

  useEffect(() => { connect() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events])

  const handleSend = (overrideInput?: string) => {
    const query = overrideInput || input.trim()
    if (!query) return
    clearEvents()
    sendQuery(query)
    setInput('')
  }

  const activeAgentEvent = events.slice().reverse().find(e => e.type === 'agent_state_update')
  const activeAgent = activeAgentEvent ? activeAgentEvent.agent : null

  return (
    <div className="min-h-screen bg-gray-950 text-sm font-mono flex flex-col p-4 gap-4">
      <div className="flex items-center gap-3 border-b border-gray-800 pb-3">
        <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-red-500'}`} />
        <span className="text-gray-300 font-bold tracking-widest">CERES OS</span>
        
        <div className="ml-8 px-4 py-1 rounded bg-gray-900 border border-gray-800 flex items-center gap-2">
           <span className="text-xs text-gray-500">ACTIVE PROCESS:</span>
           {activeAgent ? (
             <span className={`font-bold ${AGENT_COLORS[activeAgent] || 'text-white'}`}>{activeAgent}</span>
           ) : (
             <span className="text-gray-600">IDLE</span>
           )}
           {isPlaying && <Volume2 className="w-4 h-4 text-violet-400 animate-pulse ml-2" />}
        </div>

        <span className="text-gray-600 text-xs ml-auto">
          {isConnected ? 'CONNECTED' : 'DISCONNECTED'}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto space-y-1 min-h-[400px]">
        <AnimatePresence>
          {events.map((evt, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex gap-2"
            >
              <span className={`font-bold ${AGENT_COLORS[evt.agent] || 'text-white'}`}>
                [{evt.agent}]
              </span>
              <span className="text-gray-300">{evt.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2 border-t border-gray-800 pt-3 items-center">
        <span className="text-violet-400">›</span>
        <input
          className="flex-1 bg-transparent text-gray-100 outline-none placeholder-gray-600"
          placeholder="Ask CERES anything..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button
          onClick={isRecording ? stopRecording : startRecording}
          className={`p-2 rounded transition-colors ${isRecording ? 'bg-red-500/20 text-red-500 animate-pulse' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
        >
          {isRecording ? <Mic className="w-4 h-4" /> : <MicOff className="w-4 h-4" />}
        </button>
        <button
          onClick={() => handleSend()}
          className="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded font-bold text-xs"
        >
          SEND
        </button>
      </div>
    </div>
  )
}
