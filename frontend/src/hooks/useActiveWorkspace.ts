import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getActiveWorkspace,
  listWorkspaces,
  setActiveWorkspace,
  type ActiveWorkspaceResponse,
  type Workspace,
} from '../api/workspaces'

const STORAGE_KEY = 'sarathi.active_workspace'

interface CachedWorkspace {
  workspace_id: string
  name: string
}

/** Read the localStorage fallback. Server is always source of truth on read. */
export function readWorkspaceFallback(): CachedWorkspace | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as CachedWorkspace
  } catch {
    return null
  }
}

export function writeWorkspaceFallback(ws: CachedWorkspace | null) {
  try {
    if (ws) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ws))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // ignore
  }
}

/**
 * TanStack Query hook for the active workspace. Reads from server; falls back
 * to localStorage on fetch failure to avoid blank UI on transient errors.
 */
export function useActiveWorkspace() {
  return useQuery<ActiveWorkspaceResponse>({
    queryKey: ['workspaces', 'active'],
    queryFn: async () => {
      try {
        const result = await getActiveWorkspace()
        if (result.active_workspace_id && result.workspace) {
          writeWorkspaceFallback({
            workspace_id: result.active_workspace_id,
            name: result.workspace.name,
          })
        }
        return result
      } catch (err) {
        const cached = readWorkspaceFallback()
        if (cached) {
          return {
            active_workspace_id: cached.workspace_id,
            workspace: {
              workspace_id: cached.workspace_id,
              name: cached.name,
              status: 'active',
            } as Workspace,
          }
        }
        throw err
      }
    },
    staleTime: 30 * 1000,
    retry: 0,
  })
}

export function useWorkspaces() {
  return useQuery<{ workspaces: Workspace[] }>({
    queryKey: ['workspaces', 'list'],
    queryFn: listWorkspaces,
  })
}

export function useSetActiveWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (workspaceId: string) => setActiveWorkspace(workspaceId),
    onSuccess: (data) => {
      qc.setQueryData(['workspaces', 'active'], data)
      if (data.active_workspace_id && data.workspace) {
        writeWorkspaceFallback({
          workspace_id: data.active_workspace_id,
          name: data.workspace.name,
        })
      }
      // Invalidate everything that's workspace-scoped so the UI refetches.
      qc.invalidateQueries({ queryKey: ['feed'] })
      qc.invalidateQueries({ queryKey: ['profile'] })
      qc.invalidateQueries({ queryKey: ['library'] })
      qc.invalidateQueries({ queryKey: ['research'] })
      qc.invalidateQueries({ queryKey: ['conversations'] })
      qc.invalidateQueries({ queryKey: ['briefs'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
    },
  })
}
