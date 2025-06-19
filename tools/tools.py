import os
import re
import math
import json
import asyncio
import requests
from typing import Annotated, Optional, Callable, List, Any
from pydantic import BaseModel
from langchain_core.tools import tool, Tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState
from langgraph.prebuilt.chat_agent_executor import AgentState
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool

from utils.utility import extract_tables


load_dotenv()


class MultiplyInput(BaseModel):
    input: str


class TextToSqlInput(BaseModel):
    query: str


class RunSqlInput(BaseModel):
    sql_query: str


class GenerateAnalyticalQuestionsInput(BaseModel):
    query: str


class AnalyseDataInput(BaseModel):
    status: str
    data: dict  # Accepts any dict, including 'message' and 'queryResult' keys
    # queryResult is a list of dicts with arbitrary key-value pairs
    # Example: {'message': str, 'queryResult': list[dict[str, Any]]}


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


def run_sql_execute(sql_query: str, payload) -> list:
    """
    Inner function that executes a SQL query against a provided db
    Returns the query results as a list of tuples.
    
    Args:
        sql_query (str): The SQL query to execute
    """
    print("run_sql_execute payload: ", payload)

    # TODO: change over this function to use the api request, add in hostoverride, raw table name extraction, and a local dev version that hits our transactions pg db
    sql_payload = {
        "sqlQuery": sql_query,
        "connectionId": payload.connection_id,
        "filters": [],
        "rawTableNames": extract_tables(sql_query),
        "requestingOrganization": payload.organization_id,
        "tz": 0
    }
    print("sql_payload: ", sql_payload)

    api_base = "http://localhost:5001" if os.environ.get("ENV") == "development" else "https://api.upsolve.ai"
    api_route = f"{api_base}/v1/api/client-database/run-sql"

    try:
        response = requests.post(
            api_route,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {payload.tenant_jwt}"
            },
            json=sql_payload
            )

        results = response.json()
        print("run_sql_execute results: ", results)
    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        return results


def run_sql_execute_local(sql_query: str, payload) -> list:
    """
    Inner function that executes a SQL query against the transactions postgres db
    Returns the query results as a list of tuples.
    
    Args:
        sql_query (str): The SQL query to execute
    """
    print("run_sql_execute_local payload: ", payload)

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

        cursor.execute(sql_query)
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


async def text_to_sql_from_schema(local_llm, schema, query: str = "", token_stream_callback=None) -> str:
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
            13. Add a LIMIT clause where appropriate (for example, if a long list of rows is expected in the response). If you do not add a LIMIT, a LIMIT 50 should be appended.
            14. When appropriate, add an ORDER BY clause (e.g., ORDER BY id DESC or ORDER BY created_at DESC) if such columns exist in the selected table(s).

            CRITICAL: Your response must be ONLY the SQL query, with no additional text, explanations, or formatting.
            DO NOT include any of the following in your response:
            - SQL: prefix
            - ```sql markers
            - Explanations or comments
            - Any other text before or after the query
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

    if token_stream_callback:
        await token_stream_callback("\n\n")
        # await token_stream_callback("[TEXT_TO_SQL_TOOL]")  # For testing
        # await token_stream_callback("\n\n")  # For testing

    content_accumulator = []

    try:
        if token_stream_callback:
            await token_stream_callback("[CODE_START]")

        async for chunk in local_llm.astream(messages):
            print(chunk)

            if chunk.content and token_stream_callback:
                await token_stream_callback(chunk.content)
            if chunk.content:
                content_accumulator.append(chunk.content)
        
        full_content = "".join(content_accumulator).strip()

        # --- Add LIMIT 50 if not present ---
        # TODO: do this if not present and/or a higher limit has been inadvertently set
        generated_sql = full_content.rstrip(';')
        if not re.search(r'\\blimit\\b\\s*\\d+', generated_sql, re.IGNORECASE):
            generated_sql += " LIMIT 50"
        generated_sql += ";"

        if token_stream_callback:
            await token_stream_callback("[CODE_END]")
        
        print("text_to_sql_from_schema generated_sql: ", generated_sql)
        return generated_sql
    except Exception as e:
        print(f"Error in text_to_sql_from_schema: {e}")
        if token_stream_callback:
            await token_stream_callback("[CODE_END]")
        raise


async def generate_questions_from_schema(local_llm, schema, query: str = "", token_stream_callback=None, stream=True) -> list:
    """
    Inner function that generates a list of similar analytical questions.
    
    Args:
        query (str): The main question to generate similar questions for
        schema (dict): The schema of the dataset that is being analysed
        token_stream_callback (callable): Optional callback for streaming tokens
        stream (bool): Whether to stream the response or not
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

    print("executing generate_questions_from_schema")

    if token_stream_callback:
        await token_stream_callback("\n\n")
        # await token_stream_callback("[GENERATE_ANALYTICAL_QUESTIONS_TOOL]")  # For testing
        # await token_stream_callback("\n\n")  # For testing
    
    try:
        match stream:
            case True:
                # Use streaming if stream=True
                content_accumulator = []
                async for chunk in local_llm.astream(messages):
                    print(chunk)
                    if chunk.content and token_stream_callback:
                        await token_stream_callback(chunk.content)
                    if chunk.content:
                        content_accumulator.append(chunk.content)
                full_content = "".join(content_accumulator)
            case False:
                # Use non-streaming if stream=False
                response = await local_llm.ainvoke(messages)
                full_content = response.content

        try:
            # Parse the JSON string into a list of questions
            questions = json.loads(full_content.strip())
            # Limit to exactly 3 questions
            return questions[:3]
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            return []
    except Exception as e:
        print(f"Error in generate_questions_from_schema: {e}")
        raise


async def analyse_data(local_llm, status: str, data: dict, token_stream_callback=None) -> str:
    """
    Uses an LLM to analyze and summarize the results of a SQL query in markdown format.
    """
    # Compose the prompt
    messages = [
        SystemMessage(content="""
            You are a data analyst. Given a status and a set of raw query results (as a list of dicts), analyze the data and provide a clear, concise summary in markdown format.
            - Highlight key findings, trends, and outliers.
            - Use bullet points, code blocks, and headings as appropriate.
            - If the data is empty, say so.
            - Do not use table formatting (|), use code blocks or bullet points for structured data.
            - Be as insightful as possible.
        """),
        HumanMessage(content=f"""
            Status: {status}
            Data: {json.dumps(data, indent=2)}
        """)
    ]

    print("executing analyse_data")

    if token_stream_callback:
        await token_stream_callback("\n\n")
        # await token_stream_callback("[ANALYSE_DATA_TOOL]")  # For testing
        # await token_stream_callback("\n\n")  # For testing

    content_accumulator = []

    try:
        async for chunk in local_llm.astream(messages):
            print(chunk)

            if chunk.content and token_stream_callback:
                await token_stream_callback(chunk.content)
            if chunk.content:
                content_accumulator.append(chunk.content)
        
        full_content = "".join(content_accumulator)

        print("analyse_data full_content: ", full_content)
        return full_content
    except Exception as e:
        print(f"Error in analyse_data: {e}")
        raise


def create_run_sql_tool(payload, token_stream_callback=None):
    @tool(args_schema=RunSqlInput)
    def run_sql(
        sql_query: str
        # state: Annotated[AgentState, InjectedState],  # TODO: bring these back but need to pass in state and config into the tool call
        # config: RunnableConfig  # TODO: bring these back but need to pass in state and config into the tool call
    ) -> str:
        """Runs provided sql query"""
        if token_stream_callback:
            token_stream_callback("\n\n")
            # token_stream_callback("[RUN_SQL_TOOL]")  # For testing
            # token_stream_callback("\n\n")  # For testing
            return run_sql_execute(sql_query, payload)
        
        return run_sql_execute_local(sql_query, payload)
    return run_sql


def create_text_to_sql_tool(schema, token_stream_callback=None):
    @tool(args_schema=TextToSqlInput)
    def text_to_sql(
        query: str
        # state: Annotated[AgentState, InjectedState],  # TODO: bring these back but need to pass in state and config into the tool call
        # config: RunnableConfig  # TODO: bring these back but need to pass in state and config into the tool call
    ) -> str:
        """Generates sql from a main query."""
        local_llm = init_chat_model(
            model="gpt-4-turbo",
            temperature=0,
            api_key=os.environ["OPENAI_API_KEY"],
            streaming=True
        )
        return asyncio.run(text_to_sql_from_schema(local_llm, schema, query, token_stream_callback))
    return text_to_sql


def create_generate_analytical_questions_tool(schema, token_stream_callback=None, stream=True):
    @tool(args_schema=GenerateAnalyticalQuestionsInput)
    def generate_analytical_questions(
        query: str,
        # state: Annotated[AgentState, InjectedState],  # TODO: bring these back but need to pass in state and config into the tool call
        # config: RunnableConfig  # TODO: bring these back but need to pass in state and config into the tool call
    ) -> list:
        """Generates related analytical questions for a main query."""
        local_llm = init_chat_model(
            model="gpt-4-turbo",
            temperature=0,
            api_key=os.environ["OPENAI_API_KEY"],
            streaming=stream
        )
        print("stream: ", stream)
        return asyncio.run(generate_questions_from_schema(local_llm, schema, query, token_stream_callback, stream))
    return generate_analytical_questions


def create_analyse_data_tool(token_stream_callback=None):
    @tool(args_schema=AnalyseDataInput)
    def analyse_data_tool(
        status: str,
        data: dict,
        # state: Annotated[AgentState, InjectedState],  # TODO: bring these back but need to pass in state and config into the tool call
        # config: RunnableConfig  # TODO: bring these back but need to pass in state and config into the tool call
    ) -> str:
        """Takes raw data, analyses raw data for insigts, returns results in markdown format """
        local_llm = init_chat_model(
            model="gpt-4-turbo",
            temperature=0,
            api_key=os.environ["OPENAI_API_KEY"],
            streaming=True
        )
        return asyncio.run(analyse_data(local_llm, status, data, token_stream_callback))
    return analyse_data_tool


# Define tools list
def define_tools(payload, token_stream_callback=None):
    # Access schema directly from the Pydantic model
    schema = payload.schema

    tools = [
        Tool(
            name="multiply",
            func=multiply,
            description="Multiplies two integers together. Input must be a string containing two numbers, like '4,3' or '4 * 3'. Parameter name is 'input'."
        ),
        Tool(
            name="run_sql",
            func=create_run_sql_tool(payload, token_stream_callback),
            description="Executes SQL queries against a provided database. Returns results as a list of tuples."
        ),
        Tool(
            name='text_to_sql',
            func=create_text_to_sql_tool(schema, token_stream_callback),
            description="Converts natural language questions into SQL queries. Takes a question as input and returns a valid SQL query that will answer the question."
        ),
        Tool(
            name='generate_analytical_questions',
            func=create_generate_analytical_questions_tool(schema, token_stream_callback, stream=False),
            description="Generates a list of similar analytical questions that could help answer the main question. Takes a question as input and returns a list of related questions that explore different aspects of the main question."
        ),
         # TODO: analyse_data tool doesnt seem to be used
        Tool(
            name='analyse_data',
            func=create_analyse_data_tool(token_stream_callback),
            description="Analyses raw data returned from the run_sql tool. Returns results in markdown format"
        ),
    ]
    
    return tools

# TODO: create chart tool

# run the following sql "select * from transactions limit 1"
# generate sql for "spend by category"
# generate analytical questions to "who spent the most"
# generate sql for "spend by category" and execute it
# execute the sql "select * from transactions limit 2"
# generate sql for products sold by location and execute it
