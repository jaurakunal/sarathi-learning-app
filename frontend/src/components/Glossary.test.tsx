import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Glossary } from './Glossary'

describe('Glossary', () => {
  it('renders terms and definitions', () => {
    render(
      <Glossary items={[
        { term: 'Reflection', plain: 'When an agent pauses to think.' },
        { term: 'Memory stream', plain: 'A log of experiences.' },
      ]} />,
    )
    expect(screen.getByText('Reflection')).toBeInTheDocument()
    expect(screen.getByText('When an agent pauses to think.')).toBeInTheDocument()
    expect(screen.getByText('Memory stream')).toBeInTheDocument()
    expect(screen.getByText('A log of experiences.')).toBeInTheDocument()
  })

  it('renders nothing for empty list', () => {
    const { container } = render(<Glossary items={[]} />)
    expect(container.firstChild).toBeNull()
  })
})
