interface GlossaryProps {
  items: { term: string; plain: string }[]
}

export function Glossary({ items }: GlossaryProps) {
  if (!items.length) return null

  return (
    <dl className="space-y-2">
      {items.map((item) => (
        <div key={item.term}>
          <dt className="text-sm font-medium text-zinc-200">{item.term}</dt>
          <dd className="text-sm text-zinc-400 ml-0">{item.plain}</dd>
        </div>
      ))}
    </dl>
  )
}
