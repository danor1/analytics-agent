import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
import asyncio
import uvicorn
from main import build_graph


# TODO: bring local SYSTEM_MESSAGE in alignment and bring back table formatting
# System message to guide the LLM
SYSTEM_MESSAGE = """You are a helpful AI assistant that can use tools to accomplish tasks.
When given a task that requires multiple steps:
1. Break down the task into steps
2. Use the appropriate tools in sequence
3. After each tool call, analyze the result and determine if more steps are needed
4. Continue until the task is complete
5. Provide a clear final response summarizing the results in valid markdown format

For example, if asked to "generate SQL for spend by user and run it":
1. First use text_to_sql to generate the SQL query
2. Then use run_sql to execute the generated query
3. Finally, present the results in a clear format using markdown

Always format your final response using markdown:
- Use # for main headings
- Use ## for subheadings
- Use ``` for code blocks with appropriate language specification
- Use - or * for bullet points
- Use ** for bold text
- Use * for italic text
- Use > for blockquotes
- Use [text](url) for links

Important formatting rules:
- Always add two newlines after headings
- Always add one newline after paragraphs
- Always add one newline after list items
- Always add one newline before and after code blocks
- Always add one newline before and after blockquotes
- Use double newlines to create clear section breaks
- NEVER use table formatting (|) - instead use bullet points or code blocks for structured data
"""

app = FastAPI(title="Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

class SchemaType(BaseModel):
    columns: list[str]
    types: dict[str, str]

class ConnectionPayload(BaseModel):
    organization_id: str
    connection_id: str
    tenant_jwt: str
    schema: dict[str, SchemaType]

class ChatRequest(BaseModel):
    input: str
    payload: ConnectionPayload

# TODO: organization_id will eventually be passed through an auth middleware
@app.post("/chat")
async def chat(req: ChatRequest):
    async def token_streamer():
        print("req: ", req)
        if not req.payload.organization_id or not req.payload.connection_id or not req.payload.tenant_jwt or not req.payload.schema:
            raise HTTPException(status_code=400, message="Missing required payload fields")
            return
        
        queue = asyncio.Queue()

        async def token_callback(token: str):
            for part in re.split(r'(\n\n|\n)', token):
                if part == '\n':
                    await queue.put('[NEWLINE]')
                elif part == '\n\n':
                    await queue.put('[DOUBLENEWLINE]')
                elif part:
                    await queue.put(part)
        
        graph = build_graph(req.payload, token_callback)

        initial_state = {
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": req.input}
            ]
        }

        async def run_graph():
            async for _ in graph.astream(initial_state):
                pass

        asyncio.create_task(run_graph())

        while True:
            token = await queue.get()
            
            if token == '[DONE]':
                yield f"data: [DONE]\n\n"
                break

            for part in re.split(r'(\n\n|\n)', token):
                if part == '\n':
                    yield f"data: [NEWLINE]\n\n"
                elif part == '\n\n':
                    yield f"data: [DOUBLENEWLINE]\n\n"
                elif part:
                    yield f"data: {part}\n\n"
    
    return StreamingResponse(token_streamer(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 

# can be tested with
# curl -N -X POST "http://0.0.0.0:8000/chat" -H "Content-Type: application/json" -d '{"input": "What kind of bear is best?"}' 