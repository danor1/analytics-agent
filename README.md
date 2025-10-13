# AI Data Analytics Agent

A lightweight, framework-free AI agent that converts natural language questions into SQL queries and provides analytical insights.

## Features

- **No Heavy Frameworks**: Built without LangGraph - simple, clean Python code
- **Natural Language to SQL**: Converts questions into SQL queries using GPT-4
- **Direct Query Analysis**: Breaks down questions into logical analytical steps
- **Streaming Responses**: Real-time token-level streaming for immediate feedback
- **In-Memory Data**: Executes queries against 10 sample rows in JSON (no database needed!)
- **Schema + Data in JSON**: Single file contains both schema and sample data
- **Optional PostgreSQL**: Can connect to real database if credentials are provided
- **FastAPI REST API**: Streaming endpoint for web integration
- **CLI Interface**: Interactive command-line interface for local testing

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

1. Receives a natural language question
2. Breaks down the question into logical analytical steps
3. For each step:
   - Converts question to SQL using GPT-4
   - Executes query against in-memory data (or real DB if configured)
   - Analyzes results using GPT-4
4. Provides comprehensive summary in markdown format

## Architecture

- `main.py` - Core agent loop and CLI
- `api.py` - FastAPI REST API
- `tools/tools.py` - Tool definitions (text_to_sql, run_sql, etc.)
- `config/` - Schema definitions
- `utils/` - Helper utilities

No LangGraph, no complex dependencies - just simple, maintainable code.