import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Pause, Play, Trash2, MessageCircle } from 'lucide-react'
import { apiFetch } from '../api/client'
import { Layout } from '../components/Layout'
import { logout } from '../auth/cognito'

function getSettings(): Promise<{ pipeline_status: string }> {
  return apiFetch('/settings')
}

export function Settings() {
  const navigate = useNavigate()
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  })
  const [paused, setPaused] = useState(false)
  const [pauseLoading, setPauseLoading] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [deleteInput, setDeleteInput] = useState('')
  const [deleteLoading, setDeleteLoading] = useState(false)

  useEffect(() => {
    if (settings) {
      setPaused(settings.pipeline_status === 'paused')
    }
  }, [settings])

  async function togglePause() {
    setPauseLoading(true)
    try {
      const newStatus = paused ? 'active' : 'paused'
      await apiFetch('/settings/pipeline', {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus }),
      })
      setPaused(!paused)
    } catch {
      // Non-critical
    } finally {
      setPauseLoading(false)
    }
  }

  async function deleteAccount() {
    setDeleteLoading(true)
    try {
      await apiFetch('/settings/delete-account', { method: 'DELETE' })
      logout()
      window.location.reload()
    } catch {
      setDeleteLoading(false)
    }
  }

  return (
    <Layout>
    <div className="min-h-screen bg-[#0a0a0f] relative">
      <div className="max-w-lg lg:max-w-2xl mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">

        <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate('/')} className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1 lg:hidden">
              <ArrowLeft size={18} /> Back
            </button>
            <h1 className="text-sm font-semibold text-zinc-300 lg:text-xl lg:font-bold lg:text-gradient">Settings</h1>
          </div>
        </div>

        <div className="mt-6 space-y-6">

          {/* Onboarding */}
          <div className="feed-card feed-card--unread rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-white">Onboarding conversation</h3>
                <p className="text-xs text-zinc-500 mt-1">Review or update your research profile</p>
              </div>
              <button
                onClick={() => navigate('/onboarding')}
                className="flex items-center gap-2 px-3 py-2 text-xs text-accent border border-accent/20 rounded-lg hover:bg-accent/10 transition-colors"
              >
                <MessageCircle size={14} /> Open
              </button>
            </div>
          </div>

          {/* Pipeline pause */}
          <div className="feed-card feed-card--unread rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-white">Paper discovery</h3>
                <p className="text-xs text-zinc-500 mt-1">
                  {paused ? 'Paused — no new papers will be added to your feed' : 'Active — new papers discovered nightly'}
                </p>
              </div>
              <button
                onClick={togglePause}
                disabled={pauseLoading}
                className={`flex items-center gap-2 px-3 py-2 text-xs rounded-lg transition-colors ${
                  paused
                    ? 'text-green-400 border border-green-400/20 hover:bg-green-400/10'
                    : 'text-amber-400 border border-amber-400/20 hover:bg-amber-400/10'
                }`}
              >
                {paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}
              </button>
            </div>
          </div>

          {/* Danger zone */}
          <div className="mt-8 pt-6 border-t border-red-500/10">
            <h2 className="text-xs text-red-400/70 uppercase tracking-wide font-medium mb-3">Danger zone</h2>
            <div className="feed-card rounded-xl p-5 border border-red-500/20">
              <h3 className="text-sm font-medium text-white">Delete account & all data</h3>
              <p className="text-xs text-zinc-500 mt-2">Removes all papers, conversations, profile, and engagement data permanently.</p>

              {!deleteConfirm ? (
                <button
                  onClick={() => setDeleteConfirm(true)}
                  className="mt-4 flex items-center gap-2 px-3 py-2 text-xs text-red-400 border border-red-400/20 rounded-lg hover:bg-red-400/10 transition-colors"
                >
                  <Trash2 size={14} /> Delete my account
                </button>
              ) : (
                <div className="mt-4 p-4 rounded-lg border border-red-500/30 bg-red-500/5 space-y-3">
                  <p className="text-sm text-red-300 font-medium">This action cannot be undone.</p>
                  <p className="text-xs text-zinc-400">All your data will be permanently deleted — papers, conversations, research tags, pinned insights, profile, and your login. You will not be able to recover any of it.</p>
                  <p className="text-xs text-zinc-300 mt-2">Type <span className="font-mono font-bold text-red-400">CONFIRM</span> to proceed:</p>
                  <input
                    type="text"
                    value={deleteInput}
                    onChange={(e) => setDeleteInput(e.target.value)}
                    placeholder="Type CONFIRM"
                    className="w-full px-3 py-2 bg-white/[0.04] border border-red-500/20 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-red-500/50 font-mono"
                  />
                  <div className="flex gap-3">
                    <button
                      onClick={deleteAccount}
                      disabled={deleteLoading || deleteInput !== 'CONFIRM'}
                      className="px-4 py-2 text-xs text-white bg-red-500 rounded-lg hover:bg-red-600 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    >
                      {deleteLoading ? 'Deleting...' : 'Permanently delete everything'}
                    </button>
                    <button
                      onClick={() => { setDeleteConfirm(false); setDeleteInput('') }}
                      className="px-3 py-2 text-xs text-zinc-400 hover:text-white transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
    </Layout>
  )
}
