from fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from dotenv import load_dotenv
import os
import json
import sys # For printing to stderr

from utils import get_todoist_client

load_dotenv() # Ensure .env is loaded if token is there

@dataclass
class ToDoistContext:
    todoist_client: object # Consider typing more specifically, e.g., todoist_api_python.api.TodoistAPI

@asynccontextmanager
async def todoist_lifespan(server: FastMCP) -> AsyncIterator[ToDoistContext]:
    print("Lifespan: Initializing Todoist client...", file=sys.stderr)
    try:
        client = get_todoist_client() # This raises ValueError if token is not found
        print("Lifespan: Todoist client obtained.", file=sys.stderr)
        yield ToDoistContext(todoist_client=client)
    except ValueError as ve:
        print(f"Lifespan ERROR: {ve}. Server will likely not function correctly.", file=sys.stderr)
        # Option 1: Raise to prevent server from fully starting without client
        raise RuntimeError(f"Failed to initialize Todoist client in lifespan: {ve}")
        # Option 2: Yield a context with None or handle gracefully in tools (more complex)
        # yield ToDoistContext(todoist_client=None)
    except Exception as e:
        print(f"Lifespan: Unexpected exception during Todoist client initialization: {e}", file=sys.stderr)
        raise
    finally:
        print("Lifespan: Exiting lifespan.", file=sys.stderr)
        # Add any client cleanup if necessary, e.g., client.close() if it has such a method
        pass

# Initialize FastMCP - host/port are irrelevant for stdio
mcp = FastMCP(
    "todoist",
    description="MCP server for ToDoist integration",
    lifespan=todoist_lifespan
)

@mcp.tool()
async def add_task(ctx: Context, content: str, project_id: str = None) -> str:
    """Add a new task to ToDoist."""
    print(f"Tool 'add_task' called with content: '{content}', project_id: {project_id}", file=sys.stderr)
    if not ctx.request_context.lifespan_context or not hasattr(ctx.request_context.lifespan_context, 'todoist_client') or ctx.request_context.lifespan_context.todoist_client is None:
        return "Error: Todoist client not available in context. Check server logs for initialization issues."
    try:
        client = ctx.request_context.lifespan_context.todoist_client
        # The official todoist_api_python library returns a Task object
        task = client.add_task(content=content, project_id=project_id)
        print(f"Todoist API: Task added successfully - ID: {task.id}", file=sys.stderr)
        return f"Task added: {task.id} - {task.content}"
    except Exception as e:
        print(f"Error in add_task: {e}", file=sys.stderr)
        return f"Error adding task: {str(e)}"

@mcp.tool()
async def get_tasks(ctx: Context, project_id: str = None) -> str:
    """Get all tasks from ToDoist."""
    print(f"Tool 'get_tasks' called with project_id: {project_id}", file=sys.stderr)
    if not ctx.request_context.lifespan_context or not hasattr(ctx.request_context.lifespan_context, 'todoist_client') or ctx.request_context.lifespan_context.todoist_client is None:
        return "Error: Todoist client not available in context. Check server logs for initialization issues."
    try:
        client = ctx.request_context.lifespan_context.todoist_client
        tasks = client.get_tasks(project_id=project_id)
        task_list = [{"id": t.id, "content": t.content, "is_completed": t.is_completed} for t in tasks]
        print(f"Todoist API: Found {len(task_list)} tasks.", file=sys.stderr)
        return json.dumps(task_list, indent=2)
    except Exception as e:
        print(f"Error in get_tasks: {e}", file=sys.stderr)
        return f"Error getting tasks: {str(e)}"

@mcp.tool()
async def complete_task(ctx: Context, task_id: str) -> str:
    """Mark a task as completed."""
    print(f"Tool 'complete_task' called with task_id: {task_id}", file=sys.stderr)
    if not ctx.request_context.lifespan_context or not hasattr(ctx.request_context.lifespan_context, 'todoist_client') or ctx.request_context.lifespan_context.todoist_client is None:
        return "Error: Todoist client not available in context. Check server logs for initialization issues."
    try:
        client = ctx.request_context.lifespan_context.todoist_client
        success = client.close_task(task_id=task_id) # Returns True on success
        if success:
            print(f"Todoist API: Task {task_id} completed.", file=sys.stderr)
            return f"Task {task_id} marked as completed."
        else:
            print(f"Todoist API: Failed to complete task {task_id} (not found or other issue).", file=sys.stderr)
            return f"Failed to mark task {task_id} as completed (task not found or already completed)."
    except Exception as e:
        print(f"Error in complete_task: {e}", file=sys.stderr)
        return f"Error completing task: {str(e)}"

if __name__ == "__main__":
    print("Starting Todoist MCP server with STDIO transport...", file=sys.stderr)
    try:
        # mcp.run() is synchronous and handles the async loop for tools/lifespan
        mcp.run(transport='stdio')
    except Exception as e:
        print(f"Todoist MCP server failed to run: {e}", file=sys.stderr)
        # This ensures Claude Desktop sees the server process exited with an error.
        sys.exit(1) 
    print("Todoist MCP server finished.", file=sys.stderr)