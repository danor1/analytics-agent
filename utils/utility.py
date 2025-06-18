"""
Utility functions for the agent application.
"""
import re
from typing import List


def extract_tables(sql: str) -> List[str]:
    """
    Extract table names from a SQL query.
    Handles formats like:
    - "catalog"."schema"."table"
    - catalog.schema.table
    - "schema"."table"
    - schema.table
    - just table
    """
    table_names = set()
    
    # Regex to capture tables in various formats
    regex = r'(?:"?[\w]+"?\.)?(?:"?[\w]+"?\.)?"?([\w]+)"?'
    
    for match in re.finditer(regex, sql):
        # match.group(1) is the table name (last part)
        table_names.add(match.group(1))
    
    return list(table_names)
