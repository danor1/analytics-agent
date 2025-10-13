# AI Data Analytics Agent

A lightweight, framework-free AI agent that converts natural language questions into SQL queries and provides analytical insights.

## Features

- **No Heavy Frameworks**: Built without any framework - simple, clean Python code with async/await
- **Natural Language to SQL**: Converts questions into SQL queries using GPT-4
- **Direct Query Analysis**: Breaks down questions into logical analytical steps
- **Streaming Responses**: Real-time token-level streaming for immediate feedback
- **Async Tool Execution**: Proper async/await support for efficient tool execution
- **In-Memory Data**: Executes queries against sample rows in JSON (no database needed!)
- **Schema + Data in JSON**: Single file contains both schema and sample data
- **Optional PostgreSQL**: Can connect to real database if credentials are provided
- **FastAPI REST API**: Streaming endpoint for web integration
- **CLI Interface**: Interactive command-line interface for local testing
- **Debug Logging**: Full response logging to track agent reasoning and outputs

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
# Required
OPENAI_API_KEY=your_openai_api_key

# Optional (for database execution)
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_NAME=your_db_name
DB_PORT=5432
```

## Usage

### CLI Mode
```bash
python main.py
```

### API Mode
```bash
python api.py
```

Then send POST requests to `http://localhost:8000/v1/api/chat`:
```json
{
  "input": "What are the top spending categories?",
  "payload": {
    "schema": { ... }
  }
}
```

## Database Configuration

The agent uses `config/database.json` which contains:
- **Schema**: Table definitions with column names and types
- **Data**: 10 sample rows for each table (users and transactions)

You can:
- Edit the existing JSON file to modify schema or data
- Add more tables and sample data
- Use the in-memory data for realistic query results without a real database

## How It Works

1. **User Input**: Receives a natural language question
2. **Agent Loop**: Iterates until task is complete (max 20 iterations)
3. **For Each Iteration**:
   - LLM determines next action and calls appropriate tools
   - **text_to_sql**: Converts natural language to SQL query
   - **run_sql**: Executes query against in-memory data (or real DB if configured)
   - **analyse_data**: Analyzes results and provides insights
4. **Streaming Output**: Real-time token streaming with full response logging
5. **Final Response**: Comprehensive summary in markdown format

### Tool Execution Flow

```
User Question → LLM (with tools) → Tool Calls → Execute Tools → Results → LLM → Final Answer
                      ↑                                                         |
                      |_________________________________________________________|
                                    (Loop until complete)
```

All tools use async/await for efficient execution within the running event loop.

## Architecture

- `main.py` - Core async agent loop and CLI interface
- `api.py` - FastAPI REST API with streaming support
- `tools/tools.py` - Async tool definitions (text_to_sql, run_sql, analyse_data)
- `config/database.json` - Schema and sample data
- `utils/` - Helper utilities (rendering, data extraction)

### Key Components

**Agent Loop (`run_agent_loop`)**:
- Manages conversation history and message state
- Streams LLM responses in real-time
- Executes tools asynchronously using `ainvoke()`
- Logs full responses for debugging

**Tools**:
- `text_to_sql` - Async LLM call to generate SQL from natural language
- `run_sql` - Executes SQL against in-memory data or PostgreSQL
- `analyse_data` - Async LLM call to analyze and summarize results
- `multiply` - Example tool for demonstration

**Streaming**:
- Token-level streaming from LLM
- Tool output streaming via callbacks
- Final response logging

No LangGraph, no complex dependencies - just simple, maintainable async Python code.