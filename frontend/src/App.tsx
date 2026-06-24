import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthGate } from './auth/AuthGate'
import { Feed } from './pages/Feed'
import { CardDetail } from './pages/CardDetail'
import { Chat } from './pages/Chat'
import { Profile } from './pages/Profile'
import { Library } from './pages/Library'
import { Research } from './pages/Research'
import { Conversations } from './pages/Conversations'
import { ResearchChat } from './pages/ResearchChat'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Feed />} />
            <Route path="/card/:id" element={<CardDetail />} />
            <Route path="/card/:id/chat" element={<Chat />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/library" element={<Library />} />
            <Route path="/research" element={<Research />} />
            <Route path="/conversations" element={<Conversations />} />
            <Route path="/chat/research/:convId" element={<ResearchChat />} />
          </Routes>
        </BrowserRouter>
      </AuthGate>
    </QueryClientProvider>
  )
}
