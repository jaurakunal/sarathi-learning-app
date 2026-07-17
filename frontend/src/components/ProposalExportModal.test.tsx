import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ProposalExportModal } from './ProposalExportModal'

vi.mock('../api/proposal', () => ({
  generateProposal: vi.fn(),
}))

import { generateProposal } from '../api/proposal'

const mockGen = vi.mocked(generateProposal)

const areas = [
  { id: 'a1', name: 'AI clone', status: 'active', frontier: '', last_engaged: null },
  { id: 'a2', name: 'Security', status: 'active', frontier: '', last_engaged: null },
  { id: 'a3', name: 'Archived Area', status: 'archived', frontier: '', last_engaged: null },
]

describe('ProposalExportModal', () => {
  beforeEach(() => vi.resetAllMocks())

  it('does not render when closed', () => {
    render(<ProposalExportModal open={false} onClose={() => {}} areas={areas} />)
    expect(screen.queryByText('Export research proposal')).not.toBeInTheDocument()
  })

  it('renders scope options and hides archived areas', () => {
    render(<ProposalExportModal open={true} onClose={() => {}} areas={areas} />)
    expect(screen.getByText('Export research proposal')).toBeInTheDocument()
    expect(screen.getByLabelText('Entire workspace')).toBeInTheDocument()
    expect(screen.getByLabelText('AI clone')).toBeInTheDocument()
    expect(screen.getByLabelText('Security')).toBeInTheDocument()
    expect(screen.queryByLabelText('Archived Area')).not.toBeInTheDocument()
  })

  it('calls generateProposal with bundle mode by default', async () => {
    mockGen.mockResolvedValue({
      markdown: '# hello\n',
      filename: 'ai-clone-context-2026-07-17.md',
      papers_included: 3,
      pinned_insights_included: 1,
      generated_at: '2026-07-17T00:00:00Z',
      mode: 'bundle',
    })

    render(<ProposalExportModal open={true} onClose={() => {}} areas={areas} />)
    fireEvent.click(screen.getByRole('button', { name: /Generate/i }))

    await waitFor(() => {
      expect(mockGen).toHaveBeenCalledWith({ mode: 'bundle', area_id: null })
    })
    // preview shows the returned markdown
    expect(await screen.findByText(/hello/)).toBeInTheDocument()
  })

  it('switches to full mode and includes area_id in the request', async () => {
    mockGen.mockResolvedValue({
      markdown: '# draft\n',
      filename: 'ai-clone-proposal-2026-07-17.md',
      papers_included: 5,
      pinned_insights_included: 2,
      generated_at: '2026-07-17T00:00:00Z',
      mode: 'full',
    })

    render(<ProposalExportModal open={true} onClose={() => {}} areas={areas} />)

    fireEvent.click(screen.getByLabelText('AI clone'))
    // Full mode radio — click the input near "Full draft"
    fireEvent.click(screen.getByRole('radio', { name: /Full draft/i }))
    fireEvent.click(screen.getByRole('button', { name: /Generate/i }))

    await waitFor(() => {
      expect(mockGen).toHaveBeenCalledWith({ mode: 'full', area_id: 'a1' })
    })
  })

  it('renders error message on failure', async () => {
    mockGen.mockRejectedValue(new Error('boom'))
    render(<ProposalExportModal open={true} onClose={() => {}} areas={areas} />)
    fireEvent.click(screen.getByRole('button', { name: /Generate/i }))
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('shows Download button once result is loaded', async () => {
    mockGen.mockResolvedValue({
      markdown: '# md\n',
      filename: 'x.md',
      papers_included: 1,
      pinned_insights_included: 0,
      generated_at: '2026-07-17T00:00:00Z',
      mode: 'bundle',
    })
    render(<ProposalExportModal open={true} onClose={() => {}} areas={areas} />)
    fireEvent.click(screen.getByRole('button', { name: /Generate/i }))
    expect(await screen.findByRole('button', { name: /Download/i })).toBeInTheDocument()
  })
})
