import { useState, useCallback, useEffect } from 'react'
import { CeresBootScreen } from './components/CeresBootScreen'
import { FaceAuthScreen } from './components/FaceAuthScreen'
import { JarvisOrb } from './components/JarvisOrb'
import { ApprovalModal } from './components/ApprovalModal'
import { useCeresStore } from './store/useCeresStore'

export default function App() {
  const dispatch = useCeresStore(s => s.dispatch)
  // Persist boot/auth across refreshes for the session lifetime
  const [booted, setBooted] = useState(() => sessionStorage.getItem('ceres_booted') === '1')
  const [authenticated, setAuthenticated] = useState(() => sessionStorage.getItem('ceres_auth') === '1')

  const handleBoot = useCallback(() => {
    sessionStorage.setItem('ceres_booted', '1')
    dispatch({ type: 'BOOT_COMPLETE' })
    setBooted(true)
  }, [dispatch])

  const handleAuth = useCallback(() => {
    sessionStorage.setItem('ceres_auth', '1')
    dispatch({ type: 'AUTH_COMPLETE' })
    setAuthenticated(true)
  }, [dispatch])

  useEffect(() => {
    if (booted && authenticated) dispatch({ type: 'AUTH_COMPLETE' })
    else if (booted) dispatch({ type: 'BOOT_COMPLETE' })
  }, [booted, authenticated, dispatch])

  if (!booted) {
    return <CeresBootScreen onComplete={handleBoot} />
  }

  if (!authenticated) {
    return <FaceAuthScreen onComplete={handleAuth} />
  }

  return (
    <>
      <JarvisOrb />
      <ApprovalModal />
    </>
  )
}
