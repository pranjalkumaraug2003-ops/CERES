/**
 * useAudioPlayer — thin compat shim.
 *
 * Audio is now managed by the AudioQueue singleton inside useCeresStore.
 * This hook exists only so components that destructure { isPlaying }
 * continue to compile without changes.
 *
 * All actual playback is driven by useCeresStore's tts_chunk handler.
 */
import { useCeresStore } from '../store/useCeresStore'

export const useAudioPlayer = () => {
  const isPlaying = useCeresStore(s => s.isPlaying)
  const interrupt  = useCeresStore(s => s.interrupt)

  return {
    isPlaying,
    stopAudio: interrupt,
    // Legacy compat: playBase64Audio is a no-op — audio flows through AudioQueue
    playBase64Audio: (_base64: string) => {},
  }
}
