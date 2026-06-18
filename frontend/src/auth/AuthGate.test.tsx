import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AuthGate } from './AuthGate'

vi.mock('./cognito', () => ({
  getSession: vi.fn(),
  login: vi.fn(),
}))

import { getSession, login } from './cognito'

const mockGetSession = vi.mocked(getSession)
const mockLogin = vi.mocked(login)

describe('AuthGate', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows loading while checking session', () => {
    mockGetSession.mockReturnValue(new Promise(() => {}))
    const { container } = render(<AuthGate><p>Protected</p></AuthGate>)
    expect(container.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('shows children when authenticated', async () => {
    mockGetSession.mockResolvedValue({ isValid: () => true } as never)
    render(<AuthGate><p>Protected content</p></AuthGate>)

    await waitFor(() => {
      expect(screen.getByText('Protected content')).toBeInTheDocument()
    })
  })

  it('shows login form when not authenticated', async () => {
    mockGetSession.mockResolvedValue(null)
    render(<AuthGate><p>Protected</p></AuthGate>)

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Email')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Password')).toBeInTheDocument()
      expect(screen.getByText('Sign in')).toBeInTheDocument()
    })
  })

  it('calls login on form submit', async () => {
    mockGetSession.mockResolvedValue(null)
    mockLogin.mockResolvedValue({ isValid: () => true } as never)
    render(<AuthGate><p>Protected</p></AuthGate>)

    await waitFor(() => screen.getByPlaceholderText('Email'))

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'test@example.com' } })
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByText('Sign in'))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('test@example.com', 'password123')
    })
  })

  it('shows error on login failure', async () => {
    mockGetSession.mockResolvedValue(null)
    mockLogin.mockRejectedValue(new Error('Incorrect username or password'))
    render(<AuthGate><p>Protected</p></AuthGate>)

    await waitFor(() => screen.getByPlaceholderText('Email'))

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'bad@email.com' } })
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByText('Sign in'))

    await waitFor(() => {
      expect(screen.getByText('Incorrect username or password')).toBeInTheDocument()
    })
  })

  it('shows Sārathi branding', async () => {
    mockGetSession.mockResolvedValue(null)
    render(<AuthGate><p>Protected</p></AuthGate>)

    await waitFor(() => {
      expect(screen.getByText('Sārathi')).toBeInTheDocument()
    })
  })
})
