import { Sparkles, Compass, Newspaper, MessageCircle, TrendingUp } from 'lucide-react'

const STEPS = [
  {
    icon: Compass,
    title: 'Tell it what you care about',
    body: 'A 5-minute chat maps your research interests, background, and how deep you want to go.',
  },
  {
    icon: Newspaper,
    title: 'Wake up to a personal feed',
    body: 'Every night it scans arXiv, HuggingFace, Papers With Code, and OpenReview — surfaces the handful worth your morning.',
  },
  {
    icon: MessageCircle,
    title: 'Chat with any paper',
    body: 'Grounded RAG over the full text. Ask "why does this matter for my work" and get sourced answers.',
  },
  {
    icon: TrendingUp,
    title: 'It learns as you read',
    body: 'Every dismiss, bookmark, and question shifts what shows up tomorrow. Your profile compounds.',
  },
]

export function Landing() {
  const goToSignUp = () => {
    window.location.href = '/login?signup'
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white relative overflow-hidden">
      <div className="ambient-orb w-[36rem] h-[36rem] bg-accent top-[-14rem] right-[-14rem]" />
      <div className="ambient-orb w-[28rem] h-[28rem] bg-violet-neon bottom-[-8rem] left-[-8rem]" />

      <header className="relative z-10 flex items-center justify-between px-6 lg:px-10 py-5">
        <h1 className="text-xl font-bold text-gradient">Sārathi</h1>
        <a
          href="/login"
          className="text-sm text-zinc-300 hover:text-white transition-colors"
        >
          Sign in
        </a>
      </header>

      <section className="relative z-10 max-w-3xl mx-auto px-6 pt-10 pb-16 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] text-xs text-zinc-400 mb-6">
          <Sparkles size={12} className="text-accent" />
          Your AI chief-of-research-staff
        </div>
        <h2 className="text-4xl lg:text-5xl font-bold leading-tight tracking-tight">
          Stop drowning in papers.<br />
          <span className="text-gradient">Start reading the right ones.</span>
        </h2>
        <p className="mt-6 text-zinc-400 text-lg max-w-2xl mx-auto">
          Sārathi reads the AI research firehose so you don't have to.
          It learns what you care about, and every morning hands you a short,
          personal digest — with a chat interface for the papers you want to go deeper on.
        </p>
        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3">
          <button
            onClick={goToSignUp}
            className="px-6 py-3 bg-accent hover:bg-accent-light text-white font-medium rounded-xl shadow-glow transition-all"
          >
            Get started
          </button>
          <a
            href="#how-it-works"
            className="px-6 py-3 text-sm text-zinc-300 hover:text-white transition-colors"
          >
            See how it works →
          </a>
        </div>
      </section>

      <section id="how-it-works" className="relative z-10 max-w-5xl mx-auto px-6 pb-24">
        <h3 className="text-center text-sm uppercase tracking-widest text-zinc-500 mb-10">
          How it works
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <div key={i} className="glass-card rounded-2xl p-6 space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-accent/15 border border-accent-dim flex items-center justify-center">
                  <Icon size={18} className="text-accent" />
                </div>
                <span className="text-xs text-zinc-500 font-mono">
                  {String(i + 1).padStart(2, '0')}
                </span>
              </div>
              <h4 className="text-lg font-semibold">{title}</h4>
              <p className="text-sm text-zinc-400 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="relative z-10 max-w-2xl mx-auto px-6 pb-20 text-center">
        <div className="glass-card rounded-2xl p-8 space-y-4">
          <h3 className="text-2xl font-semibold">Ready to try it?</h3>
          <p className="text-zinc-400 text-sm">
            Create an account in a minute. The onboarding chat takes about 5 minutes.
          </p>
          <button
            onClick={goToSignUp}
            className="px-6 py-3 bg-accent hover:bg-accent-light text-white font-medium rounded-xl shadow-glow transition-all"
          >
            Get started
          </button>
        </div>
      </section>

      <footer className="relative z-10 text-center text-xs text-zinc-600 pb-8">
        Built for a small crew of researchers. Not accepting public signups.
      </footer>
    </div>
  )
}
