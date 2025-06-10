import os
import re
import math
from pydantic import BaseModel
from langchain_core.tools import tool, Tool
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool


load_dotenv()


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
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            database=os.environ["DB_NAME"],
            port=os.environ["DB_PORT"],
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


# Define tools list
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
