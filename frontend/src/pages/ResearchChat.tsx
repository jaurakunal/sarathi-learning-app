import { useParams } from 'react-router-dom'
import { Chat } from './Chat'

export function ResearchChat() {
  const { convId } = useParams<{ convId: string }>()

  return <Chat researchConvId={convId} />
}
