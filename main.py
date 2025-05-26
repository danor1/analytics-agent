import os
import re
import math
from typing import Annotated
from typing_extensions import TypedDict
from langchain_core.tools import tool
from langchain.agents import Tool
from langchain_core.messages import ToolMessage
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
llm = init_chat_model(api_key=openai_key, model="gpt-4-turbo")

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
            user=
            password=
            host=
            database=
            port=
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
def call_llm(state: State):
    last_msg = state['messages'][-1]
    if isinstance(last_msg, ToolMessage):
        return {'messages': state['messages']}
    return {'messages': [llm_with_tools.invoke(state['messages'])]}

# --- Tool Executor Node ---
tool_node = ToolNode(tools)

graph_builder = StateGraph(State)
graph_builder.add_node("llm", call_llm)
graph_builder.add_node("tools", tool_node)
graph_builder.set_entry_point("llm")
graph_builder.add_conditional_edges("llm", tools_condition)
graph_builder.add_edge("tools", "llm")

graph = graph_builder.compile()

# --- Render Graph (optional) ---
# render(graph)

def stream_graph_updates(user_input: str):
    for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}):
        for value in event.values():
            print("INTERNAL CAPTURE: ", value)
            print("Assistant: ", value["messages"][-1].content)


def main():
    while True:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("exiting")
            break
        stream_graph_updates(user_input)
            

main()
