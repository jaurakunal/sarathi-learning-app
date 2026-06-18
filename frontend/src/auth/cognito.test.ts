import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockGetSession, mockSignOut, mockGetCurrentUser } = vi.hoisted(() => {
  const mockGetSession = vi.fn()
  const mockSignOut = vi.fn()
  const mockGetCurrentUser = vi.fn()
  return { mockGetSession, mockSignOut, mockGetCurrentUser }
})

vi.mock('amazon-cognito-identity-js', () => {
  return {
    CognitoUserPool: vi.fn().mockImplementation(() => ({
      getCurrentUser: mockGetCurrentUser,
    })),
    CognitoUser: vi.fn().mockImplementation(() => ({
      authenticateUser: vi.fn(),
    })),
    AuthenticationDetails: vi.fn(),
  }
})

import { getSession, getIdToken, logout, getLoginUrl } from './cognito'

describe('cognito auth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetCurrentUser.mockReturnValue({
      getSession: mockGetSession,
      signOut: mockSignOut,
    })
  })

  describe('getSession', () => {
    it('returns session when valid', async () => {
      const mockSession = { isValid: () => true, getIdToken: () => ({ getJwtToken: () => 'jwt' }) }
      mockGetSession.mockImplementation((cb: Function) => cb(null, mockSession))

      const session = await getSession()
      expect(session).toBe(mockSession)
    })

    it('returns null when session invalid', async () => {
      const mockSession = { isValid: () => false }
      mockGetSession.mockImplementation((cb: Function) => cb(null, mockSession))

      const session = await getSession()
      expect(session).toBeNull()
    })

    it('returns null on error', async () => {
      mockGetSession.mockImplementation((cb: Function) => cb(new Error('expired'), null))

      const session = await getSession()
      expect(session).toBeNull()
    })

    it('returns null when no current user', async () => {
      mockGetCurrentUser.mockReturnValue(null)

      const session = await getSession()
      expect(session).toBeNull()
    })
  })

  describe('getIdToken', () => {
    it('returns JWT string from valid session', async () => {
      const mockSession = {
        isValid: () => true,
        getIdToken: () => ({ getJwtToken: () => 'my-jwt-token' }),
      }
      mockGetSession.mockImplementation((cb: Function) => cb(null, mockSession))

      const token = await getIdToken()
      expect(token).toBe('my-jwt-token')
    })

    it('returns null when no valid session', async () => {
      mockGetSession.mockImplementation((cb: Function) => cb(new Error('no'), null))

      const token = await getIdToken()
      expect(token).toBeNull()
    })
  })

  describe('logout', () => {
    it('calls signOut on current user', () => {
      logout()
      expect(mockSignOut).toHaveBeenCalled()
    })

    it('does nothing when no current user', () => {
      mockGetCurrentUser.mockReturnValue(null)
      expect(() => logout()).not.toThrow()
    })
  })

  describe('getLoginUrl', () => {
    it('constructs hosted UI URL with correct params', () => {
      const url = getLoginUrl()
      expect(url).toContain('login?client_id=')
      expect(url).toContain('response_type=code')
      expect(url).toContain('scope=openid+email')
      expect(url).toContain('redirect_uri=')
    })
  })
})
