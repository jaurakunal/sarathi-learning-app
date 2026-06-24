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

  // Start the conversation on mount
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    sendMessage('')
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
      await apiFetch('/onboarding/confirm', {
        method: 'POST',
        body: JSON.stringify({ profile }),
      })
      navigate('/')
    } catch {
      setConfirming(false)
    }
  }

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
        {profileComplete && (
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
