import { useEffect, useState, ReactNode } from 'react'
import { getSession } from './cognito'

interface AuthGateProps {
  children: ReactNode
  fallback: ReactNode
}

export function AuthGate({ children, fallback }: AuthGateProps) {
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    getSession().then((session) => {
      setAuthed(session !== null)
    })
  }, [])

  if (authed === null) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  return <>{authed ? children : fallback}</>
}
