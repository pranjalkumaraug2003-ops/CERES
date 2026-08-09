import { useState, useEffect } from 'react'

export function FaceAuthScreen({ onComplete }: { onComplete: () => void }) {
  const [status, setStatus] = useState('Initializing Face Recognition...')
  const [error, setError] = useState<string | null>(null)
  
  useEffect(() => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000)

    fetch('http://localhost:8000/api/auth/face', { signal: controller.signal })
      .then(r => r.json())
      .then(data => {
        clearTimeout(timeoutId)
        if (data.authenticated) {
          setStatus(`Welcome back, ${data.user.toUpperCase()}`)
          setTimeout(onComplete, 2000)
        } else {
          setError(data.error || 'Authentication failed.')
          setStatus('Authentication Failed.')
        }
      })
      .catch(e => {
        clearTimeout(timeoutId)
        setError(e.name === 'AbortError' ? 'Webcam timeout (hardware lock)' : e.message)
        setStatus('Connection Error.')
      })
      
    return () => clearTimeout(timeoutId)
  }, [onComplete])

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'var(--os-void)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
      {/* Background Ambient Grid */}
      <div className="ambient-grid" />
      <div className="volumetric-light" />
      <div className="scanlines" />

      {/* Target Reticle Box */}
      <div style={{ position: 'relative', width: 260, height: 260, border: '1px solid var(--os-border)', borderRadius: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 40, background: 'var(--os-panel-bg)', backdropFilter: 'blur(16px)' }}>
        {/* Reticle corners */}
        <div style={{ position: 'absolute', top: -1, left: -1, width: 30, height: 30, borderTop: '2px solid var(--os-primary)', borderLeft: '2px solid var(--os-primary)', borderTopLeftRadius: 16 }} />
        <div style={{ position: 'absolute', top: -1, right: -1, width: 30, height: 30, borderTop: '2px solid var(--os-primary)', borderRight: '2px solid var(--os-primary)', borderTopRightRadius: 16 }} />
        <div style={{ position: 'absolute', bottom: -1, left: -1, width: 30, height: 30, borderBottom: '2px solid var(--os-primary)', borderLeft: '2px solid var(--os-primary)', borderBottomLeftRadius: 16 }} />
        <div style={{ position: 'absolute', bottom: -1, right: -1, width: 30, height: 30, borderBottom: '2px solid var(--os-primary)', borderRight: '2px solid var(--os-primary)', borderBottomRightRadius: 16 }} />
        
        {/* Scanning line */}
        <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 16 }}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'var(--os-primary)', boxShadow: '0 0 15px var(--os-primary)', animation: 'scanline-pass 3s linear infinite' }} />
        </div>

        {/* Inner icon */}
        <svg style={{ width: 64, height: 64, color: 'var(--os-primary-dim)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M10 21h4M12 21v-4M8 7h8M8 11h8M12 3v4" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M5 19V5h14v14H5z" />
        </svg>
      </div>

      <div className="font-tech" style={{ fontSize: 16, letterSpacing: '0.2em', color: error ? 'var(--os-alert)' : 'var(--os-primary)', textShadow: `0 0 10px ${error ? 'var(--os-alert)' : 'var(--os-primary-dim)'}` }}>
        {status}
      </div>

      {error && (
        <div className="font-mono" style={{ color: 'var(--os-alert)', opacity: 0.8, fontSize: 12, marginTop: 16, maxWidth: 300, textAlign: 'center' }}>
          {error}
        </div>
      )}

      {error && (
        <button 
          onClick={onComplete}
          className="font-tech spatial-panel"
          style={{ marginTop: 40, padding: '12px 24px', cursor: 'pointer', fontSize: 12, color: 'var(--os-text)', background: 'var(--os-panel-bg)' }}
        >
          BYPASS AUTHENTICATION
        </button>
      )}
    </div>
  )
}
