import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Send, Check, Bug, Lightbulb, MessageSquare } from 'lucide-react'
import { sendFeedback, type FeedbackCategory } from '../api/feedback'

interface FeedbackModalProps {
  open: boolean
  onClose: () => void
}

const CATEGORIES: { key: FeedbackCategory; label: string; icon: typeof Bug }[] = [
  { key: 'bug', label: 'Bug', icon: Bug },
  { key: 'idea', label: 'Idea', icon: Lightbulb },
  { key: 'other', label: 'Other', icon: MessageSquare },
]

export function FeedbackModal({ open, onClose }: FeedbackModalProps) {
  const [category, setCategory] = useState<FeedbackCategory>('bug')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const reset = () => {
    setCategory('bug'); setMessage(''); setSending(false); setSent(false); setError('')
  }

  const close = () => { reset(); onClose() }

  const submit = async () => {
    if (!message.trim()) return
    setSending(true); setError('')
    try {
      await sendFeedback(message.trim(), category)
      setSent(true)
      setTimeout(close, 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to send')
      setSending(false)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 z-40" onClick={close}
          />
          <motion.div
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 20 }}
            className="fixed inset-0 z-50 flex items-center justify-center px-4 pointer-events-none"
            role="dialog" aria-label="Send feedback"
          >
            <div className="pointer-events-auto w-full max-w-md bg-[#0e0e18] border border-white/[0.08] rounded-2xl shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
                <h2 className="text-lg font-semibold text-white">Send feedback</h2>
                <button onClick={close} className="text-zinc-400 hover:text-white p-1" aria-label="Close">
                  <X size={18} />
                </button>
              </div>

              {sent ? (
                <div className="px-6 py-10 text-center space-y-3">
                  <div className="w-12 h-12 rounded-full bg-accent/15 border border-accent-dim flex items-center justify-center mx-auto">
                    <Check size={22} className="text-accent" />
                  </div>
                  <p className="text-sm text-zinc-300">Thanks — got it.</p>
                </div>
              ) : (
                <div className="px-6 py-4 space-y-4">
                  <div className="flex gap-2">
                    {CATEGORIES.map(({ key, label, icon: Icon }) => (
                      <button
                        key={key}
                        onClick={() => setCategory(key)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-all ${
                          category === key
                            ? 'bg-accent/20 border-accent-dim text-white'
                            : 'border-white/[0.12] text-zinc-400 hover:text-zinc-200'
                        }`}
                      >
                        <Icon size={14} /> {label}
                      </button>
                    ))}
                  </div>
                  <textarea
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    placeholder={category === 'bug' ? "What went wrong? What did you expect?" : "What's on your mind?"}
                    rows={5}
                    autoFocus
                    className="w-full resize-none bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-accent/40"
                  />
                  {error && <p className="text-xs text-red-400">{error}</p>}
                  <div className="flex justify-end">
                    <button
                      onClick={submit}
                      disabled={sending || !message.trim()}
                      className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-light text-white text-sm font-medium rounded-lg shadow-glow disabled:opacity-50 transition-all"
                    >
                      <Send size={14} /> {sending ? 'Sending…' : 'Send'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
