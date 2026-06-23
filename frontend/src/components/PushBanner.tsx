import { useState } from 'react'
import { Bell } from 'lucide-react'
import { usePushNotifications } from '../hooks/usePushNotifications'

export function PushBanner() {
  const { permission, subscribed, subscribe } = usePushNotifications()
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem('push-banner-dismissed') === 'true'
  )

  if (subscribed || dismissed || permission === 'denied') return null
  if (!('Notification' in window) || !('serviceWorker' in navigator)) return null

  function handleEnable() {
    subscribe()
  }

  function handleDismiss() {
    localStorage.setItem('push-banner-dismissed', 'true')
    setDismissed(true)
  }

  return (
    <div className="mx-4 mt-3 p-3 rounded-xl bg-zinc-900/80 border border-zinc-800 flex items-center gap-3">
      <Bell size={18} className="text-accent shrink-0" />
      <p className="text-xs text-zinc-300 flex-1">Get notified when new papers land in your feed</p>
      <button
        onClick={handleEnable}
        className="text-xs font-medium text-accent hover:text-white transition-colors"
      >
        Enable
      </button>
      <button
        onClick={handleDismiss}
        className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
      >
        Later
      </button>
    </div>
  )
}
