import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../api/client'
import { useActiveWorkspace } from '../hooks/useActiveWorkspace'

interface OnboardingGateProps {
  children: ReactNode
}

interface OnboardingStatus {
  has_user_meta?: boolean
  user_onboarding_complete?: boolean
  has_workspace_profile?: boolean
  next_stage?: 'user' | 'workspace' | 'complete'
  workspace_id?: string | null
  has_profile?: boolean // legacy
}

function checkOnboarding(): Promise<OnboardingStatus> {
  return apiFetch('/onboarding')
}

export function OnboardingGate({ children }: OnboardingGateProps) {
  // Bootstrap active workspace alongside onboarding status.
  const active = useActiveWorkspace()
  const onboarding = useQuery({
    queryKey: ['onboarding-status'],
    queryFn: checkOnboarding,
    staleTime: 60 * 1000,
    retry: 1,
  })

  if (active.isLoading || onboarding.isLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  // Treat fetch errors as "let them through" (don't lock out existing users)
  if (onboarding.isError) {
    return <>{children}</>
  }

  const data = onboarding.data
  if (data) {
    // Legacy: has_profile is the union flag
    const fullyDone =
      data.next_stage === 'complete' ||
      (data.has_user_meta && data.has_workspace_profile) ||
      data.has_profile === true
    if (!fullyDone) {
      return <Navigate to="/onboarding" replace />
    }
  }

  // If they have no active workspace at all, send them to onboarding to create one.
  if (active.data && !active.data.active_workspace_id) {
    return <Navigate to="/onboarding" replace />
  }

  return <>{children}</>
}
