import os
import json
import asyncio
from typing import Dict, List, Any, Optional
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv

from tools.tools import define_tools


load_dotenv()


llm = init_chat_model(
    model="gpt-4-turbo",
    temperature=0,
    api_key=os.environ["OPENAI_API_KEY"],
    streaming=True
)


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

# --- Simple State Management ---
class AgentState:
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.tool_calls: List[Dict[str, Any]] = []
    
    def add_message(self, role: str, content: str, **kwargs):
        message = {"role": role, "content": content}
        message.update(kwargs)
        self.messages.append(message)
        return message
    
    def get_messages(self):
        return self.messages


def aggregate_tool_calls(tool_calls_accumulator):
    """Aggregate streaming tool call chunks into complete tool calls."""
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



async def call_llm_with_streaming(llm_with_tools, messages, token_stream_callback=None):
    """Call LLM and stream response, returning content and tool calls."""
    content_accumulator = []
    tool_calls_accumulator = []

    # Streaming LLM output
    async for chunk in llm_with_tools.astream(messages):
        print(chunk)

        if token_stream_callback and chunk.content:
            await token_stream_callback(chunk.content)
        if chunk.content:
            content_accumulator.append(chunk.content)
        if "tool_calls" in chunk.additional_kwargs:
            tool_calls_accumulator.extend(chunk.additional_kwargs["tool_calls"])
    
    full_content = "".join(content_accumulator)
    aggregated = aggregate_tool_calls(tool_calls_accumulator)
    
    print("tool_calls_accumulator: ", tool_calls_accumulator)
    print("aggregated: ", aggregated)
    
    return full_content, aggregated


async def execute_tool(tool_name: str, tool_args: Dict[str, Any], tools_dict: Dict[str, Any]) -> str:
    """Execute a single tool and return its result."""
    if tool_name not in tools_dict:
        return f"Error: Tool '{tool_name}' not found"
    
    tool_func = tools_dict[tool_name]
    try:
        # Call the tool function with the parsed arguments
        result = tool_func(**tool_args)
        # Handle async tool functions
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)
    except Exception as e:
        print(f"Error executing tool {tool_name}: {e}")
        return f"Error: {str(e)}"


async def run_agent_loop(payload, user_input: str, token_stream_callback=None):
    """Main agent loop - no framework, just simple iteration."""
    # Define tools
    tools = define_tools(payload, token_stream_callback)
    
    # Create a dict mapping tool names to their functions
    tools_dict = {tool.name: tool.func for tool in tools}
    
    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)
    
    # Initialize messages with system message and user input
    messages = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": user_input}
    ]
    
    # Agent loop - continue until no more tool calls
    max_iterations = 20  # Safety limit
    for iteration in range(max_iterations):
        print(f"\n--- Iteration {iteration + 1} ---")
        
        # Call LLM
        content, tool_calls = await call_llm_with_streaming(
            llm_with_tools, 
            messages, 
            token_stream_callback
        )
        
        # Add assistant message to history
        if tool_calls:
            openai_style_tool_calls = [
                {
                    "id": call["id"],
                    "type": call["type"],
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"]
                    }
                }
                for call in tool_calls
            ]
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": openai_style_tool_calls
            })
        else:
            messages.append({
                "role": "assistant",
                "content": content
            })
        
        # If no tool calls, we're done
        if not tool_calls:
            print("\nNo tool calls - agent finished")
            break
        
        # Execute each tool call
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            try:
                tool_args = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError as e:
                print(f"Error parsing tool arguments: {e}")
                tool_args = {}
            
            print(f"\nExecuting tool: {tool_name} with args: {tool_args}")
            
            # Execute the tool
            result = await execute_tool(tool_name, tool_args, tools_dict)
            
            print(f"Tool result: {result}")
            
            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": tool_name,
                "content": result
            })
    
    # Send done signal
    if token_stream_callback:
        await token_stream_callback("[DONE]")
    
    return messages



async def stream_agent_updates(payload, user_input: str):
    """Stream agent responses to console."""
    print("Assistant: ", end="", flush=True)
    
    await run_agent_loop(payload, user_input)
    
    print()


async def main():
    """CLI interface for the agent."""
    # Only import schema when running locally
    from config.database import transactions_schema

    payload = {
        "organization_id": "",
        "connection_id": "",
        'tenant_jwt': "",
        "schema": transactions_schema
    }

    while True:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("exiting")
            break
        await stream_agent_updates(payload, user_input)


if __name__ == "__main__":
    asyncio.run(main())
