import { getIdToken } from '../auth/cognito'
import { readWorkspaceFallback } from '../hooks/useActiveWorkspace'

const API_URL = import.meta.env.VITE_API_URL

/** Append a workspace_id query param to a path if not already present. */
function withWorkspace(path: string): string {
  // /workspaces, /workspaces/active, /workspaces/{wid}, /push, /account, /onboarding
  // do not need a workspace_id parameter — the server resolves it itself
  // (or doesn't care). Skip injection for those.
  const skipPrefixes = ['/workspaces', '/push', '/account']
  if (skipPrefixes.some((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`))) {
    return path
  }
  if (path.includes('workspace_id=')) {
    return path
  }
  const fallback = readWorkspaceFallback()
  if (!fallback?.workspace_id) {
    return path
  }
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}workspace_id=${encodeURIComponent(fallback.workspace_id)}`
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = await getIdToken()
  if (!token) {
    throw new Error('Not authenticated')
  }

  const finalPath = withWorkspace(path)

  const res = await fetch(`${API_URL}${finalPath}`, {
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
