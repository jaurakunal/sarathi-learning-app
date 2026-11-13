import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Login } from './Login'

vi.mock('../auth/cognito', () => ({
  getSession: vi.fn(),
  login: vi.fn(),
  forgotPassword: vi.fn(),
  confirmNewPassword: vi.fn(),
  signUp: vi.fn(),
  confirmSignUp: vi.fn(),
}))

import { getSession, login, signUp, confirmSignUp } from '../auth/cognito'

const mockGetSession = vi.mocked(getSession)
const mockLogin = vi.mocked(login)
const mockSignUp = vi.mocked(signUp)
const mockConfirmSignUp = vi.mocked(confirmSignUp)

function renderLogin() {
  return render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  )
}

describe('Login', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders password form', async () => {
    mockGetSession.mockResolvedValue(null)
    renderLogin()

    await waitFor(() => {
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

  it('signs up, verifies the emailed code, then logs in', async () => {
    mockGetSession.mockResolvedValue(null)
    mockSignUp.mockResolvedValue()
    mockConfirmSignUp.mockResolvedValue()
    mockLogin.mockResolvedValue({ isValid: () => true } as never)
    renderLogin()

    await waitFor(() => screen.getByPlaceholderText('Email'))
    fireEvent.click(screen.getByRole('button', { name: /^sign up$/i }))

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'new@example.com' } })
    fireEvent.change(screen.getByPlaceholderText('Password (min 8 chars)'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => screen.getByPlaceholderText('Verification code'))
    expect(mockSignUp).toHaveBeenCalledWith('new@example.com', 'password123')

    fireEvent.change(screen.getByPlaceholderText('Verification code'), { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: /verify & continue/i }))

    await waitFor(() => {
      expect(mockConfirmSignUp).toHaveBeenCalledWith('new@example.com', '123456')
      expect(mockLogin).toHaveBeenCalledWith('new@example.com', 'password123')
    })
  })
})
