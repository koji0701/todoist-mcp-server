from fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from dotenv import load_dotenv
import os
import json
import sys # For printing to stderr
import asyncio
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
async def add_task(
    ctx: Context,
    content: str,
    project_id: str = None,
    description: str = None,
    due_string: str = None,
    due_date: str = None,
    due_datetime: str = None,
    due_lang: str = None,
    priority: int = None,
    labels: list[str] = None,
    assignee_id: str = None,
    section_id: str = None,
    parent_id: str = None,
    order: int = None,
    duration: int = None,
    duration_unit: str = None  # e.g., "minute" or "day"
) -> str:
    """
    Add a new task to ToDoist.
    
    Args:
        content: The content of the task.
        project_id: ID of the project to add the task to.
        description: A long description for the task.
        due_string: A natural language string for the due date (e.g., "tomorrow at 12:00").
        due_date: Specific due date in YYYY-MM-DD format.
        due_datetime: Specific due date and time in RFC3339 format (e.g., "2023-09-01T12:00:00Z").
        due_lang: Language for `due_string` processing (e.g., "en", "ja").
        priority: Task priority (1 for p4, 2 for p3, 3 for p2, 4 for p1).
        labels: A list of label names to attach to the task.
        assignee_id: The ID of the user to assign the task to.
        section_id: ID of the section to add the task to.
        parent_id: ID of the parent task.
        order: The order of the task among its siblings.
        duration: The duration of the task in `duration_unit`.
        duration_unit: The unit for the `duration` ("minute" or "day").
    """
    
    # Log received parameters
    call_params = {
        "content": content, "project_id": project_id, "description": description,
        "due_string": due_string, "due_date": due_date, "due_datetime": due_datetime,
        "due_lang": due_lang, "priority": priority, "labels": labels,
        "assignee_id": assignee_id, "section_id": section_id, "parent_id": parent_id,
        "order": order, "duration": duration, "duration_unit": duration_unit
    }
    # Filter out None values for cleaner logging
    provided_args = {k: v for k, v in call_params.items() if v is not None}
    print(f"Tool 'add_task' called with args: {provided_args}", file=sys.stderr)

    if not ctx.request_context.lifespan_context or not hasattr(ctx.request_context.lifespan_context, 'todoist_client') or ctx.request_context.lifespan_context.todoist_client is None:
        return "Error: Todoist client not available in context. Check server logs for initialization issues."
    
    try:
        client = ctx.request_context.lifespan_context.todoist_client
        
        # Prepare arguments for the Todoist API client
        # The client.add_task method takes keyword arguments for all optional fields
        api_kwargs = {}
        if project_id:
            api_kwargs["project_id"] = project_id
        if description:
            api_kwargs["description"] = description
        if due_string:
            api_kwargs["due_string"] = due_string
        if due_date:
            api_kwargs["due_date"] = due_date
        if due_datetime:
            api_kwargs["due_datetime"] = due_datetime
        if due_lang:
            api_kwargs["due_lang"] = due_lang
        if priority is not None: # Priority can be 0, so check for None explicitly
            api_kwargs["priority"] = priority
        if labels: # Assumes labels is a list of strings (label names)
            api_kwargs["labels"] = labels
        if assignee_id:
            api_kwargs["assignee_id"] = assignee_id
        if section_id:
            api_kwargs["section_id"] = section_id
        if parent_id:
            api_kwargs["parent_id"] = parent_id
        if order is not None:
            api_kwargs["order"] = order
        if duration is not None:
            api_kwargs["duration"] = duration
        if duration_unit:
            api_kwargs["duration_unit"] = duration_unit
            
        task = client.add_task(content=content, **api_kwargs)
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

async def main():
    transport = os.getenv("TRANSPORT", "stdio")
    print(f"Starting Todoist MCP server with {transport} transport...", file=sys.stderr)
    if transport == "stdio":
        await mcp.run_stdio_async()
    else: 
        await mcp.run_sse_async()


if __name__ == "__main__":
    print("Starting Todoist MCP server with STDIO transport...", file=sys.stderr)
    asyncio.run(main())
    print("Todoist MCP server finished.", file=sys.stderr)
    # try:
    #     # mcp.run() is synchronous and handles the async loop for tools/lifespan
    #     mcp.run(transport='stdio')
    # except Exception as e:
    #     print(f"Todoist MCP server failed to run: {e}", file=sys.stderr)
    #     # This ensures Claude Desktop sees the server process exited with an error.
    #     sys.exit(1) 
