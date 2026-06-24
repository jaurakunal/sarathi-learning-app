import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Pause, Play, Trash2, MessageCircle } from 'lucide-react'
import { apiFetch } from '../api/client'
import { Layout } from '../components/Layout'
import { logout } from '../auth/cognito'

export function Settings() {
  const navigate = useNavigate()
  const [paused, setPaused] = useState(false)
  const [pauseLoading, setPauseLoading] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [deleteLoading, setDeleteLoading] = useState(false)

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
            <div className="feed-card rounded-xl p-5 border-red-500/20">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-white">Delete account & all data</h3>
                  <p className="text-xs text-zinc-500 mt-1">Removes all papers, conversations, profile, and engagement data permanently.</p>
                </div>
                {!deleteConfirm ? (
                  <button
                    onClick={() => setDeleteConfirm(true)}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-red-400 border border-red-400/20 rounded-lg hover:bg-red-400/10 transition-colors"
                  >
                    <Trash2 size={14} /> Delete
                  </button>
                ) : (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={deleteAccount}
                      disabled={deleteLoading}
                      className="px-3 py-2 text-xs text-white bg-red-500 rounded-lg hover:bg-red-600 disabled:opacity-50"
                    >
                      {deleteLoading ? 'Deleting...' : 'Confirm delete'}
                    </button>
                    <button
                      onClick={() => setDeleteConfirm(false)}
                      className="px-3 py-2 text-xs text-zinc-400 hover:text-white"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
    </Layout>
  )
}
