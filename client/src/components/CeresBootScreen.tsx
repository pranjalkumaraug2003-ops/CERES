import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const BOOT_STEPS = [
  { msg: 'Initializing Neural Networks...', pct: 12, module: 'Neural Core', status: 'LOADING' },
  { msg: 'Establishing AI Core Link...', pct: 25, module: 'Neural Core', status: 'ACTIVE' },
  { msg: 'Loading Voice Recognition Engine...', pct: 40, module: 'Voice Engine', status: 'LOADING' },
  { msg: 'Calibrating Speech Synthesis...', pct: 52, module: 'Voice Engine', status: 'READY' },
  { msg: 'Activating Vision & Biometric Systems...', pct: 65, module: 'Vision System', status: 'LOADING' },
  { msg: 'Biometric scan complete...', pct: 75, module: 'Vision System', status: 'READY' },
  { msg: 'Encrypting secure telemetry link...', pct: 88, module: 'Security', status: 'LOADING' },
  { msg: 'All Systems Nominal — C.E.R.E.S Online.', pct: 100, module: 'Security', status: 'SECURED' },
]

interface CeresBootScreenProps { onComplete: () => void }

export function CeresBootScreen({ onComplete }: CeresBootScreenProps) {
  const [step, setStep] = useState(0)
  const [progress, setProgress] = useState(0)
  const [done, setDone] = useState(false)
  const [cpuPct] = useState(() => Math.floor(38 + Math.random() * 22))
  const [ramPct] = useState(() => Math.floor(52 + Math.random() * 18))

  useEffect(() => {
    if (done) { const t = setTimeout(onComplete, 1000); return () => clearTimeout(t) }
    const t = setTimeout(() => {
      const next = Math.min(step + 1, BOOT_STEPS.length - 1)
      setStep(next)
      setProgress(BOOT_STEPS[next].pct)
      if (next === BOOT_STEPS.length - 1) setTimeout(() => setDone(true), 600)
    }, 700)
    return () => clearTimeout(t)
  }, [step, done, onComplete])

  const moduleMap: Record<string, string> = {}
  for (let i = 0; i <= step && i < BOOT_STEPS.length; i++) {
    const b = BOOT_STEPS[i]
    moduleMap[b.module] = b.status
  }

  return (
    <div style={{ position:'fixed', inset:0, background:'var(--os-void)', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', overflow:'hidden' }}>
      
      {/* Background Ambient Grid */}
      <div className="ambient-grid" />
      <div className="volumetric-light" />
      <div className="scanlines" />

      {/* Cinematic Minimalist Rings (Replaces rocky planet) */}
      <div style={{ position:'relative', width: 340, height: 340, marginBottom: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <motion.div 
          animate={{ background: `radial-gradient(circle, var(--os-primary-dim) 0%, transparent 60%)` }}
          transition={{ duration: 2, repeat: Infinity, repeatType: 'reverse' }}
          style={{ position: 'absolute', width: 140, height: 140, borderRadius: '50%', opacity: 0.15, mixBlendMode: 'screen' }}
        />
        <svg width="340" height="340" viewBox="0 0 340 340" style={{ position: 'absolute', pointerEvents: 'none', overflow: 'visible' }}>
          <circle cx="170" cy="170" r="120" fill="none" stroke="var(--os-primary-dim)" strokeWidth="1.5" opacity="0.3" />
          <motion.circle cx="170" cy="170" r="140" fill="none" stroke="var(--os-primary)" strokeWidth="0.5" strokeDasharray="4 8" opacity="0.4"
            animate={{ rotate: 360 }} transition={{ duration: 40, repeat: Infinity, ease: 'linear' }} style={{ transformOrigin: '50% 50%' }} />
          <motion.circle cx="170" cy="170" r="160" fill="none" stroke="var(--os-primary)" strokeWidth="2" strokeDasharray="80 120 40 120" opacity="0.6"
            animate={{ rotate: -360 }} transition={{ duration: 60, repeat: Infinity, ease: 'linear' }} style={{ transformOrigin: '50% 50%' }} />
        </svg>
      </div>

      {/* Title */}
      <div style={{ textAlign:'center', marginBottom:20 }}>
        <div className="font-tech" style={{
          fontSize: 48, fontWeight: 300,
          letterSpacing: '0.25em', color: 'var(--os-primary)',
          textShadow: '0 0 20px var(--os-primary-dim)'
        }}>
          C.E.R.E.S
        </div>
        <div className="font-tech" style={{ fontSize:10, letterSpacing:'0.28em', color:'var(--os-text-dim)', marginTop:15 }}>
          COGNITIVE ENHANCED RESPONSE & EXECUTION SYSTEM
        </div>
      </div>

      {/* Progress */}
      <div style={{ width:400, marginBottom:10 }}>
        <div style={{ height: 1, background: 'var(--os-grid)' }}>
          <motion.div animate={{ width: `${progress}%` }} transition={{ duration: 0.5, ease: 'easeOut' }}
            style={{ height: '100%', background: 'var(--os-primary)', boxShadow: '0 0 10px var(--os-primary)' }} />
        </div>
      </div>

      {/* Boot message */}
      <AnimatePresence mode="wait">
        <motion.div key={step} initial={{ opacity:0, y: 5 }} animate={{ opacity:1, y: 0 }} exit={{ opacity:0, y: -5 }}
          className="font-mono" style={{ fontSize: 11, color: 'var(--os-text)', letterSpacing: '0.1em', height: 18, textAlign: 'center' }}>
          {step < BOOT_STEPS.length ? BOOT_STEPS[step].msg : ''}
        </motion.div>
      </AnimatePresence>

      {/* Bottom corners HUD */}
      <div style={{ position:'absolute', bottom:40, left:40, right:40, display:'flex', justifyContent:'space-between' }}>
        {/* System Status */}
        <div className="spatial-panel" style={{ padding: '15px 20px', width: 220, border: 'none', background: 'transparent' }}>
          <div className="font-tech" style={{ fontSize: 10, color: 'var(--os-text-dim)', letterSpacing: '0.2em', marginBottom: 12 }}>
            SYSTEM STATUS
          </div>
          {[['CPU',cpuPct],['RAM',ramPct]].map(([l,v]) => (
            <div key={l as string} style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
              <span className="font-mono" style={{ fontSize:10, color:'var(--os-text)', width:32 }}>{l as string}</span>
              <div style={{ flex: 1, height:1, background:'var(--os-grid)', overflow:'hidden' }}>
                <div style={{ width:`${v}%`, height:'100%', background: 'var(--os-primary)' }} />
              </div>
              <span className="font-mono" style={{ fontSize:10, color:'var(--os-primary)' }}>{v}%</span>
            </div>
          ))}
          <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:12 }}>
            <motion.div animate={{ opacity:[0.3,1,0.3] }} transition={{ duration:2, repeat:Infinity }}
              style={{ width:4, height:4, borderRadius:'50%', background:'var(--os-success)', boxShadow:'0 0 5px var(--os-success)' }} />
            <span className="font-tech" style={{ fontSize:9, color:'var(--os-success)' }}>NET ONLINE</span>
          </div>
        </div>

        {/* AI Modules */}
        <div className="spatial-panel" style={{ padding: '15px 20px', width: 250, border: 'none', background: 'transparent', textAlign: 'right' }}>
          <div className="font-tech" style={{ fontSize: 10, color: 'var(--os-text-dim)', letterSpacing: '0.2em', marginBottom: 12 }}>
            AI MODULES
          </div>
          {['Neural Core','Voice Engine','Vision System','Security'].map(name => {
            const status = moduleMap[name] || 'STANDBY'
            const color = status === 'STANDBY' ? 'var(--os-text-dim)' : (status === 'LOADING' ? 'var(--os-primary)' : 'var(--os-success)')
            return (
              <div key={name} style={{ display:'flex', justifyContent:'flex-end', alignItems:'center', gap:10, marginBottom:8 }}>
                <span className="font-mono" style={{ fontSize:10, color: 'var(--os-text)', letterSpacing:'0.05em' }}>
                  {name} <span style={{ color }}>{status}</span>
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
