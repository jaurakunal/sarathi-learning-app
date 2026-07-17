import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Download, FileText, Sparkles, Loader2 } from 'lucide-react'
import { generateProposal, type ProposalMode, type ProposalResponse } from '../api/proposal'
import type { AreaInfo } from '../api/profile'

interface ProposalExportModalProps {
  open: boolean
  onClose: () => void
  areas: AreaInfo[]
}

function downloadMarkdown(filename: string, markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function ProposalExportModal({ open, onClose, areas }: ProposalExportModalProps) {
  const [mode, setMode] = useState<ProposalMode>('bundle')
  const [areaId, setAreaId] = useState<string>('')  // '' = whole workspace
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ProposalResponse | null>(null)

  useEffect(() => {
    if (!open) {
      // Reset when closed so the next open is fresh.
      setResult(null)
      setError('')
      setLoading(false)
    }
  }, [open])

  const activeAreas = useMemo(
    () => areas.filter((a) => a.status !== 'archived'),
    [areas],
  )

  const handleGenerate = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const r = await generateProposal({ mode, area_id: areaId || null })
      setResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = () => {
    if (result) downloadMarkdown(result.filename, result.markdown)
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 z-40"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="fixed inset-0 z-50 flex items-center justify-center px-4 pointer-events-none"
            role="dialog"
            aria-label="Export research proposal"
          >
            <div className="pointer-events-auto w-full max-w-lg bg-[#0e0e18] border border-white/[0.08] rounded-2xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <FileText size={18} className="text-accent" /> Export research proposal
                </h2>
                <button
                  onClick={onClose}
                  className="text-zinc-400 hover:text-white p-1"
                  aria-label="Close"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
                {/* Area */}
                <div>
                  <p className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Scope</p>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-sm text-zinc-200 cursor-pointer">
                      <input
                        type="radio"
                        name="area"
                        value=""
                        checked={areaId === ''}
                        onChange={() => setAreaId('')}
                        className="accent-accent"
                      />
                      Entire workspace
                    </label>
                    {activeAreas.map((a) => (
                      <label
                        key={a.id}
                        className="flex items-center gap-2 text-sm text-zinc-200 cursor-pointer"
                      >
                        <input
                          type="radio"
                          name="area"
                          value={a.id}
                          checked={areaId === a.id}
                          onChange={() => setAreaId(a.id)}
                          className="accent-accent"
                        />
                        {a.name}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Mode */}
                <div>
                  <p className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Output</p>
                  <div className="space-y-2">
                    <label className="flex items-start gap-2 text-sm text-zinc-200 cursor-pointer">
                      <input
                        type="radio"
                        name="mode"
                        value="bundle"
                        checked={mode === 'bundle'}
                        onChange={() => setMode('bundle')}
                        className="mt-1 accent-accent"
                      />
                      <span>
                        <span className="font-medium">Context bundle</span>{' '}
                        <span className="text-xs text-accent">(recommended)</span>
                        <br />
                        <span className="text-xs text-zinc-500">
                          Structured .md you can paste into any LLM to draft your proposal in your voice.
                        </span>
                      </span>
                    </label>
                    <label className="flex items-start gap-2 text-sm text-zinc-200 cursor-pointer">
                      <input
                        type="radio"
                        name="mode"
                        value="full"
                        checked={mode === 'full'}
                        onChange={() => setMode('full')}
                        className="mt-1 accent-accent"
                      />
                      <span>
                        <span className="font-medium">Full draft</span>
                        <br />
                        <span className="text-xs text-zinc-500">
                          Problem → approach → existing research → what's new → next steps. Generated with an LLM.
                        </span>
                      </span>
                    </label>
                  </div>
                </div>

                {/* Preview */}
                {result && (
                  <div>
                    <div className="text-xs text-zinc-500 mb-1">
                      {result.papers_included} papers · {result.pinned_insights_included} pinned insights
                    </div>
                    <pre className="text-xs text-zinc-300 bg-white/[0.03] border border-white/[0.06] rounded-lg p-3 max-h-64 overflow-auto whitespace-pre-wrap font-mono">
                      {result.markdown.slice(0, 4000)}
                      {result.markdown.length > 4000 && '\n\n… (truncated preview — full text in download)'}
                    </pre>
                  </div>
                )}

                {error && (
                  <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg p-3">
                    {error}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-white/[0.06] flex items-center justify-end gap-2">
                {result ? (
                  <>
                    <button
                      onClick={handleGenerate}
                      disabled={loading}
                      className="px-4 py-2 rounded-lg text-sm text-zinc-300 hover:text-white transition-colors"
                    >
                      Regenerate
                    </button>
                    <button
                      onClick={handleDownload}
                      className="px-4 py-2 rounded-lg text-sm bg-accent hover:bg-accent-light text-white shadow-glow flex items-center gap-2"
                    >
                      <Download size={14} /> Download .md
                    </button>
                  </>
                ) : (
                  <button
                    onClick={handleGenerate}
                    disabled={loading}
                    className="px-4 py-2 rounded-lg text-sm bg-accent hover:bg-accent-light text-white shadow-glow flex items-center gap-2 disabled:opacity-60"
                  >
                    {loading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                    {loading ? 'Generating…' : 'Generate'}
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
