import os
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv

from utils.render import render 

load_dotenv()
openai_key = os.environ["OPENAI_API_KEY"]
llm = init_chat_model(api_key=openai_key, model="gpt-3.5-turbo")


class State(TypedDict):
    messages: Annotated[list, add_messages]


def chatbot(state: State):
    return {'messages': [llm.invoke(state['messages'])]}


graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)
graph_builder.set_entry_point("chatbot")

graph = graph_builder.compile()

# render(graph)

def stream_graph_updates(user_input: str):
    for event in graph.stream({"messages": [{"role": "user", "content": user_input}]}):
        for value in event.values():
            print("Assistant: ", value["messages"][-1].content)


def main():
    while True:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("exiting")
            break
        stream_graph_updates(user_input)
            

main()
