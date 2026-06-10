"""Lambda Function URL handler: streaming chat via SSE."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda Function URL handler for streaming Q&A.

    Flow:
    1. Extract user_id from Cognito JWT
    2. Parallel reads: conversation history (DDB) + profile META (DDB) + paper full text (S3)
    3. Assemble context: system prompt + profile + paper + summaries + recent turns + new request
    4. PutItem: new turn with request, response=null
    5. Call Anthropic streaming API
    6. Forward chunks as SSE events
    7. UpdateItem: fill response + response_ts + citations + tokens
    """
    raise NotImplementedError("Streaming chat — M1 build step")
