import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Login } from './Login'

vi.mock('../auth/cognito', () => ({
  getSession: vi.fn(),
  login: vi.fn(),
  forgotPassword: vi.fn(),
  confirmNewPassword: vi.fn(),
  getOIDCLoginUrl: vi.fn(() => 'https://sso.example/login'),
}))

import { getSession, login } from '../auth/cognito'

const mockGetSession = vi.mocked(getSession)
const mockLogin = vi.mocked(login)

function renderLogin() {
  return render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  )
}

describe('Login', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders SSO and password form', async () => {
    mockGetSession.mockResolvedValue(null)
    renderLogin()

    await waitFor(() => {
      expect(screen.getByText('Sign in with SSO')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Email')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Password')).toBeInTheDocument()
    })
  })

  it('calls login on form submit', async () => {
    mockGetSession.mockResolvedValue(null)
    mockLogin.mockResolvedValue({ isValid: () => true } as never)
    renderLogin()

    await waitFor(() => screen.getByPlaceholderText('Email'))

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'test@example.com' } })
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('test@example.com', 'password123')
    })
  })

  it('shows error on login failure', async () => {
    mockGetSession.mockResolvedValue(null)
    mockLogin.mockRejectedValue(new Error('Incorrect username or password'))
    renderLogin()

    await waitFor(() => screen.getByPlaceholderText('Email'))

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'bad@email.com' } })
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

    await waitFor(() => {
      expect(screen.getByText('Incorrect username or password')).toBeInTheDocument()
    })
  })
})
