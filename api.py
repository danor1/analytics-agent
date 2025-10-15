import re
import os
from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import uvicorn
from dotenv import load_dotenv
from paid import Paid
from main import run_agent_loop

load_dotenv()


# System message to guide the LLM
SYSTEM_MESSAGE = """You are a helpful AI data analyst.

When given a user question:
1. Break down the question into logical analytical steps
2. For each step:
    a. Generate a SQL query using the text_to_sql tool
    b. Execute the SQL query using the run_sql tool
    c. Analyze the returned data using the analyse_data tool
3. Summarize your findings in clear markdown, using bullet points and code blocks for data

Rules:
- Use only the provided schema
- Always show your reasoning and steps
- Never use table formatting (|), use bullet points or code blocks for structured data
- SQL queries are automatically limited to 50 rows
- Use the analyse_data tool to get insights from SQL results before summarizing
- Always end each response with a newline or double newline for proper formatting
"""

app = FastAPI(title="Agent API")

# Initialize paid client
paid_client = Paid(token=os.environ["PAIDAI_KEY"])

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

class AgentPayload(BaseModel):
    schema: dict[str, SchemaType]

class ChatRequest(BaseModel):
    input: str
    payload: AgentPayload

@api_v1_router.post("/chat")
async def chat(req: ChatRequest):
    async def token_streamer():
        print("req: ", req)
        if not req.payload.schema:
            raise HTTPException(status_code=400, detail="Missing schema in payload")
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
        
        # Run the agent loop
        async def run_agent():
            signals = []
            
            def collect_signal_callback(signal_name):
                signals.append(signal_name)
            
            await run_agent_loop(req.payload, req.input, token_callback, collect_signal_callback, "2d958cd9-ecff-4619-8523-8c986a9dbb1f", "0165cd09-66cb-4c4f-adba-0a5aeb171a4b")
            
            # Record signals in bulk
            if signals:
                result = paid_client.usage.record_bulk(signals=[signals])
                print("API signals recorded: ", result)

        asyncio.create_task(run_agent())

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
