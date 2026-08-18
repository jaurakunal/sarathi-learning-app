import { useState, useRef, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import { Send, Check } from 'lucide-react'
import { apiFetch } from '../api/client'
import { createWorkspace, setActiveWorkspace } from '../api/workspaces'
import { writeWorkspaceFallback } from '../hooks/useActiveWorkspace'

interface OnboardingMessage {
  role: 'user' | 'assistant'
  content: string
}

type Stage = 'user' | 'workspace'

interface AreaOption {
  id: string
  label: string
}

interface OnboardingStatus {
  has_user_meta: boolean
  user_onboarding_complete: boolean
  has_workspace_profile: boolean
  workspace_id: string | null
  next_stage: 'user' | 'workspace' | 'complete'
  areas_catalog?: AreaOption[]
  has_profile?: boolean
}

export function Onboarding() {
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const isNewWorkspace = search.get('new') === 'true'

  const [messages, setMessages] = useState<OnboardingMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState<Stage>('user')
  const [stageReady, setStageReady] = useState(false)

  // user-stage completion
  const [userMetaComplete, setUserMetaComplete] = useState(false)
  const [userMeta, setUserMeta] = useState<any>(null)
  const [userSummary, setUserSummary] = useState('')

  // workspace-stage completion
  const [profileComplete, setProfileComplete] = useState(false)
  const [profile, setProfile] = useState<any>(null)
  const [profileSummary, setProfileSummary] = useState('')

  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  // Dropdown fallback: pick areas from a list if the chat is degraded/skipped.
  const [areasCatalog, setAreasCatalog] = useState<AreaOption[]>([])
  const [showAreaPicker, setShowAreaPicker] = useState(false)
  const [pickedAreas, setPickedAreas] = useState<Set<string>>(new Set())

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Bootstrap: figure out the stage on mount.
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    bootstrap()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function stripJson(text: string): string {
    let jsonStart = text.indexOf('```json')
    if (jsonStart === -1) jsonStart = text.indexOf('```')
    if (jsonStart > -1) return text.slice(0, jsonStart).trim()
    const lines = text.split('\n')
    const braceIdx = lines.findIndex((l) => l.trim() === '{' || l.trim().startsWith('{"'))
    if (braceIdx > -1) return lines.slice(0, braceIdx).join('\n').trim()
    return text
  }

  async function bootstrap() {
    try {
      const status = await apiFetch<OnboardingStatus>('/onboarding')
      if (status.areas_catalog?.length) setAreasCatalog(status.areas_catalog)
      let nextStage: Stage = 'user'
      if (isNewWorkspace) {
        // User clicked "Create new workspace" — skip user-level if we already
        // have it, and create a fresh workspace.
        if (status.user_onboarding_complete || status.has_user_meta) {
          // Make a new workspace and set it active before starting the chat.
          try {
            const ws = await createWorkspace('New workspace', '')
            await setActiveWorkspace(ws.workspace.workspace_id)
            // CRITICAL: update the localStorage fallback too. client.ts stamps
            // ?workspace_id from this fallback on every request; if we only set
            // the server pointer, onboarding messages carry the OLD workspace_id
            // and get written to the previously-active workspace's conversation.
            writeWorkspaceFallback({
              workspace_id: ws.workspace.workspace_id,
              name: ws.workspace.name,
            })
          } catch {
            // If creation fails, fall through — onboarding_confirm will create
            // a Default workspace as a fallback.
          }
          nextStage = 'workspace'
        } else {
          nextStage = 'user'
        }
      } else if (status.next_stage === 'workspace') {
        nextStage = 'workspace'
      } else if (status.next_stage === 'complete') {
        navigate('/')
        return
      }
      setStage(nextStage)
      setStageReady(true)
      // Kick off the conversation
      sendMessage('', nextStage)
    } catch {
      // If the status check fails, default to user stage
      setStage('user')
      setStageReady(true)
      sendMessage('', 'user')
    }
  }

  async function sendMessage(text: string, forcedStage?: Stage) {
    const useStage = forcedStage ?? stage
    if (text) {
      setMessages((prev) => [...prev, { role: 'user', content: text }])
    }
    setInput('')
    setLoading(true)

    try {
      const res = await apiFetch<{
        stage: Stage
        response: string
        turn_seq: number
        profile_complete?: boolean
        profile_summary?: string
        profile?: any
        user_meta_complete?: boolean
        user_meta?: any
        summary?: string
        workspace_id?: string
      }>('/onboarding', {
        method: 'POST',
        body: JSON.stringify({ message: text, stage: useStage }),
      })

      let displayResponse = res.response
      if (res.profile_complete || res.user_meta_complete) {
        displayResponse = stripJson(displayResponse)
      }

      setMessages((prev) => [...prev, { role: 'assistant', content: displayResponse }])

      if (res.user_meta_complete && res.user_meta) {
        setUserMetaComplete(true)
        setUserMeta(res.user_meta)
        setUserSummary(res.summary || '')
      }
      if (res.profile_complete && res.profile) {
        setProfileComplete(true)
        setProfile(res.profile)
        setProfileSummary(res.profile_summary || '')
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Something went wrong. Please try again.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  async function confirmUserMeta() {
    setConfirming(true)
    try {
      await apiFetch('/onboarding/profile', {
        method: 'PUT',
        body: JSON.stringify({ stage: 'user', user_meta: userMeta }),
      })
      // Move to workspace stage
      setUserMetaComplete(false)
      setUserMeta(null)
      setUserSummary('')
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: "Great — I've got your profile. Now let's set up your first workspace. What do you want to research here?",
        },
      ])
      setStage('workspace')
      sendMessage('', 'workspace')
    } finally {
      setConfirming(false)
    }
  }

  async function confirmWorkspaceProfile() {
    setConfirming(true)
    try {
      await apiFetch('/onboarding/profile', {
        method: 'PUT',
        body: JSON.stringify({ stage: 'workspace', profile }),
      })
      setConfirmed(true)
      setTimeout(() => navigate('/'), 3000)
    } catch {
      setConfirming(false)
    }
  }

  // Dropdown fallback: build a minimal but valid profile from the picked areas
  // and finish onboarding without the LLM interview.
  async function confirmPickedAreas() {
    if (pickedAreas.size === 0) return
    setConfirming(true)
    try {
      const chosen = areasCatalog.filter((a) => pickedAreas.has(a.id))
      const builtProfile = {
        areas: chosen.map((a) => ({ id: a.id, label: a.label, role: 'primary' })),
        meta: {
          paper_goal: `Follow research on ${chosen.map((a) => a.label).join(', ')}.`,
        },
      }
      await apiFetch('/onboarding/profile', {
        method: 'PUT',
        body: JSON.stringify({ stage: 'workspace', profile: builtProfile }),
      })
      setConfirmed(true)
      setTimeout(() => navigate('/'), 3000)
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

      <div className="glass-header sticky top-0 z-20">
        <div className="max-w-2xl mx-auto w-full px-4 py-4 text-center">
          <h1 className="text-lg font-bold text-gradient">
            {stage === 'user' ? 'Welcome to Sārathi' : 'Set up this workspace'}
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            {stage === 'user'
              ? "Let's understand who you are"
              : "Let's understand what this workspace is for"}
          </p>
        </div>
      </div>

      <div className="flex-1 max-w-2xl mx-auto w-full px-4 py-4 space-y-4 overflow-y-auto relative z-10">
        {messages.map((msg, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] lg:max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-accent/20 border border-accent-dim text-white'
                  : 'bg-[rgba(26,26,46,0.7)] backdrop-blur-[12px] border border-[rgba(236,72,153,0.15)] text-zinc-200'
              }`}
            >
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
                <div
                  className="w-2 h-2 rounded-full bg-accent/50 animate-bounce"
                  style={{ animationDelay: '0.1s' }}
                />
                <div
                  className="w-2 h-2 rounded-full bg-accent/50 animate-bounce"
                  style={{ animationDelay: '0.2s' }}
                />
              </div>
            </div>
          </div>
        )}

        {userMetaComplete && !confirmed && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 rounded-xl border border-accent/30 bg-accent/5 space-y-3"
          >
            <p className="text-sm text-white font-medium">Here's what I understood about you:</p>
            <p className="text-sm text-zinc-300">{userSummary}</p>
            <div className="flex gap-3">
              <button
                onClick={confirmUserMeta}
                disabled={confirming}
                className="flex items-center gap-2 px-4 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-light disabled:opacity-50 transition-all"
              >
                <Check size={14} />
                {confirming ? 'Saving...' : 'Looks good — set up my workspace'}
              </button>
              <button
                onClick={() => {
                  setUserMetaComplete(false)
                  setUserMeta(null)
                  sendMessage("Let me correct something...")
                }}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
              >
                Let me correct something
              </button>
            </div>
          </motion.div>
        )}

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
                onClick={confirmWorkspaceProfile}
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

        {confirmed && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="p-6 rounded-xl border border-accent/30 bg-accent/5 text-center space-y-3"
          >
            <p className="text-lg font-semibold text-white">You're all set!</p>
            <p className="text-sm text-zinc-400">
              Your first papers are being discovered now. Taking you to your feed...
            </p>
            <button
              onClick={() => navigate('/')}
              className="text-sm text-accent hover:text-accent-light transition-colors"
            >
              Go to feed now →
            </button>
          </motion.div>
        )}

        {/* Dropdown fallback: pick areas directly. Available in the workspace
            stage so a user can always finish even if the chat is degraded. */}
        {stage === 'workspace' && !profileComplete && !confirmed && areasCatalog.length > 0 && (
          <div className="pt-4">
            {!showAreaPicker ? (
              <div className="text-center">
                <button
                  onClick={() => setShowAreaPicker(true)}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors underline underline-offset-2"
                >
                  Prefer to just pick your areas from a list?
                </button>
              </div>
            ) : (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-4 rounded-xl border border-accent/30 bg-accent/5 space-y-3"
              >
                <p className="text-sm text-white font-medium">Pick the areas you want in this workspace:</p>
                <div className="flex flex-wrap gap-2">
                  {areasCatalog.map((a) => {
                    const on = pickedAreas.has(a.id)
                    return (
                      <button
                        key={a.id}
                        onClick={() => setPickedAreas((prev) => {
                          const next = new Set(prev)
                          if (next.has(a.id)) next.delete(a.id); else next.add(a.id)
                          return next
                        })}
                        className={`px-3 py-1.5 rounded-full text-xs border transition-all ${
                          on
                            ? 'bg-accent/20 border-accent-dim text-white'
                            : 'border-white/[0.12] text-zinc-400 hover:text-zinc-200'
                        }`}
                      >
                        {a.label}
                      </button>
                    )
                  })}
                </div>
                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={confirmPickedAreas}
                    disabled={confirming || pickedAreas.size === 0}
                    className="flex items-center gap-2 px-4 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-light disabled:opacity-50 transition-all"
                  >
                    <Check size={14} />
                    {confirming ? 'Setting up...' : `Build my feed${pickedAreas.size ? ` (${pickedAreas.size})` : ''}`}
                  </button>
                  <button
                    onClick={() => setShowAreaPicker(false)}
                    className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
                  >
                    Back to chat
                  </button>
                </div>
              </motion.div>
            )}
          </div>
        )}

        {!userMetaComplete && !profileComplete && !confirmed && messages.length >= 6 && (
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

      {!userMetaComplete && !profileComplete && stageReady && (
        <div className="relative z-10 border-t border-white/[0.08] bg-[#0a0a0f]/90 backdrop-blur-sm">
          <div className="max-w-2xl mx-auto w-full px-4 py-4">
            <form onSubmit={handleSubmit} className="flex gap-2 items-end">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSubmit(e)
                  }
                }}
                disabled={loading}
                placeholder={
                  stage === 'user'
                    ? 'Tell me about yourself...'
                    : 'Tell me what this workspace is for...'
                }
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
