import { useState, useEffect, useRef, useCallback } from 'react'

const WAKE_PHRASES = ['hey ceres', 'ceres', 'ok ceres']

/**
 * Always-on wake word detection.
 *
 * @param onActivated  Called when wake phrase is detected and CERES is idle.
 * @param onInterrupt  Called when wake phrase is detected while CERES is speaking.
 *                     Should flush audio and cancel the backend pipeline.
 */
export const useWakeWord = (
  onActivated: () => void,
  onInterrupt: () => void,
  isPlaying: boolean = false
) => {
  const [isListening, setIsListening] = useState(false)
  const recognitionRef = useRef<any>(null)
  const isPlayingRef = useRef(isPlaying)

  // Keep ref in sync with prop so the closure inside onresult stays current
  useEffect(() => {
    isPlayingRef.current = isPlaying
  }, [isPlaying])

  const startListening = useCallback(() => {
    // @ts-ignore
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) return

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript.toLowerCase().trim()
        for (const phrase of WAKE_PHRASES) {
          if (transcript.includes(phrase)) {
            recognition.stop()
            setIsListening(false)

            if (isPlayingRef.current) {
              // Barge-in: CERES is speaking — interrupt it, then activate
              onInterrupt()
              setTimeout(onActivated, 80)  // brief gap so flush() completes first
            } else {
              onActivated()
            }
            return
          }
        }
      }
    }

    recognition.onend = () => {
      // Restart automatically to keep always-on listening
      if (isListening) {
        try { recognition.start() } catch {}
      }
    }

    recognition.onerror = (e: any) => {
      if (e.error === 'not-allowed') {
        console.warn('Wake word: mic permission denied')
        setIsListening(false)
      }
    }

    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
  }, [onActivated, onInterrupt, isListening])

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
    setIsListening(false)
  }, [])

  useEffect(() => {
    startListening()
    return () => stopListening()
  }, [startListening, stopListening])

  return { isListening, startListening, stopListening }
}
