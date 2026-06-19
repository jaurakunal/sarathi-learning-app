import { Amplify } from 'aws-amplify'
import { generateClient } from 'aws-amplify/api'

const APPSYNC_URL = import.meta.env.VITE_APPSYNC_URL
const APPSYNC_REGION = import.meta.env.VITE_AWS_REGION || 'us-east-1'

Amplify.configure({
  API: {
    GraphQL: {
      endpoint: APPSYNC_URL,
      region: APPSYNC_REGION,
      defaultAuthMode: 'userPool',
    },
  },
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
    },
  },
})

export const client = generateClient()

export const SEND_MESSAGE = /* GraphQL */ `
  mutation SendMessage($paperId: String!, $message: String!) {
    sendMessage(paperId: $paperId, message: $message) {
      conversationId
      turnSeq
      status
    }
  }
`

export const ON_CHUNK = /* GraphQL */ `
  subscription OnChunk($conversationId: String!, $turnSeq: Int!) {
    onChunk(conversationId: $conversationId, turnSeq: $turnSeq) {
      conversationId
      turnSeq
      chunk
      done
      tokensIn
      tokensOut
    }
  }
`
