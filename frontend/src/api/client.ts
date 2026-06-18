import { getIdToken } from '../auth/cognito'

const API_URL = import.meta.env.VITE_API_URL

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = await getIdToken()
  if (!token) {
    throw new Error('Not authenticated')
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: token,
      ...options?.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `API error: ${res.status}`)
  }

  return res.json()
}
