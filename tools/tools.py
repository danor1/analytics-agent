import os
import re
import math
import json
import asyncio
from typing import Annotated, Optional, Callable
from pydantic import BaseModel
from langchain_core.tools import tool, Tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
# from langgraph.graph import AsyncTool
from langgraph.prebuilt import InjectedState
from langgraph.prebuilt.chat_agent_executor import AgentState
# from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool


load_dotenv()

# TODO: move to a config file
transactions_schema = {
    "transactions": {
        "columns": [
            "purchase_date",
            "posted_date", 
            "payment_date",
            "exported_date",
            "exported_datetime",
            "amount",
            "currency",
            "original_amount",
            "original_currency", 
            "usd_equivalent_amount",
            "expense_status",
            "payment_status",
            "budget_or_limit",
            "parent_budget",
            "policy",
            "user",
            "department",
            "location",
            "cost_center",
            "merchant_name",
            "category",
            "memo",
            "type",
            "current_review_assignees",
            "review_assigned_datetime",
            "final_approval_datetime",
            "final_approver",
            "final_copilot_approver",
            "id",
            "country_of_expense"
        ],
        "types": {
            "purchase_date": "date",
            "posted_date": "string",
            "payment_date": "string", 
            "exported_date": "string",
            "exported_datetime": "string",
            "amount": "number",
            "currency": "string",
            "original_amount": "number",
            "original_currency": "string",
            "usd_equivalent_amount": "number",
            "expense_status": "string",
            "payment_status": "string",
            "budget_or_limit": "string",
            "parent_budget": "string",
            "policy": "string",
            "user": "string",
            "department": "string",
            "location": "string",
            "cost_center": "string",
            "merchant_name": "string",
            "category": "string",
            "memo": "string",
            "type": "string",
            "current_review_assignees": "string",
            "review_assigned_datetime": "string",
            "final_approval_datetime": "string",
            "final_approver": "string",
            "final_copilot_approver": "string",
            "id": "string",
            "country_of_expense": "string"
        }
    }
}


# llm = ChatOpenAI(
#     model="gpt-4-turbo-preview",
#     temperature=0,
#     api_key=os.environ["OPENAI_API_KEY"]
# )
llm = init_chat_model(
    model="gpt-4-turbo",
    temperature=0,
    api_key=os.environ["OPENAI_API_KEY"],
    streaming=True
)


class MultiplyInput(BaseModel):
    input: str


class TextToSqlInput(BaseModel):
    query: str


class RunSqlInput(BaseModel):
    query: str


class GenerateAnalyticalQuestionsInput(BaseModel):
    query: str


# TODO: move the functions that the tools call away after bringing state and config in
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


@tool(args_schema=RunSqlInput)
def run_sql(query: str = "") -> list:
    """
    Executes a SQL query against the PostgreSQL database.
    Returns the query results as a list of tuples.
    
    Args:
        query (str): The SQL query to execute
    """
    try:
        connection_pool = pool.SimpleConnectionPool(
            1,
            10,
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            database=os.environ["DB_NAME"],
            port=os.environ["DB_PORT"],
        )

        conn = connection_pool.getconn()
        cursor = conn.cursor()

        cursor.execute(query)
        results = cursor.fetchall()
        print("run_sql results: ", results)

        cursor.close()
        connection_pool.putconn(conn)
    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        if 'connection_pool' in locals():
            connection_pool.closeall()
        return results


async def text_to_sql_from_schema(query: str = "", schema: dict = {}, token_stream_callback=None) -> str:
    """
    Inner function that generates a SQL query based on the input text description.
    
    Args:
        query (str): Natural language description of the desired SQL query
        schema (dict): The schema to use for generating the SQL query
        token_stream_callback (callable): Optional callback for streaming tokens
    """
    messages = [
        SystemMessage(content="""
            You are a SQL expert tasked with converting natural language questions into SQL queries.
            Your goal is to generate accurate and efficient SQL queries that will answer the given question.

            Rules for SQL Generation:
            1. Only use tables and columns that exist in the provided schema
            2. Use proper SQL syntax and best practices
            3. Include appropriate JOINs when data is needed from multiple tables
            4. Use proper aggregation functions when needed
            5. Handle NULL values appropriately
            6. Use proper table aliases to avoid ambiguity
            7. For JSON/JSONB columns, use the ->> (text) or -> (JSON) operators instead of dot notation
            8. Properly escape string values in WHERE clauses
            9. Use E'string' syntax for strings with special characters
            10. Double single quotes for apostrophes
            11. NEVER use ID columns directly in SELECT or GROUP BY clauses unless:
                - You use a different column from the same table instead
                - They are used to join to another table to get meaningful data
                - They are used only for joining/grouping, not for direct visualization
                - They are used to count/aggregate other meaningful columns
            12. For each visualization:
                - Generate a SQL query that will produce the exact data needed for that visualization
                - The SQL query must match the dimensions and measures used in the chart configuration
                - Use meaningful column aliases that match the chart configuration field names
                - Ensure the query returns data in the correct format for the chart type
                - For line charts, ensure time-based data is properly ordered
                - For bar charts, ensure categorical data is properly grouped
                - For donut charts, ensure the data is properly aggregated for the segments

            Your response must be ONLY a valid SQL query that:
            - Directly answers the given question
            - Uses only tables and columns from the provided schema
            - Is properly formatted and readable
            - Includes appropriate comments explaining complex parts
        """),
        HumanMessage(content=f"""
            Question: {query}

            Available Schema:
            {schema}

            Generate a SQL query that will answer this question.
            The query should only use tables and columns that exist in the provided schema.
            Return ONLY the SQL query, no explanation or additional text.
        """)
    ]

    print("executing text_to_sql_from_schema")
    content_accumulator = []

    async for chunk in llm.astream(messages):
        print(chunk)

        if token_stream_callback:
            await token_stream_callback(chunk.content)
        if chunk.content:
            content_accumulator.append(chunk.content)
    
    full_content = "".join(content_accumulator)
    print("text_to_sql_from_schema full_content: ", full_content)
    return full_content.strip()


async def generate_questions_from_schema(query: str = "", schema: dict = {}, token_stream_callback=None) -> list:
    """
    Inner function that generates a list of similar analytical questions.
    
    Args:
        query (str): The main question to generate similar questions for
        schema (dict): The schema of the dataset that is being analysed
        token_stream_callback (callable): Optional callback for streaming tokens
    Returns:
        list: A list of similar questions
    """
    messages = [
        SystemMessage(content=f"""
            You are a data analyst tasked with generating similar analytical questions that could help answer a main question.
            Your goal is to create a list of related questions that explore different aspects of the main question.

            Rules for Question Generation:
            1. Questions should be specific and measurable
            2. Questions should explore different dimensions of the main question
            3. Questions should reference actual columns from the schema
            4. Questions should be focused on one aspect at a time
            5. Questions should be actionable and lead to clear insights
            6. NEVER use ID columns directly in questions - use meaningful columns instead

            Question Categories to Consider:
            - Time-based analysis (trends, seasonality, growth)
            - Comparative analysis (between departments, categories, time periods)
            - Performance metrics (spending, amounts, quantities)
            - User behavior (spending patterns, preferences)
            - Category analysis (spending by category)
            - Location analysis (spending by location)

            Your response must be a JSON array of strings, where each string is a question.
            Return ONLY the questions, no explanations or additional metadata.

            CRITICAL: Only use columns that exist in the provided schema.
            CRITICAL: Questions must be specific and reference actual data points.
            CRITICAL: Each question should help answer the main question from a different angle.
        """),
        HumanMessage(content=f"""
            Main Question: {query}

            Available Schema:
            {schema}

            Generate a list of similar questions that could help answer the main question.
            The questions should be specific, measurable, and reference actual columns from the schema.
            Return ONLY the questions as a JSON array of strings.
        """)
    ]

    # response = llm.invoke(messages)
    print("executing generate_questions_from_schema")
    content_accumulator = []

    async for chunk in llm.astream(messages):
        print(chunk)

        if token_stream_callback:
            await token_stream_callback(chunk.content)
        if chunk.content:
            content_accumulator.append(chunk.content)
    
    full_content = "".join(content_accumulator)

    try:
        # Parse the JSON string into a list of questions
        questions = json.loads(full_content.strip())
        return questions
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}")
        return []


def create_text_to_sql_tool(token_stream_callback=None):
    @tool(args_schema=TextToSqlInput)
    def text_to_sql(
        query: str
        # state: Annotated[AgentState, InjectedState],  # TODO: bring these back but need to pass in state and config into the tool call
        # config: RunnableConfig  # TODO: bring these back but need to pass in state and config into the tool call
    ) -> str:
        """Generates sql from a main query."""
        return asyncio.run(text_to_sql_from_schema(query, transactions_schema, token_stream_callback))  # TODO: pass in transactions_schema
    return text_to_sql


def create_generate_analytical_questions_tool(token_stream_callback=None):
    @tool(args_schema=GenerateAnalyticalQuestionsInput)
    def generate_analytical_questions(
        query: str,
        # state: Annotated[AgentState, InjectedState],  # TODO: bring these back but need to pass in state and config into the tool call
        # config: RunnableConfig  # TODO: bring these back but need to pass in state and config into the tool call
    ) -> list:
        """Generates related analytical questions for a main query."""
        return asyncio.run(generate_questions_from_schema(query, transactions_schema, token_stream_callback))  # TODO: pass in transactions_schema
    return generate_analytical_questions



# Define tools list
def define_tools(token_stream_callback=None):
    tools = [
        Tool(
            name="multiply",
            func=multiply,
            description="Multiplies two integers together. Input must be a string containing two numbers, like '4,3' or '4 * 3'. Parameter name is 'input'."
        ),
        Tool(
            name="run_sql",
            func=run_sql,
            description="Executes SQL queries against a PostgreSQL database. Returns results as a list of tuples."
        ),
        Tool(
            name='text_to_sql',
            func=create_text_to_sql_tool(token_stream_callback),
            description="Converts natural language questions into SQL queries. Takes a question as input and returns a valid SQL query that will answer the question."
        ),
        Tool(
            name='generate_analytical_questions',
            func=create_generate_analytical_questions_tool(token_stream_callback),
            description="Generates a list of similar analytical questions that could help answer the main question. Takes a question as input and returns a list of related questions that explore different aspects of the main question."
        )
    ]
    
    return tools

# TODO: create chart tool


# run the following sql "select * from transactions limit 1"
# generate sql for "spend by category"
# generate analytical questions to "who spent the most"
# generate sql for "spend by category" and execute it
