from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
import asyncio
import uvicorn
from main import build_graph

# System message to guide the LLM
SYSTEM_MESSAGE = """You are a helpful AI assistant that can use tools to accomplish tasks.
When given a task that requires multiple steps:
1. Break down the task into steps
2. Use the appropriate tools in sequence
3. After each tool call, analyze the result and determine if more steps are needed
4. Continue until the task is complete
5. Provide a clear final response summarizing the results

For example, if asked to "generate SQL for spend by user and run it":
1. First use text_to_sql to generate the SQL query
2. Then use run_sql to execute the generated query
3. Finally, present the results in a clear format"""

app = FastAPI(title="Agent API")

class ChatRequest(BaseModel):
    input: str

@app.post("/chat")
async def chat(req: ChatRequest):
    async def token_streamer():
        queue = asyncio.Queue()

        async def token_callback(token: str):
            await queue.put(token)
        
        graph = build_graph(token_callback)

        initial_state = {
            "messages": [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": req.input}
            ]
        }

        async def run_graph():
            async for _ in graph.astream(initial_state):
                pass  # potentially need to log here? this would log stuff on the server side

        asyncio.create_task(run_graph())

        while True:
            token = await queue.get()
            yield f"data: {token}\n\n";
            if token == "[DONE]":
                break
    
    return StreamingResponse(token_streamer(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 

# can be tested with
# curl -N -X POST "http://0.0.0.0:8000/chat" -H "Content-Type: application/json" -d '{"input": "What kind of bear is best?"}' 