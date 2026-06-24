import { useEffect, useState, ReactNode } from 'react'
import { getSession, login, signUp, confirmSignUp } from './cognito'

interface AuthGateProps {
  children: ReactNode
}

type AuthView = 'login' | 'signup' | 'verify'

export function AuthGate({ children }: AuthGateProps) {
  const [authed, setAuthed] = useState<boolean | null>(null)
  const [view, setView] = useState<AuthView>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [verifyCode, setVerifyCode] = useState('')
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

  const handleLogin = async (e: React.FormEvent) => {
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

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await signUp(email, password)
      setView('verify')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await confirmSignUp(email, verifyCode)
      await login(email, password)
      setAuthed(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center px-6 relative overflow-hidden">
      <div className="ambient-orb w-96 h-96 bg-accent top-[-10rem] right-[-10rem]" />
      <div className="ambient-orb w-72 h-72 bg-violet-neon bottom-[-5rem] left-[-5rem]" />

      <div className="w-full max-w-sm space-y-5 relative z-10">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold text-gradient">Sārathi</h1>
          <p className="text-zinc-500 text-sm">Your research charioteer</p>
        </div>

        {error && (
          <div className="text-red-400 text-sm text-center bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {view === 'login' && (
          <form onSubmit={handleLogin} className="space-y-4">
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
            <p className="text-center text-sm text-zinc-500">
              Don't have an account?{' '}
              <button type="button" onClick={() => { setView('signup'); setError('') }} className="text-accent hover:text-accent-light">
                Sign up
              </button>
            </p>
          </form>
        )}

        {view === 'signup' && (
          <form onSubmit={handleSignUp} className="space-y-4">
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
              placeholder="Password (min 8 chars)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 glass-card rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-accent/50"
              autoComplete="new-password"
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-accent hover:bg-accent-light text-white font-medium rounded-xl disabled:opacity-50 transition-all shadow-glow"
            >
              {loading ? 'Creating account...' : 'Create account'}
            </button>
            <p className="text-center text-sm text-zinc-500">
              Already have an account?{' '}
              <button type="button" onClick={() => { setView('login'); setError('') }} className="text-accent hover:text-accent-light">
                Sign in
              </button>
            </p>
          </form>
        )}

        {view === 'verify' && (
          <form onSubmit={handleVerify} className="space-y-4">
            <p className="text-sm text-zinc-400 text-center">Check your email for a verification code.</p>
            <input
              type="text"
              placeholder="Verification code"
              value={verifyCode}
              onChange={(e) => setVerifyCode(e.target.value)}
              className="w-full px-4 py-3 glass-card rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:border-accent/50 text-center tracking-widest"
              autoComplete="one-time-code"
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-accent hover:bg-accent-light text-white font-medium rounded-xl disabled:opacity-50 transition-all shadow-glow"
            >
              {loading ? 'Verifying...' : 'Verify & continue'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
