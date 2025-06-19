import re
from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
import asyncio
import uvicorn
from main import build_graph


# System message to guide the LLM
SYSTEM_MESSAGE = """You are a helpful AI data analyst.

When given a user question:
0. Start by explaining your analysis approach in exactly 1 sentence (how you plan to break down and answer the question). Do not mention SQL or technical details.
1. Generate exactly 3 analytical sub-questions that would help answer the main question using the generate_analytical_questions tool.
2. Process each sub-question one at a time (in series, not parallel):
    a. Generate a SQL query to answer it using the text_to_sql tool.
    b. Execute the SQL query using the run_sql tool.
    c. Analyze the returned data using the analyse_data tool.
    d. Move to the next sub-question only after completing the previous one.
3. Summarize your findings in clear markdown, using bullet points and code blocks for data.

Rules:
- Use only the provided schema.
- Always show your reasoning and steps.
- Never use table formatting (|), use bullet points or code blocks for structured data.
- Add LIMIT 50 to SQL queries if not present.
- Use the analyse_data tool to get insights from SQL results before summarizing.
- Process exactly 3 questions, one at a time.
- Always end each response with a newline or double newline for proper formatting.
"""

app = FastAPI(title="Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

api_v1_router = APIRouter(prefix="/v1/api")

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
@api_v1_router.post("/chat")
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


# Mount the v1 API router
app.include_router(api_v1_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 
