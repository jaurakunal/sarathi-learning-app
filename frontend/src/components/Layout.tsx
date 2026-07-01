import { useLocation, useNavigate } from 'react-router-dom'
import { Home, MessageCircle, Target, BookOpen, TrendingUp, Settings, LogOut } from 'lucide-react'
import { logout } from '../auth/cognito'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'

const NAV_ITEMS = [
  { path: '/', label: 'Feed', icon: Home },
  { path: '/conversations', label: 'Conversations', icon: MessageCircle },
  { path: '/research', label: 'Research', icon: Target },
  { path: '/library', label: 'Library', icon: BookOpen },
  { path: '/profile', label: 'Progress', icon: TrendingUp },
  { path: '/settings', label: 'Settings', icon: Settings },
] as const

interface LayoutProps {
  children: React.ReactNode
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-[#0a0a0f] lg:flex">
      {/* Desktop sidebar — hidden on mobile */}
      <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:left-0 lg:w-[240px] bg-[#0e0e18] border-r border-white/[0.06] z-30">
        {/* Logo */}
        <div className="px-6 pt-8 pb-3">
          <h1 className="text-xl font-bold text-gradient">Sārathi</h1>
        </div>

        {/* Workspace switcher */}
        <div className="px-3 pb-3">
          <WorkspaceSwitcher />
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 space-y-1">
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
            const active = location.pathname === path
            return (
              <button
                key={path}
                onClick={() => navigate(path)}
                className={`w-full flex items-center gap-3 px-4 py-2 rounded-lg text-sm transition-colors ${
                  active
                    ? 'text-white bg-white/[0.06] border-l-2 border-accent pl-[10px]'
                    : 'text-zinc-400 hover:text-white hover:bg-white/[0.04] border-l-2 border-transparent pl-[10px]'
                }`}
              >
                <Icon size={18} className={active ? 'text-accent' : ''} />
                {label}
              </button>
            )
          })}
        </nav>

        {/* Logout */}
        <div className="px-3 pb-6 border-t border-white/[0.06] pt-4">
          <button
            onClick={() => { logout(); window.location.reload() }}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-zinc-500 hover:text-red-400 hover:bg-red-400/5 transition-colors"
          >
            <LogOut size={18} />
            Log out
          </button>
        </div>
      </aside>

      {/* Main content — offset by sidebar width on desktop */}
      <main className="lg:ml-[240px] flex-1 min-h-screen">
        {/* Mobile top bar with workspace switcher */}
        <div className="lg:hidden flex items-center justify-between px-4 py-3 border-b border-white/[0.06] bg-[#0e0e18] sticky top-0 z-20">
          <h1 className="text-lg font-bold text-gradient">Sārathi</h1>
          <WorkspaceSwitcher />
        </div>
        {children}
      </main>
    </div>
  )
}
