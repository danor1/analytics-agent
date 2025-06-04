from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
import asyncio
import uvicorn
from main import build_graph

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

        async def run_graph():
            async for _ in graph.astream({"messages": [{"role": "user", "content": req.input}]}):
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