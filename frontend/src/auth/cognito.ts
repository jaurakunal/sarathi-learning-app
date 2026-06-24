import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
} from 'amazon-cognito-identity-js'

const userPool = new CognitoUserPool({
  UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
  ClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
})

export function getCurrentUser(): CognitoUser | null {
  return userPool.getCurrentUser()
}

export function getSession(): Promise<CognitoUserSession | null> {
  const user = getCurrentUser()
  if (!user) return Promise.resolve(null)

  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session?.isValid()) {
        resolve(null)
      } else {
        resolve(session)
      }
    })
  })
}

export async function getIdToken(): Promise<string | null> {
  const session = await getSession()
  return session?.getIdToken().getJwtToken() ?? null
}

export function login(email: string, password: string): Promise<CognitoUserSession> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  const authDetails = new AuthenticationDetails({ Username: email, Password: password })

  return new Promise((resolve, reject) => {
    user.authenticateUser(authDetails, {
      onSuccess: resolve,
      onFailure: reject,
      newPasswordRequired: () => {
        reject(new Error('New password required — set it in the AWS console first'))
      },
    })
  })
}

export function signUp(email: string, password: string): Promise<void> {
  return new Promise((resolve, reject) => {
    userPool.signUp(email, password, [], [], (err) => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export function confirmSignUp(email: string, code: string): Promise<void> {
  const user = new CognitoUser({ Username: email, Pool: userPool })
  return new Promise((resolve, reject) => {
    user.confirmRegistration(code, true, (err) => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export function logout() {
  const user = getCurrentUser()
  if (user) user.signOut()
}

export function getLoginUrl(): string {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID
  const redirectUri = import.meta.env.VITE_REDIRECT_URI
  return `https://${domain}/login?client_id=${clientId}&response_type=code&scope=openid+email&redirect_uri=${encodeURIComponent(redirectUri)}`
}
