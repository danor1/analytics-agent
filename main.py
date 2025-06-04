import os
import re
import math
import time
import asyncio
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.tools import tool
from langchain.agents import Tool
from langchain_core.messages import ToolMessage, AIMessageChunk, AIMessage
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool

from utils.render import render 

load_dotenv()
openai_key = os.environ["OPENAI_API_KEY"]
llm = init_chat_model(api_key=openai_key, model="gpt-4-turbo", streaming=True)

# --- Define Tool ---
@tool
def multiply(input: str) -> int:
    """
    Multiply two numbers. Accepts input like:
    - "2,3"
    - "2 * 3"
    - "2 3"
    - "multiply 2 and 3"
    """
    numbers = list(map(int, re.findall(r"\d+", input)))
    if len(numbers) < 2:
        raise ValueError("Please provide at least 2 numbers to multiply")
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
            user="upsolve",
            password="bgq6XED!gpv5jyx*jvx",
            host="upsolve-pg-instance-1.c7r9gwixnn8o.us-east-1.rds.amazonaws.com",
            database="moneybank",
            port=5432,
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
        description="Multiplies two integers together"
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


# --- LLM Node (detects tool usage) ---
def make_llm_node(llm_with_tools, token_stream_callback=None):
    async def call_llm(state: State):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, ToolMessage):
            yield {"messages": state["messages"]}
            return

        collected_chunks = []

        # Streaming LLM output
        async for chunk in llm_with_tools.astream(state["messages"]):
            print(chunk)
            if token_stream_callback:
                await token_stream_callback(chunk.content)
            collected_chunks.append(chunk)
        
        if token_stream_callback:
            await token_stream_callback("[DONE]")
        
        print(f"Yielding final chunks: ${collected_chunks}")
        yield {"messages": collected_chunks}
        
    return call_llm


# --- Build Graph function ---
def build_graph(token_stream_callback=None):
    graph_builder = StateGraph(State)

    # --- Make LLM Node ---
    llm_node = make_llm_node(llm_with_tools, token_stream_callback)

    # --- Tool Executor Node ---
    tool_node = ToolNode(tools)

    graph_builder.add_node("llm", llm_node)
    graph_builder.add_node("tools", tool_node)

    graph_builder.set_entry_point("llm")

    graph_builder.add_conditional_edges("llm", tools_condition)
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
