import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import { Send, Check } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'

interface OnboardingMessage {
  role: 'user' | 'assistant'
  content: string
}

export function Onboarding() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<OnboardingMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [profileComplete, setProfileComplete] = useState(false)
  const [profile, setProfile] = useState<any>(null)
  const [profileSummary, setProfileSummary] = useState('')
  const [confirming, setConfirming] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Load existing history or start fresh on mount
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    loadOrStart()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function stripJson(text: string): string {
    // Strip fenced JSON
    let jsonStart = text.indexOf('```json')
    if (jsonStart === -1) jsonStart = text.indexOf('```')
    if (jsonStart > -1) return text.slice(0, jsonStart).trim()
    // Strip bare JSON block
    const lines = text.split('\n')
    const braceIdx = lines.findIndex((l) => l.trim() === '{' || l.trim().startsWith('{"'))
    if (braceIdx > -1) return lines.slice(0, braceIdx).join('\n').trim()
    return text
  }

  async function loadOrStart() {
    try {
      const history = await apiFetch<{ turns: { seq: number; request: string; response: string | null }[] }>(`/chat/onboarding`)
      if (history.turns && history.turns.length > 0) {
        const restored: OnboardingMessage[] = []
        let hasJsonProfile = false
        for (const turn of history.turns) {
          if (turn.request && turn.request !== 'Hi, I just signed up.') {
            restored.push({ role: 'user', content: turn.request })
          }
          if (turn.response) {
            // Check if this response contains a profile JSON
            if (turn.response.includes('"user_profile"') || turn.response.includes('"profile_complete"') || turn.response.includes('"areas"')) {
              hasJsonProfile = true
            }
            const cleaned = stripJson(turn.response)
            if (cleaned) {
              restored.push({ role: 'assistant', content: cleaned })
            }
          }
        }
        if (restored.length > 0) {
          setMessages(restored)
          // If profile was already generated but never confirmed, trigger re-detection
          if (hasJsonProfile) {
            try {
              const res = await apiFetch<{ profile_complete?: boolean; profile?: any; profile_summary?: string; response: string }>('/onboarding', {
                method: 'POST',
                body: JSON.stringify({ message: 'Please confirm my profile.' }),
              })
              if (res.profile_complete && res.profile) {
                setProfileComplete(true)
                setProfile(res.profile)
                setProfileSummary(res.profile_summary || '')
              }
            } catch {
              // Non-critical
            }
          }
          return
        }
      }
    } catch {
      // No history — start fresh
    }
    sendMessage('')
  }

  async function sendMessage(text: string) {
    if (text) {
      setMessages((prev) => [...prev, { role: 'user', content: text }])
    }
    setInput('')
    setLoading(true)

    try {
      const res = await apiFetch<{
        response: string
        turn_seq: number
        profile_complete?: boolean
        profile_summary?: string
        profile?: any
      }>('/onboarding', {
        method: 'POST',
        body: JSON.stringify({ message: text }),
      })

      // Strip JSON from displayed message when profile is complete
      let displayResponse = res.response
      if (res.profile_complete) {
        // Try fenced JSON first
        let jsonStart = displayResponse.indexOf('```json')
        if (jsonStart === -1) jsonStart = displayResponse.indexOf('```')
        // Try bare JSON block (line starting with {)
        if (jsonStart === -1) {
          const lines = displayResponse.split('\n')
          const braceIdx = lines.findIndex((l) => l.trim() === '{' || l.trim().startsWith('{"'))
          if (braceIdx > -1) {
            jsonStart = lines.slice(0, braceIdx).join('\n').length
          }
        }
        if (jsonStart > -1) {
          displayResponse = displayResponse.slice(0, jsonStart).trim()
        }
      }

      setMessages((prev) => [...prev, { role: 'assistant', content: displayResponse }])

      if (res.profile_complete && res.profile) {
        setProfileComplete(true)
        setProfile(res.profile)
        setProfileSummary(res.profile_summary || '')
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Something went wrong. Please try again.' }])
    } finally {
      setLoading(false)
    }
  }

  async function confirmProfile() {
    setConfirming(true)
    try {
      await apiFetch('/onboarding/profile', {
        method: 'PUT',
        body: JSON.stringify({ profile }),
      })
      setConfirmed(true)
      setTimeout(() => navigate('/'), 3000)
    } catch {
      setConfirming(false)
    }
  }

  const [confirmed, setConfirmed] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading) return
    sendMessage(input.trim())
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex flex-col relative overflow-hidden">
      <div className="ambient-orb w-96 h-96 bg-accent top-[-10rem] right-[-10rem]" />
      <div className="ambient-orb w-72 h-72 bg-violet-neon bottom-[20%] left-[-8rem]" />

      {/* Header */}
      <div className="glass-header sticky top-0 z-20">
        <div className="max-w-2xl mx-auto w-full px-4 py-4 text-center">
          <h1 className="text-lg font-bold text-gradient">Welcome to Sārathi</h1>
          <p className="text-xs text-zinc-500 mt-1">Let's understand your research interests</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 max-w-2xl mx-auto w-full px-4 py-4 space-y-4 overflow-y-auto relative z-10">
        {messages.map((msg, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`max-w-[85%] lg:max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
              msg.role === 'user'
                ? 'bg-accent/20 border border-accent-dim text-white'
                : 'bg-[rgba(26,26,46,0.7)] backdrop-blur-[12px] border border-[rgba(236,72,153,0.15)] text-zinc-200'
            }`}>
              {msg.role === 'user' ? (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              ) : (
                <div className="prose prose-invert prose-sm max-w-none">
                  <Markdown>{msg.content}</Markdown>
                </div>
              )}
            </div>
          </motion.div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-[rgba(26,26,46,0.7)] rounded-2xl px-4 py-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 rounded-full bg-accent/50 animate-bounce" />
                <div className="w-2 h-2 rounded-full bg-accent/50 animate-bounce" style={{ animationDelay: '0.1s' }} />
                <div className="w-2 h-2 rounded-full bg-accent/50 animate-bounce" style={{ animationDelay: '0.2s' }} />
              </div>
            </div>
          </div>
        )}

        {/* Profile confirmation */}
        {profileComplete && !confirmed && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 rounded-xl border border-accent/30 bg-accent/5 space-y-3"
          >
            <p className="text-sm text-white font-medium">Here's what I understood:</p>
            <p className="text-sm text-zinc-300">{profileSummary}</p>
            <div className="flex gap-3">
              <button
                onClick={confirmProfile}
                disabled={confirming}
                className="flex items-center gap-2 px-4 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-light disabled:opacity-50 transition-all"
              >
                <Check size={14} />
                {confirming ? 'Setting up...' : 'Looks good — start my feed'}
              </button>
              <button
                onClick={() => {
                  setProfileComplete(false)
                  setProfile(null)
                  sendMessage("That's not quite right. Let me clarify...")
                }}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
              >
                Let me correct something
              </button>
            </div>
          </motion.div>
        )}

        {/* Success — auto-navigates in 3s */}
        {confirmed && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="p-6 rounded-xl border border-accent/30 bg-accent/5 text-center space-y-3"
          >
            <p className="text-lg font-semibold text-white">You're all set!</p>
            <p className="text-sm text-zinc-400">Your first papers are being discovered now. Taking you to your feed...</p>
            <button
              onClick={() => navigate('/')}
              className="text-sm text-accent hover:text-accent-light transition-colors"
            >
              Go to feed now →
            </button>
          </motion.div>
        )}

        {/* Escape hatch — shows after 6+ messages if profile wasn't auto-detected */}
        {!profileComplete && !confirmed && messages.length >= 6 && (
          <div className="text-center pt-4">
            <button
              onClick={() => navigate('/')}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Skip for now — go to feed →
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      {!profileComplete && (
        <div className="relative z-10 border-t border-white/[0.08] bg-[#0a0a0f]/90 backdrop-blur-sm">
          <div className="max-w-2xl mx-auto w-full px-4 py-4">
            <form onSubmit={handleSubmit} className="flex gap-2 items-end">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(e) } }}
                disabled={loading}
                placeholder="Tell me about yourself..."
                rows={1}
                className="flex-1 resize-none bg-[rgba(26,26,46,0.7)] border border-[rgba(236,72,153,0.15)] rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-accent/50 disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                className="p-3 bg-accent hover:bg-accent-light text-white rounded-xl disabled:opacity-30 transition-all shadow-glow disabled:shadow-none"
              >
                <Send size={16} />
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
