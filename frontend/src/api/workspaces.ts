import { apiFetch } from './client'

export interface Workspace {
  workspace_id: string
  name: string
  description?: string
  status: 'active' | 'paused' | 'archived'
  paused_reason?: string | null
  created_at?: string
  last_active_at?: string
}

export interface ActiveWorkspaceResponse {
  active_workspace_id: string | null
  workspace: Workspace | null
}

export function listWorkspaces(): Promise<{ workspaces: Workspace[] }> {
  return apiFetch<{ workspaces: Workspace[] }>('/workspaces')
}

export function getActiveWorkspace(): Promise<ActiveWorkspaceResponse> {
  return apiFetch<ActiveWorkspaceResponse>('/workspaces/active')
}

export function setActiveWorkspace(
  workspaceId: string,
): Promise<ActiveWorkspaceResponse> {
  return apiFetch<ActiveWorkspaceResponse>('/workspaces/active', {
    method: 'PUT',
    body: JSON.stringify({ workspace_id: workspaceId }),
  })
}

export function createWorkspace(
  name: string,
  description: string = '',
): Promise<{ workspace: Workspace }> {
  return apiFetch<{ workspace: Workspace }>('/workspaces', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  })
}

export function updateWorkspace(
  workspaceId: string,
  fields: Partial<Pick<Workspace, 'name' | 'description' | 'status'>> & { paused_reason?: string | null },
): Promise<{ workspace: Workspace }> {
  return apiFetch<{ workspace: Workspace }>(`/workspaces/${workspaceId}`, {
    method: 'PUT',
    body: JSON.stringify(fields),
  })
}

export function archiveWorkspace(
  workspaceId: string,
): Promise<{ status: string; workspace_id: string }> {
  return apiFetch<{ status: string; workspace_id: string }>(
    `/workspaces/${workspaceId}`,
    {
      method: 'DELETE',
      body: JSON.stringify({ confirm: true }),
    },
  )
}
