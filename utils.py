from todoist_api_python.api import TodoistAPI
import os
import sys # For stderr

def get_todoist_client():
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        print("ERROR in get_todoist_client: TODOIST_API_TOKEN not set in environment", file=sys.stderr)
        raise ValueError("TODOIST_API_TOKEN not set in environment. Please set it in .env or Claude Desktop config.")
    print("get_todoist_client: Token found, initializing TodoistAPI.", file=sys.stderr)
    return TodoistAPI(token)