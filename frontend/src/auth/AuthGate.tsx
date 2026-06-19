import { useEffect, useState, ReactNode } from 'react'
import { getSession, login } from './cognito'

interface AuthGateProps {
  children: ReactNode
}

export function AuthGate({ children }: AuthGateProps) {
  const [authed, setAuthed] = useState<boolean | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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

  if (authed) {
    return <>{children}</>
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      setAuthed(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center px-6 relative overflow-hidden">
      <div className="ambient-orb w-96 h-96 bg-accent top-[-10rem] right-[-10rem]" />
      <div className="ambient-orb w-72 h-72 bg-violet-neon bottom-[-5rem] left-[-5rem]" />

      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-5 relative z-10">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold text-gradient">Sārathi</h1>
          <p className="text-zinc-500 text-sm">Your research charioteer</p>
        </div>

        {error && (
          <div className="text-red-400 text-sm text-center bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-4 py-3 glass-card rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-accent/50"
          autoComplete="email"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-4 py-3 glass-card rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-accent/50"
          autoComplete="current-password"
        />
        <button
          type="submit"
          disabled={loading}
          className="w-full py-3 bg-accent hover:bg-accent-light text-white font-medium rounded-xl disabled:opacity-50 transition-all shadow-glow"
        >
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
