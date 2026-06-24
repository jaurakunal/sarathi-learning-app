import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../api/client'

interface OnboardingGateProps {
  children: ReactNode
}

function checkOnboarding(): Promise<{ has_profile: boolean }> {
  return apiFetch('/onboarding')
}

export function OnboardingGate({ children }: OnboardingGateProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['onboarding-status'],
    queryFn: checkOnboarding,
    staleTime: 60 * 1000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  // If the check fails, assume profile exists (don't block existing users)
  if (isError) {
    return <>{children}</>
  }

  if (data && !data.has_profile) {
    return <Navigate to="/onboarding" replace />
  }

  return <>{children}</>
}
