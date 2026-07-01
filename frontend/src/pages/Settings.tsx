import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Pause, Play, Trash2, MessageCircle, Edit2, Archive, Plus } from 'lucide-react'
import { apiFetch } from '../api/client'
import { Layout } from '../components/Layout'
import { logout } from '../auth/cognito'
import { archiveWorkspace, updateWorkspace } from '../api/workspaces'
import { useActiveWorkspace, useWorkspaces } from '../hooks/useActiveWorkspace'

interface SettingsResponse {
  pipeline_status: string
  paused_reason?: string
  global_status?: string
  workspaces?: { workspace_id: string; name: string; status: string; paused_reason: string }[]
  active_workspace_id?: string
}

function getSettings(): Promise<SettingsResponse> {
  return apiFetch('/settings')
}

export function Settings() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: settings, refetch: refetchSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  })
  const active = useActiveWorkspace()
  const list = useWorkspaces()

  const [paused, setPaused] = useState(false)
  const [pauseLoading, setPauseLoading] = useState(false)
  const [renameTarget, setRenameTarget] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [archiveTarget, setArchiveTarget] = useState<string | null>(null)
  const [archiveInput, setArchiveInput] = useState('')
  const [archiveLoading, setArchiveLoading] = useState(false)

  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [deleteInput, setDeleteInput] = useState('')
  const [deleteLoading, setDeleteLoading] = useState(false)

  useEffect(() => {
    if (settings) {
      setPaused(settings.pipeline_status === 'paused')
    }
  }, [settings])

  async function togglePauseActive() {
    setPauseLoading(true)
    try {
      const newStatus = paused ? 'active' : 'paused'
      await apiFetch('/settings', {
        method: 'PUT',
        body: JSON.stringify({ pipeline_status: newStatus, scope: 'workspace' }),
      })
      setPaused(!paused)
      refetchSettings()
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    } catch {
      // ignore
    } finally {
      setPauseLoading(false)
    }
  }

  async function pauseAll() {
    setPauseLoading(true)
    try {
      await apiFetch('/settings', {
        method: 'PUT',
        body: JSON.stringify({ pipeline_status: 'paused', scope: 'all' }),
      })
      refetchSettings()
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    } finally {
      setPauseLoading(false)
    }
  }

  async function rename(workspaceId: string) {
    if (!renameValue.trim()) return
    try {
      await updateWorkspace(workspaceId, { name: renameValue.trim() })
      setRenameTarget(null)
      setRenameValue('')
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    } catch {
      // ignore
    }
  }

  async function doArchive(workspaceId: string) {
    setArchiveLoading(true)
    try {
      await archiveWorkspace(workspaceId)
      setArchiveTarget(null)
      setArchiveInput('')
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    } finally {
      setArchiveLoading(false)
    }
  }

  async function deleteAccount() {
    setDeleteLoading(true)
    try {
      await apiFetch('/account', { method: 'DELETE' })
      logout()
      window.location.reload()
    } catch {
      setDeleteLoading(false)
    }
  }

  const workspaces = (list.data?.workspaces || []).filter((w) => w.status !== 'archived')

  return (
    <Layout>
      <div className="min-h-screen bg-[#0a0a0f] relative">
        <div className="max-w-lg lg:max-w-2xl mx-auto px-4 pt-safe-top pb-safe-bottom relative z-10">
          <div className="glass-header sticky top-0 z-20 -mx-4 px-4 py-4">
            <div className="flex items-center gap-4">
              <button
                onClick={() => navigate('/')}
                className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center gap-1 lg:hidden"
              >
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

            {/* Workspaces management */}
            <div className="feed-card feed-card--unread rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-white">Workspaces</h3>
                <button
                  onClick={() => navigate('/onboarding?new=true')}
                  className="flex items-center gap-2 px-3 py-2 text-xs text-accent border border-accent/20 rounded-lg hover:bg-accent/10 transition-colors"
                >
                  <Plus size={14} /> New
                </button>
              </div>
              <div className="space-y-3">
                {workspaces.map((ws) => (
                  <div
                    key={ws.workspace_id}
                    className="p-3 rounded-lg border border-white/[0.06] bg-white/[0.02] flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      {renameTarget === ws.workspace_id ? (
                        <input
                          type="text"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') rename(ws.workspace_id) }}
                          className="bg-[#11111d] border border-white/[0.1] rounded px-2 py-1 text-sm text-white"
                        />
                      ) : (
                        <p className="text-sm text-white truncate">{ws.name}</p>
                      )}
                      <p className="text-xs text-zinc-500 mt-0.5">
                        {ws.status === 'paused' ? `Paused${ws.paused_reason ? ` (${ws.paused_reason})` : ''}` : 'Active'}
                        {ws.workspace_id === active.data?.active_workspace_id && ' · current'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {renameTarget === ws.workspace_id ? (
                        <button
                          onClick={() => rename(ws.workspace_id)}
                          className="text-xs text-accent"
                        >
                          Save
                        </button>
                      ) : (
                        <>
                          <button
                            onClick={() => { setRenameTarget(ws.workspace_id); setRenameValue(ws.name) }}
                            className="p-1.5 text-zinc-400 hover:text-white"
                            title="Rename"
                          >
                            <Edit2 size={14} />
                          </button>
                          <button
                            onClick={() => setArchiveTarget(ws.workspace_id)}
                            className="p-1.5 text-zinc-400 hover:text-red-400"
                            title="Archive"
                          >
                            <Archive size={14} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {archiveTarget && (
                <div className="mt-4 p-4 rounded-lg border border-red-500/30 bg-red-500/5 space-y-3">
                  <p className="text-sm text-red-300 font-medium">Archive this workspace?</p>
                  <p className="text-xs text-zinc-400">
                    The workspace will be hidden, and its pipeline will stop running. Data is kept; it can be reactivated later by a developer.
                  </p>
                  <p className="text-xs text-zinc-300">
                    Type <span className="font-mono font-bold text-red-400">CONFIRM</span> to proceed:
                  </p>
                  <input
                    type="text"
                    value={archiveInput}
                    onChange={(e) => setArchiveInput(e.target.value)}
                    placeholder="Type CONFIRM"
                    className="w-full px-3 py-2 bg-white/[0.04] border border-red-500/20 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-red-500/50 font-mono"
                  />
                  <div className="flex gap-3">
                    <button
                      onClick={() => archiveTarget && doArchive(archiveTarget)}
                      disabled={archiveLoading || archiveInput !== 'CONFIRM'}
                      className="px-4 py-2 text-xs text-white bg-red-500 rounded-lg hover:bg-red-600 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    >
                      {archiveLoading ? 'Archiving...' : 'Archive workspace'}
                    </button>
                    <button
                      onClick={() => { setArchiveTarget(null); setArchiveInput('') }}
                      className="px-3 py-2 text-xs text-zinc-400 hover:text-white transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Pipeline pause for active workspace */}
            <div className="feed-card feed-card--unread rounded-xl p-5">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-white">Paper discovery (active workspace)</h3>
                  <p className="text-xs text-zinc-500 mt-1">
                    {paused
                      ? 'Paused — no new papers will be added to this workspace'
                      : 'Active — new papers discovered nightly'}
                  </p>
                </div>
                <button
                  onClick={togglePauseActive}
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
              <div className="mt-3 pt-3 border-t border-white/[0.04]">
                <button
                  onClick={pauseAll}
                  disabled={pauseLoading}
                  className="text-xs text-zinc-400 hover:text-amber-400"
                >
                  Pause all workspaces
                </button>
              </div>
            </div>

            {/* Danger zone */}
            <div className="mt-8 pt-6 border-t border-red-500/10">
              <h2 className="text-xs text-red-400/70 uppercase tracking-wide font-medium mb-3">Danger zone</h2>
              <div className="feed-card rounded-xl p-5 border border-red-500/20">
                <h3 className="text-sm font-medium text-white">Delete account & all data</h3>
                <p className="text-xs text-zinc-500 mt-2">
                  Removes ALL workspaces, papers, conversations, profile, and engagement data permanently.
                </p>

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
                    <p className="text-xs text-zinc-400">
                      All your data will be permanently deleted across every workspace — papers, conversations, research tags, pinned insights, profile, and your login. You will not be able to recover any of it.
                    </p>
                    <p className="text-xs text-zinc-300 mt-2">
                      Type <span className="font-mono font-bold text-red-400">CONFIRM</span> to proceed:
                    </p>
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
