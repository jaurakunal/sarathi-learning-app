import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

export function Callback() {
  const navigate = useNavigate()
  const [error, setError] = useState('')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const err = params.get('error_description') || params.get('error')

    if (err) {
      setError(err)
      return
    }

    if (!code) {
      setError('No authorization code received')
      return
    }

    // Exchange code for tokens via Cognito token endpoint
    const domain = import.meta.env.VITE_COGNITO_DOMAIN
    const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID
    const redirectUri = `${window.location.origin}/callback`

    fetch(`https://${domain}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: clientId,
        code,
        redirect_uri: redirectUri,
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setError(data.error_description || data.error)
          return
        }
        // Store tokens in localStorage (same format as cognito-identity-js)
        const idToken = data.id_token
        const accessToken = data.access_token
        const refreshToken = data.refresh_token

        // Parse the ID token to get the user sub
        const payload = JSON.parse(atob(idToken.split('.')[1]))
        const sub = payload.sub

        // Store in the format cognito-identity-js expects
        const keyPrefix = `CognitoIdentityServiceProvider.${clientId}`
        localStorage.setItem(`${keyPrefix}.LastAuthUser`, sub)
        localStorage.setItem(`${keyPrefix}.${sub}.idToken`, idToken)
        localStorage.setItem(`${keyPrefix}.${sub}.accessToken`, accessToken)
        if (refreshToken) {
          localStorage.setItem(`${keyPrefix}.${sub}.refreshToken`, refreshToken)
        }

        // Redirect to app
        window.location.href = '/'
      })
      .catch((e) => {
        setError(e.message || 'Token exchange failed')
      })
  }, [])

  if (error) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center px-6">
        <div className="text-center space-y-3">
          <p className="text-red-400 text-sm">{error}</p>
          <button onClick={() => navigate('/')} className="text-sm text-accent hover:text-accent-light">
            Back to login
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
      <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
    </div>
  )
}
