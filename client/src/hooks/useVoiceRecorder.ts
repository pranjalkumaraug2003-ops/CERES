import { useState, useCallback, useRef } from 'react'

export const useVoiceRecorder = (onTextReady: (text: string) => void) => {
  const [isRecording, setIsRecording] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      chunksRef.current = []

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      mediaRecorder.onstop = async () => {
        setIsRecording(false)
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        
        // Cleanup mic
        stream.getTracks().forEach(track => track.stop())

        const formData = new FormData()
        formData.append('audio', blob, 'audio.webm')

        try {
          const res = await fetch('http://localhost:8000/api/stt', {
            method: 'POST',
            body: formData,
          })
          const data = await res.json()
          if (data.text) {
            onTextReady(data.text)
          } else if (data.error) {
            console.error('STT Error:', data.error)
          }
        } catch (err) {
          console.error('Failed to upload audio:', err)
        }
      }

      mediaRecorder.start()
      setIsRecording(true)
    } catch (err) {
      console.error('Failed to get mic access', err)
      alert("Microphone access denied or not available.")
    }
  }, [onTextReady])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }, [])

  return { isRecording, startRecording, stopRecording }
}
