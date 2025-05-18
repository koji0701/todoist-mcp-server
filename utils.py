from todoist_api_python.api import TodoistAPI
import os
import sys # For stderr

def get_todoist_client():
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        print("ERROR in get_todoist_client: TODOIST_API_TOKEN not set in environment", file=sys.stderr)
        # Updated error message for broader applicability
        raise ValueError("TODOIST_API_TOKEN not set in environment. This token is required to use Todoist tools.")
    print("get_todoist_client: Token found, initializing TodoistAPI.", file=sys.stderr)
    return TodoistAPI(token)