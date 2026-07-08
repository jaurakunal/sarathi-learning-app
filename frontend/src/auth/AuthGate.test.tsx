import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { AuthGate } from './AuthGate'

vi.mock('./cognito', () => ({
  getSession: vi.fn(),
}))

import { getSession } from './cognito'

const mockGetSession = vi.mocked(getSession)

describe('AuthGate', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows loading while checking session', () => {
    mockGetSession.mockReturnValue(new Promise(() => {}))
    const { container } = render(
      <AuthGate fallback={<p>Fallback</p>}><p>Protected</p></AuthGate>,
    )
    expect(container.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('renders children when authenticated', async () => {
    mockGetSession.mockResolvedValue({ isValid: () => true } as never)
    render(<AuthGate fallback={<p>Fallback</p>}><p>Protected content</p></AuthGate>)

    await waitFor(() => {
      expect(screen.getByText('Protected content')).toBeInTheDocument()
    })
    expect(screen.queryByText('Fallback')).not.toBeInTheDocument()
  })

  it('renders fallback when not authenticated', async () => {
    mockGetSession.mockResolvedValue(null)
    render(<AuthGate fallback={<p>Fallback content</p>}><p>Protected</p></AuthGate>)

    await waitFor(() => {
      expect(screen.getByText('Fallback content')).toBeInTheDocument()
    })
    expect(screen.queryByText('Protected')).not.toBeInTheDocument()
  })
})
