import os
import re
import math
import json
import time
import asyncio
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.tools import tool
from langchain.agents import Tool
from langchain_core.messages import ToolMessage, ToolCall, AIMessageChunk, AIMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.chat_models import init_chat_model
from pydantic import BaseModel
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool

from utils.render import render 

load_dotenv()
openai_key = os.environ["OPENAI_API_KEY"]
llm = init_chat_model(api_key=openai_key, model="gpt-4-turbo", streaming=True)

class MultiplyInput(BaseModel):
    input: str

# --- Define Tool ---
@tool(args_schema=MultiplyInput)
def multiply(input: str) -> int:
    """
    Multiply two numbers. Accepts input like:
    - "2,3"
    - "2 * 3"
    - "2 3"
    - "multiply 2 and 3"
    """
    print("executing multiply")
    numbers = list(map(int, re.findall(r"\d+", input)))
    if len(numbers) < 2:
        raise ValueError("Please provide at least 2 numbers to multiply")
    
    print("math.prod(numbers[:2]): ", math.prod(numbers[:2]))
    return math.prod(numbers[:2])

@tool
def runSql(tool_input: str = "") -> list:
    """
    Executes a SQL query to fetch all records from the transactions table in the PostgreSQL database.
    Returns the query results as a list of tuples.
    
    Args:
        tool_input (str): Optional input parameter (not used in this implementation)
    """
    try:
        connection_pool = pool.SimpleConnectionPool(
            1,
            10,
            user="",
            password="",
            host="",
            database="",
            port=,
        )

        conn = connection_pool.getconn()
        cursor = conn.cursor()

        cursor.execute("SELECT * from transactions")
        results = cursor.fetchall()
        # print(f"results: {results}")

        cursor.close()
        connection_pool.putconn(conn)
    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        if 'connection_pool' in locals():
            connection_pool.closeall()
        return results


tools = [
    Tool(
        name="multiply",
        func=multiply,
        description="Multiplies two integers together. Input must be a string containing two numbers, like '4,3' or '4 * 3'. Parameter name is 'input'."
    ),
    Tool(
        name="get_data",
        func=runSql,
        description="gets data from postgres database"
    )
]
llm_with_tools = llm.bind_tools(tools)
# or define with:
# agents = initialize_agent(tools=tools, llm=llm, agent_type="openai-tools", verbose=True)


# --- Define Graph State ----
class State(TypedDict):
    messages: Annotated[list, add_messages]


# TODO: find a way to remove this function - probs resolve the extending function in the streaming loop
def aggregate_tool_calls(tool_calls_accumulator):
    grouped = {}

    for call in tool_calls_accumulator:
        idx = call.get("index")
        if idx is None:
            continue

        if idx not in grouped:
            grouped[idx] = {
                "index": idx,
                "id": call.get("id"),
                "name": call.get("function", {}).get("name"),
                "arguments": call.get("function", {}).get("arguments", ""),
                "type": call.get("type"),
            }
        else:
            grouped[idx]["arguments"] += call.get("function", {}).get("arguments", "")

        # Prefer non-None values if found in later chunks
        if not grouped[idx]["id"] and call.get("id"):
            grouped[idx]["id"] = call["id"]
        if not grouped[idx]["name"] and call.get("function", {}).get("name"):
            grouped[idx]["name"] = call["function"]["name"]
        if not grouped[idx]["type"] and call.get("type"):
            grouped[idx]["type"] = call["type"]

    # Convert back to expected format
    aggregated_calls = []
    for val in grouped.values():
        aggregated_calls.append({
            "index": val["index"],
            "id": val["id"],
            "function": {
                "name": val["name"],
                "arguments": val["arguments"]
            },
            "type": val["type"]
        })

    return aggregated_calls



# --- LLM Node (detects tool usage) ---
def make_llm_node(llm_with_tools, token_stream_callback=None):
    async def call_llm(state: State):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, ToolMessage):
            print("yielding early")
            yield {"messages": state["messages"]}
            # Already tool input, just pass through
            # yield {"tool_calls": last_msg.tool_calls}
            return

        collected_chunks = []
        content_accumulator = []
        tool_calls_accumulator = []

        # Streaming LLM output
        async for chunk in llm_with_tools.astream(state["messages"]):
            print(chunk)
            collected_chunks.append(chunk)

            if token_stream_callback:
                await token_stream_callback(chunk.content)
            if chunk.content:
                content_accumulator.append(chunk.content)
            if "tool_calls" in chunk.additional_kwargs:
                tool_calls_accumulator.extend(chunk.additional_kwargs["tool_calls"])
        
        if token_stream_callback:
            await token_stream_callback("[DONE]")
        
        full_content = "".join(content_accumulator)

        aggregated = aggregate_tool_calls(tool_calls_accumulator)
        print("tool_calls_accumulator: ", tool_calls_accumulator)
        print("aggregated: ", aggregated)
        if aggregated:
            print("in aggregated")

            # TODO: cleanup openai_style_tool_calls and tool_calls

            # tool_calls = list(map(lambda call: ToolCall(
            #     id=call["id"],
            #     name=call["function"]["name"],
            #     args=json.loads(call["function"]["arguments"])
            # ), aggregated))

            openai_style_tool_calls = [
                {
                    "id": call["id"],
                    "type": call["type"],
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"]
                    }
                }
                for call in aggregated
            ]
            print("openai_style_tool_calls: ", openai_style_tool_calls)
            print("full_content: ", full_content)

            yield {
                "tool_calls": [
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        args=json.loads(call["function"]["arguments"]),
                    ) for call in aggregated
                ],
                "messages": [
                    AIMessage(
                        content=full_content,
                        additional_kwargs={"tool_calls": openai_style_tool_calls}
                    )
                ]
            }
            return
            # yield {"tool_calls": tool_calls, "messages": [AIMessage(content=full_content, additional_kwargs={"tool_calls": openai_style_tool_calls})]}
        # print(f"Yielding final chunks: ${collected_chunks}")
        yield {"messages": [AIMessage(content=full_content)]}
        
    return call_llm

def end_node(state: State) -> State:
    print("[end_node] Final state: ", state)
    return state

# temporary - to remove
# async def tool_executor(state: State):
#     print("[tool_executor] Entered tool node")
#     tool_calls = state.get("tool_calls", [])
#     results = []
#     for call in tool_calls:
#         print(f"[tool_executor] Attempting to call tool: {call.name} with args: {call.args}")
#         for tool in tools:
#             if tool.name == call.name:
#                 try:
#                     output = await tool.ainvoke(call.args) if hasattr(tool, "ainvoke") else tool.invoke(call.args)
#                     print(f"[tool_executor] Tool '{call.name}' returned: {output}")
#                     results.append(ToolMessage(tool_call_id=call.id, content=str(output)))
#                 except Exception as e:
#                     print(f"[tool_executor] Error in tool '{call.name}': {e}")
#     return {"messages": results}

def custom_tools_condition(state: State) -> str:
    last_msg = state["messages"][-1]

    print("custom_tools_condition last_msg: ", last_msg)

    if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
        return "tools"
    
    return 'end'
    # return "tools" if state.get("tool_calls") else "llm"

# --- Build Graph function ---
def build_graph(token_stream_callback=None):
    graph_builder = StateGraph(State)

    # --- Make LLM Node ---
    llm_node = make_llm_node(llm_with_tools, token_stream_callback)

    # --- Tool Executor Node ---
    tool_node = ToolNode(tools)

    graph_builder.add_node("llm", llm_node)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_node("end", lambda state: state)

    graph_builder.set_entry_point("llm")

    graph_builder.add_conditional_edges("llm", custom_tools_condition)
    graph_builder.add_edge("tools", "llm")

    # --- Render Graph (optional) ---
    # render(graph)

    return graph_builder.compile()



async def stream_graph_updates(graph, user_input: str):
    print("Assistant: ", end="", flush=True)

    async for step in graph.astream({"messages": [{"role": "user", "content": user_input}]}):
        for node_output in step.values():
            for msg in node_output.get("messages", []):
                content = getattr(msg, "content", None)
                if content:
                    print(content, end="", flush=True)

    print()


async def main():
    graph = build_graph()
    while True:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("exiting")
            break
        await stream_graph_updates(graph, user_input)


if __name__ == "__main__":
    asyncio.run(main())
