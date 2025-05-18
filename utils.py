from todoist_api_python.api import TodoistAPI
import os
import sys # For stderr

def get_todoist_client():
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        # This error will be raised if a tool attempts to initialize the client
        # and the token is not found in the environment.
        error_msg = "TODOIST_API_TOKEN not found in environment. This token is required for the Todoist MCP to function. Please set it in your environment or provide it via Smithery configuration."
        print(f"ERROR in get_todoist_client: {error_msg}", file=sys.stderr)
        raise ValueError(error_msg)
    print("get_todoist_client: Token found, initializing TodoistAPI.", file=sys.stderr)
    return TodoistAPI(token)