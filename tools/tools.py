import os
import re
import math
import json
import asyncio
import requests
from typing import Optional, Callable, List, Any
from pydantic import BaseModel
from langchain_core.tools import tool, Tool
from langchain_core.messages import SystemMessage, HumanMessage
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


def run_sql_execute(sql_query: str, payload) -> dict:
    """
    Execute SQL query against in-memory data from database.json.
    This provides realistic results without needing a real database.
    
    Args:
        sql_query (str): The SQL query to execute
    """
    print("run_sql_execute - In-memory execution")
    print("SQL Query:", sql_query)
    
    try:
        # Load data from database.json
        db_path = "config/database.json"
        with open(db_path, 'r') as f:
            db = json.load(f)
            data = db.get("data", {})
        
        # Simple query execution on in-memory data
        # This is a basic implementation - just returns the data
        # For more complex queries, you'd need a query parser
        
        # Extract table name from query (simple regex)
        import re
        table_match = re.search(r'FROM\s+(["\']?)(\w+\.?\w+)\1', sql_query, re.IGNORECASE)
        
        if table_match:
            table_name = table_match.group(2)
            # Handle quoted table names
            table_name = table_name.replace('"', '').replace("'", "")
            
            if table_name in data:
                result_data = data[table_name]
                
                # Apply LIMIT if present
                limit_match = re.search(r'LIMIT\s+(\d+)', sql_query, re.IGNORECASE)
                if limit_match:
                    limit = int(limit_match.group(1))
                    result_data = result_data[:limit]
                
                return {
                    "status": "success",
                    "message": f"Query executed successfully on in-memory data",
                    "queryResult": result_data,
                    "sql": sql_query
                }
        
        # Fallback if table not found
        return {
            "status": "success",
            "message": f"Query generated (no matching in-memory data)",
            "queryResult": [],
            "sql": sql_query
        }
        
    except Exception as e:
        print(f"Error in run_sql_execute: {e}")
        return {
            "status": "error",
            "message": str(e),
            "queryResult": [],
            "sql": sql_query
        }


def run_sql_execute_local(sql_query: str, payload) -> dict:
    """
    Execute SQL query against a local PostgreSQL database.
    This is optional - requires DB environment variables to be set.
    
    Args:
        sql_query (str): The SQL query to execute
    """
    print("run_sql_execute_local")
    
    # Check if database credentials are available
    db_credentials = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME", "DB_PORT"]
    if not all(os.environ.get(key) for key in db_credentials):
        print("Database credentials not found, using mock execution")
        return run_sql_execute(sql_query, payload)

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
        
        if 'connection_pool' in locals():
            connection_pool.closeall()
        
        return {
            "status": "success",
            "message": "Query executed successfully",
            "queryResult": [dict(zip([desc[0] for desc in cursor.description], row)) for row in results] if results else [],
            "sql": sql_query
        }
    except Exception as e:
        print(f"Error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "queryResult": [],
            "sql": sql_query
        }


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
    def run_sql(sql_query: str) -> str:
        """Runs provided sql query (or returns mock result if no database configured)"""
        # Always use local execution which falls back to mock if no DB is configured
        result = run_sql_execute_local(sql_query, payload)
        return json.dumps(result)
    return run_sql


def create_text_to_sql_tool(schema, token_stream_callback=None):
    @tool(args_schema=TextToSqlInput)
    async def text_to_sql(query: str) -> str:
        """Generates sql from a main query."""
        local_llm = init_chat_model(
            model="gpt-4-turbo",
            temperature=0,
            api_key=os.environ["OPENAI_API_KEY"],
            streaming=True
        )
        return await text_to_sql_from_schema(local_llm, schema, query, token_stream_callback)
    return text_to_sql


def create_analyse_data_tool(token_stream_callback=None):
    @tool(args_schema=AnalyseDataInput)
    async def analyse_data_tool(status: str, data: dict) -> str:
        """Takes raw data, analyses raw data for insigts, returns results in markdown format """
        local_llm = init_chat_model(
            model="gpt-4-turbo",
            temperature=0,
            api_key=os.environ["OPENAI_API_KEY"],
            streaming=True
        )
        return await analyse_data(local_llm, status, data, token_stream_callback)
    return analyse_data_tool


# Define tools list
def define_tools(payload, token_stream_callback=None):
    # Access schema directly from the Pydantic model
    schema = payload.schema

    tools = [
        multiply,
        create_run_sql_tool(payload, token_stream_callback),
        create_text_to_sql_tool(schema, token_stream_callback),
        create_analyse_data_tool(token_stream_callback),
    ]
    
    return tools

# TODO: create chart tool

# run the following sql "select * from transactions limit 1"
# generate sql for "spend by category"
# generate analytical questions to "who spent the most"
# generate sql for "spend by category" and execute it
# execute the sql "select * from transactions limit 2"
# generate sql for products sold by location and execute it
