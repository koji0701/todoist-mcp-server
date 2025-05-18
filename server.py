from fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, asdict, is_dataclass 
from dotenv import load_dotenv
import os
import json
import sys # For printing to stderr
import asyncio
from datetime import date, datetime, timezone # Already here
from typing import Any, Callable, Iterator, List, Optional, Union, Literal # For type hints

from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Task, Project, Section, Label, Comment, Collaborator, Attachment # Import models

from utils import get_todoist_client

load_dotenv() 

@dataclass
class ToDoistContext:
    todoist_client: Optional[TodoistAPI] = None # Allow client to be None initially

@asynccontextmanager
async def todoist_lifespan(server: FastMCP) -> AsyncIterator[ToDoistContext]:
    print("Lifespan: Initializing Todoist client (lazy loading enabled)...", file=sys.stderr)
    client_instance: Optional[TodoistAPI] = None
    # Attempt to initialize the client if the token is available in the environment
    # This allows pre-initialization if the token is already set.
    # If not, tools will initialize it on demand.
    if os.getenv("TODOIST_API_TOKEN"):
        try:
            client_instance = get_todoist_client()
            print("Lifespan: Todoist client pre-initialized successfully from environment variable.", file=sys.stderr)
        except ValueError as ve:
            # This case should ideally not be hit if os.getenv("TODOIST_API_TOKEN") was true,
            # but kept for robustness.
            print(f"Lifespan warning during pre-initialization: {ve}. Client will be initialized by the first tool call if token is provided then.", file=sys.stderr)
        except Exception as e:
            print(f"Lifespan ERROR: Unexpected exception during Todoist client pre-initialization: {e}. Client will remain uninitialized.", file=sys.stderr)
    else:
        print("Lifespan: TODOIST_API_TOKEN not found in environment at startup. Client will be initialized by the first tool call if token is available then.", file=sys.stderr)

    context = ToDoistContext(todoist_client=client_instance)
    try:
        yield context
    finally:
        print("Lifespan: Exiting lifespan.", file=sys.stderr)
        # No specific cleanup needed for the client here as it's managed by the TodoistAPI instance
        pass
# Initialize FastMCP
mcp = FastMCP(
    "todoist",
    description="MCP server for ToDoist integration",
    lifespan=todoist_lifespan
)

# Helper for paginated results (no changes needed here)
async def _fetch_all_from_paginator(
    paginator_func: Callable[..., Iterator[List[Any]]],
    **kwargs: Any
) -> List[Any]:
    def sync_fetch():
        paginator = paginator_func(**kwargs)
        all_items = []
        for page in paginator:
            all_items.extend(page)
        return all_items
    return await asyncio.to_thread(sync_fetch)

# NEW: Custom JSON serializer for datetime objects
def json_datetime_serializer(obj: Any) -> str:
    """JSON serializer for objects not serializable by default json code,
    especially datetime objects."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()  # Convert datetime/date to ISO 8601 string
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

# MODIFIED: _serialize_response to use the custom serializer
def _serialize_response(data: Any) -> str:
    """
    Serializes SDK model objects (which are dataclasses), lists of them,
    or other data (like booleans or simple strings) to a JSON string.
    Handles datetime objects by converting them to ISO 8601 format.
    """
    prepared_data: Any

    if isinstance(data, list):
        prepared_data = [
            asdict(item) if is_dataclass(item) and not isinstance(item, type) else item
            for item in data
        ]
    elif is_dataclass(data) and not isinstance(data, type): 
        prepared_data = asdict(data)
    else:
        prepared_data = data
    
    try:
        return json.dumps(prepared_data, default=json_datetime_serializer, indent=2)
    except TypeError as e:
        error_message = (f"Serialization Error in _serialize_response: {e}. "
                         f"Problematic data type: {type(prepared_data)}. "
                         f"Snippet (first 500 chars): {str(prepared_data)[:500]}")
        print(error_message, file=sys.stderr)
        return json.dumps({"error": "Failed to serialize response", "details": str(e)})
    except Exception as e_gen: 
        error_message = (f"Generic JSON Dumping Error in _serialize_response: {e_gen}. "
                         f"Data snippet (first 500 chars): {str(prepared_data)[:500]}")
        print(error_message, file=sys.stderr)
        return json.dumps({"error": "A general error occurred during JSON serialization", "details": str(e_gen)})

# Helper for preparing API arguments (no changes needed here, already handles date parsing)
def _prepare_api_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Filters out None values and prepares kwargs for API calls."""
    parsed_kwargs = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        
        new_v = v
        if k in ('due_date', 'deadline_date') and isinstance(v, str):
            try:
                new_v = date.fromisoformat(v)
            except ValueError:
                pass 
        elif k in ('due_datetime', 'since', 'until') and isinstance(v, str):
            try:
                new_v = datetime.fromisoformat(v)
            except ValueError:
                pass 
        parsed_kwargs[k] = new_v
    return parsed_kwargs

# --- Generic Client Getter for Tools ---
async def _get_or_init_client(ctx: Context, tool_name_for_log: str) -> TodoistAPI:
    lifespan_ctx: ToDoistContext = ctx.request_context.lifespan_context # type: ignore
    
    if lifespan_ctx.todoist_client is None:
        print(f"Tool '{tool_name_for_log}': Client not pre-initialized. Attempting to initialize now...", file=sys.stderr)
        try:
            # This will fetch the token from the environment
            client = get_todoist_client() 
            lifespan_ctx.todoist_client = client # Store for subsequent calls
            print(f"Tool '{tool_name_for_log}': Client initialized successfully on demand.", file=sys.stderr)
        except ValueError as ve: # Token not set or other issues from get_todoist_client
            print(f"Tool '{tool_name_for_log}' ERROR: {ve}", file=sys.stderr)
            # Re-raise to be caught by the tool's error handler, which will serialize it.
            raise 
        except Exception as e: # Other unexpected init errors
            print(f"Tool '{tool_name_for_log}' ERROR: Failed to initialize Todoist client on demand: {e}", file=sys.stderr)
            raise # Re-raise
    
    # At this point, lifespan_ctx.todoist_client should be non-None if initialization succeeded.
    # If initialization failed, an exception would have been raised.
    if lifespan_ctx.todoist_client is None:
        # This should ideally not be reached if exceptions are handled correctly above.
        # However, as a safeguard:
        err_msg = "Todoist client could not be initialized due to a persistent issue. Please check logs."
        print(f"Tool '{tool_name_for_log}' FATAL ERROR: {err_msg}", file=sys.stderr)
        raise RuntimeError(err_msg) # Raise a runtime error as this is an unexpected state

    return lifespan_ctx.todoist_client
def _handle_tool_error(e: Exception, tool_name: str, item_id: Optional[str] = None) -> str:
    item_info = f" for item {item_id}" if item_id else ""
    error_message_prefix = f"Error in {tool_name}{item_info}"
    print(f"{error_message_prefix}: {e}", file=sys.stderr)
    
    error_detail = str(e)
    error_summary = f"Error in {tool_name}"

    if "401" in str(e) or "Forbidden" in str(e) or "authentication" in str(e).lower() or isinstance(e, ValueError) and "TODOIST_API_TOKEN" in str(e):
        error_summary = f"{error_message_prefix}: Authentication failed or missing token."
        error_detail = "Authentication failed. Please ensure your TODOIST_API_TOKEN is set correctly and has the necessary permissions."
        if isinstance(e, ValueError) and "TODOIST_API_TOKEN" in str(e): # Specifically for missing token from get_todoist_client
             error_detail = str(e)


    return _serialize_response({"error": error_summary, "details": error_detail})


# --- Task Functions ---
@mcp.tool()
async def add_task(
    ctx: Context,
    content: str,
    description: Optional[str] = None,
    project_id: Optional[str] = None,
    section_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    labels: Optional[List[str]] = None,
    priority: Optional[int] = None,
    due_string: Optional[str] = None,
    due_lang: Optional[str] = None,
    due_date: Optional[str] = None, 
    due_datetime: Optional[str] = None, 
    assignee_id: Optional[str] = None,
    order: Optional[int] = None,
    auto_reminder: Optional[bool] = None,
    auto_parse_labels: Optional[bool] = None,
    duration: Optional[int] = None,
    duration_unit: Optional[Literal["minute", "day"]] = None,
    deadline_date: Optional[str] = None, 
    deadline_lang: Optional[str] = None
) -> str:
    """Create a new task."""
    tool_name = "add_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: # Should not happen if _get_or_init_client raises properly
            return _serialize_response({"error": "Client could not be initialized.", "details": "Unknown error during client initialization."})

        api_kwargs = _prepare_api_kwargs(
            description=description, project_id=project_id, section_id=section_id,
            parent_id=parent_id, labels=labels, priority=priority, due_string=due_string,
            due_lang=due_lang, due_date=due_date, due_datetime=due_datetime,
            assignee_id=assignee_id, order=order, auto_reminder=auto_reminder,
            auto_parse_labels=auto_parse_labels, duration=duration, duration_unit=duration_unit,
            deadline_date=deadline_date, deadline_lang=deadline_lang
        )
        print(f"Tool '{tool_name}' called with content='{content}', kwargs={api_kwargs}", file=sys.stderr)
        task = await asyncio.to_thread(client.add_task, content=content, **api_kwargs)
        return _serialize_response(task)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def get_task(ctx: Context, task_id: str) -> str:
    """Get a specific task by its ID."""
    tool_name = "get_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called with task_id='{task_id}'", file=sys.stderr)
        task = await asyncio.to_thread(client.get_task, task_id=task_id)
        return _serialize_response(task)
    except Exception as e:
        return _handle_tool_error(e, tool_name, task_id)

@mcp.tool()
async def get_tasks(
    ctx: Context,
    project_id: Optional[str] = None,
    section_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    label: Optional[str] = None,
    ids: Optional[List[str]] = None,
    limit: Optional[int] = None
) -> str:
    """Get active tasks, optionally filtered."""
    tool_name = "get_tasks"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        api_kwargs = _prepare_api_kwargs(
            project_id=project_id, section_id=section_id, parent_id=parent_id,
            label=label, ids=ids, limit=limit # SDK might handle limit differently or not at all for get_tasks
        )
        print(f"Tool '{tool_name}' called with kwargs={api_kwargs}", file=sys.stderr)
        # The `limit` in `get_tasks` of the SDK might be for pagination, not total items.
        # _fetch_all_from_paginator already handles pagination.
        # If a true server-side limit is desired and SDK `get_tasks` supports it directly, use it.
        # Otherwise, limit is applied post-fetch if needed (as it is here)
        tasks = await _fetch_all_from_paginator(client.get_tasks, **api_kwargs)
        return _serialize_response(tasks)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def filter_tasks(
    ctx: Context,
    query: Optional[str] = None,
    lang: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get active tasks matching the filter query."""
    tool_name = "filter_tasks"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        api_kwargs = _prepare_api_kwargs(query=query, lang=lang, limit=limit) # SDK `filter_tasks` might take `filter` instead of `query`
        print(f"Tool '{tool_name}' called with kwargs={api_kwargs}", file=sys.stderr)
        # Assuming client.filter_tasks maps to client.get_tasks(filter=query, lang=lang, limit=limit)
        # or a similar mechanism. If the SDK uses 'filter' for the query string:
        sdk_filter_kwargs = {'filter': query}
        if lang: sdk_filter_kwargs['lang'] = lang
        if limit: sdk_filter_kwargs['limit'] = limit # This limit might be for pagination page size
        
        tasks = await _fetch_all_from_paginator(client.get_tasks, **_prepare_api_kwargs(**sdk_filter_kwargs))
        return _serialize_response(tasks)
    except Exception as e:
        return _handle_tool_error(e, tool_name)


@mcp.tool()
async def add_task_quick(
    ctx: Context,
    text: str,
    note: Optional[str] = None,
    reminder: Optional[str] = None,
    auto_reminder: bool = True
) -> str:
    """Create a new task using Todoist's Quick Add syntax."""
    tool_name = "add_task_quick"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        api_kwargs = _prepare_api_kwargs(note=note, reminder=reminder, auto_reminder=auto_reminder)
        print(f"Tool '{tool_name}' called with text='{text}', kwargs={api_kwargs}", file=sys.stderr)
        task = await asyncio.to_thread(client.add_task_quick, text=text, **api_kwargs) # type: ignore
        return _serialize_response(task)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def update_task(
    ctx: Context,
    task_id: str,
    content: Optional[str] = None,
    description: Optional[str] = None,
    labels: Optional[List[str]] = None,
    priority: Optional[int] = None,
    due_string: Optional[str] = None,
    due_lang: Optional[str] = None,
    due_date: Optional[str] = None, 
    due_datetime: Optional[str] = None, 
    assignee_id: Optional[str] = None,
    day_order: Optional[int] = None,
    collapsed: Optional[bool] = None,
    duration: Optional[int] = None,
    duration_unit: Optional[Literal["minute", "day"]] = None,
    deadline_date: Optional[str] = None, 
    deadline_lang: Optional[str] = None
) -> str:
    """Update an existing task."""
    tool_name = "update_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        api_kwargs = _prepare_api_kwargs(
            content=content, description=description, labels=labels, priority=priority,
            due_string=due_string, due_lang=due_lang, due_date=due_date, due_datetime=due_datetime,
            assignee_id=assignee_id, day_order=day_order, collapsed=collapsed, duration=duration,
            duration_unit=duration_unit, deadline_date=deadline_date, deadline_lang=deadline_lang
        )
        print(f"Tool '{tool_name}' called for task_id='{task_id}' with kwargs={api_kwargs}", file=sys.stderr)
        success = await asyncio.to_thread(client.update_task, task_id=task_id, **api_kwargs) # type: ignore
        if success:
            updated_task = await asyncio.to_thread(client.get_task, task_id=task_id) # type: ignore
            return _serialize_response(updated_task)
        return _serialize_response({"status": "failed", "message": "Update operation did not report success."})
    except Exception as e:
        return _handle_tool_error(e, tool_name, task_id)

@mcp.tool()
async def complete_task(ctx: Context, task_id: str) -> str:
    """Complete a task. (Corresponds to 'close_task' in SDK v2+)"""
    tool_name = "complete_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' (close_task) called for task_id='{task_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.close_task, task_id=task_id) # type: ignore
        return _serialize_response({"success": success, "task_id": task_id, "action": "completed"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, task_id)

@mcp.tool()
async def uncomplete_task(ctx: Context, task_id: str) -> str:
    """Uncomplete a (completed) task. (Corresponds to 'reopen_task' in SDK v2+)"""
    tool_name = "uncomplete_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' (reopen_task) called for task_id='{task_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.reopen_task, task_id=task_id) # type: ignore
        return _serialize_response({"success": success, "task_id": task_id, "action": "reopened"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, task_id)

@mcp.tool()
async def move_task(
    ctx: Context,
    task_id: str,
    project_id: Optional[str] = None,
    section_id: Optional[str] = None,
    parent_id: Optional[str] = None 
) -> str:
    """Move a task to a different project or section. (parent_id might need update_task)"""
    tool_name = "move_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        if project_id is None and section_id is None and parent_id is None: # Adjusted condition
            return _serialize_response({"error": "Either project_id, section_id or parent_id must be provided for move_task (uses update_task)." })

        # Use update_task for moving, including parent_id
        api_kwargs = _prepare_api_kwargs(project_id=project_id, section_id=section_id, parent_id=parent_id)
        
        if not api_kwargs:
             return _serialize_response({"error": "No move parameters provided."})

        print(f"Tool '{tool_name}' (via update_task) called for task_id='{task_id}' with kwargs={api_kwargs}", file=sys.stderr)
        success = await asyncio.to_thread(client.update_task, task_id=task_id, **api_kwargs) # type: ignore
        if success:
            moved_task = await asyncio.to_thread(client.get_task, task_id=task_id) # type: ignore
            return _serialize_response(moved_task)
        return _serialize_response({"status": "failed", "message": "Move operation (via update_task) did not report success."})

    except Exception as e:
        return _handle_tool_error(e, tool_name, task_id)

@mcp.tool()
async def delete_task(ctx: Context, task_id: str) -> str:
    """Delete a task."""
    tool_name = "delete_task"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for task_id='{task_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_task, task_id=task_id) # type: ignore
        return _serialize_response({"success": success, "task_id": task_id, "action": "deleted"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, task_id)

@mcp.tool()
async def get_completed_tasks_by_due_date(
    ctx: Context,
    since: str, 
    until: str, 
    project_id: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get completed tasks within a due date range using filters."""
    tool_name = "get_completed_tasks_by_due_date"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})

        # Convert since/until to YYYY-MM-DD format if not already
        parsed_since = date.fromisoformat(since.split("T")[0]).strftime("%Y-%m-%d")
        parsed_until = date.fromisoformat(until.split("T")[0]).strftime("%Y-%m-%d")

        filter_str = f"all & (due after: {parsed_since} & due before: {parsed_until})"
        if project_id:
            filter_str += f" & project.id:{project_id}"
        
        api_kwargs = _prepare_api_kwargs(filter=filter_str, limit=limit)
        print(f"Tool '{tool_name}' called with filter='{filter_str}', limit={limit}", file=sys.stderr)
        
        tasks = await _fetch_all_from_paginator(client.get_tasks, **api_kwargs) # type: ignore
        return _serialize_response(tasks)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def get_completed_tasks_by_completion_date(
    ctx: Context,
    since: str, 
    until: str, 
    project_id: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get completed tasks within a completion date range using filters."""
    tool_name = "get_completed_tasks_by_completion_date"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})

        # Convert since/until to YYYY-MM-DD format if not already
        parsed_since = date.fromisoformat(since.split("T")[0]).strftime("%Y-%m-%d")
        parsed_until = date.fromisoformat(until.split("T")[0]).strftime("%Y-%m-%d")

        filter_str = f"all & (completed after: {parsed_since} & completed before: {parsed_until})"
        if project_id:
            filter_str += f" & project.id:{project_id}"
            
        api_kwargs = _prepare_api_kwargs(filter=filter_str, limit=limit)
        print(f"Tool '{tool_name}' called with filter='{filter_str}', limit={limit}", file=sys.stderr)
        
        tasks = await _fetch_all_from_paginator(client.get_tasks, **api_kwargs) # type: ignore
        return _serialize_response(tasks)
    except Exception as e:
        return _handle_tool_error(e, tool_name)


# --- Project Functions ---
@mcp.tool()
async def add_project(
    ctx: Context,
    name: str,
    description: Optional[str] = None,
    parent_id: Optional[str] = None,
    color: Optional[str] = None, 
    is_favorite: Optional[bool] = None,
    view_style: Optional[Literal["list", "board"]] = None
) -> str:
    """Create a new project."""
    tool_name = "add_project"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        api_kwargs = _prepare_api_kwargs(
            description=description, parent_id=parent_id, color=color,
            is_favorite=is_favorite, view_style=view_style
        )
        print(f"Tool '{tool_name}' called with name='{name}', kwargs={api_kwargs}", file=sys.stderr)
        project = await asyncio.to_thread(client.add_project, name=name, **api_kwargs) # type: ignore
        return _serialize_response(project)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def get_project(ctx: Context, project_id: str) -> str:
    """Get a project by its ID."""
    tool_name = "get_project"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called with project_id='{project_id}'", file=sys.stderr)
        project = await asyncio.to_thread(client.get_project, project_id=project_id) # type: ignore
        return _serialize_response(project)
    except Exception as e:
        return _handle_tool_error(e, tool_name, project_id)

@mcp.tool()
async def get_projects(ctx: Context, limit: Optional[int] = None) -> str:
    """Get all active projects."""
    tool_name = "get_projects"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        sdk_call_kwargs = {} 
        print(f"Tool '{tool_name}' called (limit: {limit})", file=sys.stderr)
        all_projects = await _fetch_all_from_paginator(client.get_projects, **sdk_call_kwargs) # type: ignore
        
        final_projects_list = all_projects[:limit] if limit is not None and limit >= 0 else all_projects
        return _serialize_response(final_projects_list)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def update_project(
    ctx: Context,
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = None, 
    is_favorite: Optional[bool] = None,
    view_style: Optional[Literal["list", "board"]] = None
) -> str:
    """Update an existing project."""
    tool_name = "update_project"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        api_kwargs = _prepare_api_kwargs(
            name=name, description=description, color=color,
            is_favorite=is_favorite, view_style=view_style
        )
        print(f"Tool '{tool_name}' called for project_id='{project_id}' with kwargs={api_kwargs}", file=sys.stderr)
        success = await asyncio.to_thread(client.update_project, project_id=project_id, **api_kwargs) # type: ignore
        if success:
            updated_project = await asyncio.to_thread(client.get_project, project_id=project_id) # type: ignore
            return _serialize_response(updated_project)
        return _serialize_response({"status": "failed", "message": "Update project operation did not report success."})
    except Exception as e:
        return _handle_tool_error(e, tool_name, project_id)

@mcp.tool()
async def archive_project(ctx: Context, project_id: str) -> str:
    """Archive a project."""
    tool_name = "archive_project"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for project_id='{project_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.archive_project, project_id=project_id) # type: ignore
        return _serialize_response({"success": success, "project_id": project_id, "action": "archived"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, project_id)

@mcp.tool()
async def unarchive_project(ctx: Context, project_id: str) -> str:
    """Unarchive a project."""
    tool_name = "unarchive_project"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for project_id='{project_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.unarchive_project, project_id=project_id) # type: ignore
        return _serialize_response({"success": success, "project_id": project_id, "action": "unarchived"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, project_id)

@mcp.tool()
async def delete_project(ctx: Context, project_id: str) -> str:
    """Delete a project."""
    tool_name = "delete_project"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for project_id='{project_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_project, project_id=project_id) # type: ignore
        return _serialize_response({"success": success, "project_id": project_id, "action": "deleted"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, project_id)

@mcp.tool()
async def get_collaborators(ctx: Context, project_id: str, limit: Optional[int] = None) -> str:
    """Get collaborators in a shared project."""
    tool_name = "get_collaborators"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for project_id='{project_id}'", file=sys.stderr)
        # client.get_collaborators does not typically support pagination or limit directly.
        collaborators = await asyncio.to_thread(client.get_collaborators, project_id=project_id) # type: ignore
        
        # Apply limit post-fetch if provided, as SDK might not support it.
        final_collaborators = collaborators[:limit] if limit is not None and limit >= 0 else collaborators
        return _serialize_response(final_collaborators)
    except Exception as e:
        return _handle_tool_error(e, tool_name, project_id)

# --- Section Functions ---
@mcp.tool()
async def add_section(
    ctx: Context,
    name: str,
    project_id: str,
    order: Optional[int] = None
) -> str:
    """Create a new section within a project."""
    tool_name = "add_section"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        api_kwargs = _prepare_api_kwargs(order=order)
        print(f"Tool '{tool_name}' called with name='{name}', project_id='{project_id}', kwargs={api_kwargs}", file=sys.stderr)
        section = await asyncio.to_thread(client.add_section, name=name, project_id=project_id, **api_kwargs) # type: ignore
        return _serialize_response(section)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def get_section(ctx: Context, section_id: str) -> str:
    """Get a specific section by its ID."""
    tool_name = "get_section"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called with section_id='{section_id}'", file=sys.stderr)
        section = await asyncio.to_thread(client.get_section, section_id=section_id) # type: ignore
        return _serialize_response(section)
    except Exception as e:
        return _handle_tool_error(e, tool_name, section_id)

@mcp.tool()
async def get_sections(
    ctx: Context,
    project_id: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get all active sections, optionally filtered by project_id."""
    tool_name = "get_sections"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        sdk_call_kwargs = _prepare_api_kwargs(project_id=project_id) 
        print(f"Tool '{tool_name}' called with sdk_kwargs={sdk_call_kwargs}, tool_limit={limit}", file=sys.stderr)
        all_sections = await _fetch_all_from_paginator(client.get_sections, **sdk_call_kwargs) # type: ignore
        
        final_sections_list = all_sections[:limit] if limit is not None and limit >= 0 else all_sections
        return _serialize_response(final_sections_list)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def update_section(
    ctx: Context,
    section_id: str,
    name: str
) -> str:
    """Update an existing section's name."""
    tool_name = "update_section"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for section_id='{section_id}' with name='{name}'", file=sys.stderr)
        success = await asyncio.to_thread(client.update_section, section_id=section_id, name=name) # type: ignore
        if success:
            updated_section = await asyncio.to_thread(client.get_section, section_id=section_id) # type: ignore
            return _serialize_response(updated_section)
        return _serialize_response({"status": "failed", "message": "Update section operation did not report success."})
    except Exception as e:
        return _handle_tool_error(e, tool_name, section_id)

@mcp.tool()
async def delete_section(ctx: Context, section_id: str) -> str:
    """Delete a section."""
    tool_name = "delete_section"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for section_id='{section_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_section, section_id=section_id) # type: ignore
        return _serialize_response({"success": success, "section_id": section_id, "action": "deleted"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, section_id)

# --- Label Functions ---
@mcp.tool()
async def add_label(
    ctx: Context,
    name: str,
    color: Optional[str] = None, 
    item_order: Optional[int] = None,
    is_favorite: Optional[bool] = None
) -> str:
    """Create a new personal label."""
    tool_name = "add_label"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        api_kwargs = _prepare_api_kwargs(color=color, item_order=item_order, is_favorite=is_favorite)
        print(f"Tool '{tool_name}' called with name='{name}', kwargs={api_kwargs}", file=sys.stderr)
        label = await asyncio.to_thread(client.add_label, name=name, **api_kwargs) # type: ignore
        return _serialize_response(label)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def get_label(ctx: Context, label_id: str) -> str:
    """Get a specific personal label by its ID."""
    tool_name = "get_label"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called with label_id='{label_id}'", file=sys.stderr)
        label = await asyncio.to_thread(client.get_label, label_id=label_id) # type: ignore
        return _serialize_response(label)
    except Exception as e:
        return _handle_tool_error(e, tool_name, label_id)

@mcp.tool()
async def get_labels(ctx: Context, limit: Optional[int] = None) -> str:
    """Get all personal labels."""
    tool_name = "get_labels"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        
        sdk_call_kwargs = {}
        print(f"Tool '{tool_name}' called (limit: {limit})", file=sys.stderr)
        all_labels = await _fetch_all_from_paginator(client.get_labels, **sdk_call_kwargs) # type: ignore
        
        final_labels_list = all_labels[:limit] if limit is not None and limit >= 0 else all_labels
        return _serialize_response(final_labels_list)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def update_label(
    ctx: Context,
    label_id: str,
    name: Optional[str] = None,
    color: Optional[str] = None, 
    item_order: Optional[int] = None,
    is_favorite: Optional[bool] = None
) -> str:
    """Update a personal label."""
    tool_name = "update_label"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        api_kwargs = _prepare_api_kwargs(name=name, color=color, item_order=item_order, is_favorite=is_favorite)
        print(f"Tool '{tool_name}' called for label_id='{label_id}' with kwargs={api_kwargs}", file=sys.stderr)
        success = await asyncio.to_thread(client.update_label, label_id=label_id, **api_kwargs) # type: ignore
        if success:
            updated_label = await asyncio.to_thread(client.get_label, label_id=label_id) # type: ignore
            return _serialize_response(updated_label)
        return _serialize_response({"status": "failed", "message": "Update label operation did not report success."})
    except Exception as e:
        return _handle_tool_error(e, tool_name, label_id)

@mcp.tool()
async def delete_label(ctx: Context, label_id: str) -> str:
    """Delete a personal label."""
    tool_name = "delete_label"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for label_id='{label_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_label, label_id=label_id) # type: ignore
        return _serialize_response({"success": success, "label_id": label_id, "action": "deleted"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, label_id)

@mcp.tool()
async def get_shared_labels(
    ctx: Context,
    omit_personal: bool = False, 
    limit: Optional[int] = None
) -> str:
    """Get shared label names or Label objects (SDK v2+)."""
    tool_name = "get_shared_labels"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
            
        print(f"Tool '{tool_name}' called with omit_personal={omit_personal}, limit={limit}", file=sys.stderr)
        
        all_labels_list = await _fetch_all_from_paginator(client.get_labels) # type: ignore
        
        processed_shared_labels: List[Label] = []
        for label_obj in all_labels_list:
            if label_obj.is_shared:
                if omit_personal:
                    # A shared label is "personal" if it's also a favorite.
                    # So, if omit_personal is True, we exclude shared labels that are also favorites.
                    if not label_obj.is_favorite:
                        processed_shared_labels.append(label_obj)
                else: # include all shared labels
                    processed_shared_labels.append(label_obj)
        
        final_shared_labels_data = processed_shared_labels[:limit] if limit is not None and limit >=0 else processed_shared_labels
        return _serialize_response(final_shared_labels_data) 
            
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def rename_shared_label(
    ctx: Context,
    name: str, # Old name
    new_name: str
) -> str:
    """Rename all occurrences of a shared label. (SDK v2: update label by ID)"""
    tool_name = "rename_shared_label"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
            
        print(f"Tool '{tool_name}' called for name='{name}' to new_name='{new_name}'", file=sys.stderr)
        all_labels = await asyncio.to_thread(client.get_labels) # type: ignore
        label_to_rename = None
        for lbl in all_labels: # type: ignore
            if lbl.name == name and lbl.is_shared:
                label_to_rename = lbl
                break
        
        if not label_to_rename:
            return _serialize_response({"error": f"Shared label '{name}' not found."})
        
        success_update = await asyncio.to_thread(client.update_label, label_id=label_to_rename.id, name=new_name) # type: ignore
        if success_update:
            updated_label = await asyncio.to_thread(client.get_label, label_id=label_to_rename.id) # type: ignore
            return _serialize_response(updated_label)
        return _serialize_response({"status": "failed", "message": f"Failed to rename shared label '{name}'."})

    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def remove_shared_label(ctx: Context, name: str) -> str:
    """Remove all occurrences of a shared label. (SDK v2: delete label by ID)"""
    tool_name = "remove_shared_label"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
            
        print(f"Tool '{tool_name}' called for name='{name}'", file=sys.stderr)
        all_labels = await asyncio.to_thread(client.get_labels) # type: ignore
        label_to_remove = None
        for lbl in all_labels: # type: ignore
            if lbl.name == name and lbl.is_shared:
                label_to_remove = lbl
                break
        
        if not label_to_remove:
            return _serialize_response({"error": f"Shared label '{name}' not found to remove."})
        
        success_delete = await asyncio.to_thread(client.delete_label, label_id=label_to_remove.id) # type: ignore
        return _serialize_response({"success": success_delete, "label_id": label_to_remove.id, "name": name, "action": "deleted"})

    except Exception as e:
        return _handle_tool_error(e, tool_name)

# --- Comment Functions ---
@mcp.tool()
async def add_comment(
    ctx: Context,
    content: str,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    attachment_file_name: Optional[str] = None,
    attachment_file_url: Optional[str] = None,
    attachment_file_type: Optional[str] = None, 
    attachment_resource_type: Optional[str] = None, 
    uids_to_notify: Optional[List[str]] = None
) -> str:
    """Create a new comment on a task or project."""
    tool_name = "add_comment"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})

        if project_id is None and task_id is None:
            return _serialize_response({"error": "Either project_id or task_id must be provided for add_comment."})

        attachment_obj: Optional[dict] = None
        if attachment_file_url: 
            attachment_obj = {
                "file_name": attachment_file_name,
                "file_url": attachment_file_url,
                "file_type": attachment_file_type,
                "resource_type": attachment_resource_type or "file"
            }

        api_kwargs = _prepare_api_kwargs(
            project_id=project_id, task_id=task_id, attachment=attachment_obj
        )
        if uids_to_notify:
            print(f"Warning: uids_to_notify ({uids_to_notify}) might not be directly supported by SDK add_comment. Consider @mentions in content.", file=sys.stderr)

        print(f"Tool '{tool_name}' called with content='{content}', kwargs={api_kwargs}", file=sys.stderr)
        comment = await asyncio.to_thread(client.add_comment, content=content, **api_kwargs) # type: ignore
        return _serialize_response(comment)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def get_comment(ctx: Context, comment_id: str) -> str:
    """Get a specific comment by its ID."""
    tool_name = "get_comment"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called with comment_id='{comment_id}'", file=sys.stderr)
        comment = await asyncio.to_thread(client.get_comment, comment_id=comment_id) # type: ignore
        return _serialize_response(comment)
    except Exception as e:
        return _handle_tool_error(e, tool_name, comment_id)

@mcp.tool()
async def get_comments(
    ctx: Context,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get comments for a task or project."""
    tool_name = "get_comments"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})

        if project_id is None and task_id is None:
            return _serialize_response({"error": "Either project_id or task_id must be provided for get_comments."})
            
        sdk_call_kwargs = {}
        if task_id:
            sdk_call_kwargs['task_id'] = task_id
        elif project_id:
            sdk_call_kwargs['project_id'] = project_id
            
        print(f"Tool '{tool_name}' called with sdk_kwargs={sdk_call_kwargs}, tool_limit={limit}", file=sys.stderr)
        # SDK get_comments might not take limit directly for total items.
        # _fetch_all_from_paginator handles pagination if client.get_comments uses it.
        # If limit is for SDK's pagination page size, it's handled there.
        # If client.get_comments takes a limit for total number of items, it should be passed directly.
        # Current _fetch_all_from_paginator does not pass limit down to the SDK call.
        # So, limit is applied post-fetch.
        all_comments = await _fetch_all_from_paginator(client.get_comments, **sdk_call_kwargs) # type: ignore
        
        final_comments_list = all_comments[:limit] if limit is not None and limit >= 0 else all_comments
        return _serialize_response(final_comments_list)
    except Exception as e:
        return _handle_tool_error(e, tool_name)

@mcp.tool()
async def update_comment(
    ctx: Context,
    comment_id: str,
    content: str
) -> str:
    """Update an existing comment's content."""
    tool_name = "update_comment"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for comment_id='{comment_id}' with new content.", file=sys.stderr)
        success = await asyncio.to_thread(client.update_comment, comment_id=comment_id, content=content) # type: ignore
        if success:
            updated_comment = await asyncio.to_thread(client.get_comment, comment_id=comment_id) # type: ignore
            return _serialize_response(updated_comment)
        return _serialize_response({"status": "failed", "message": "Update comment operation did not report success."})
    except Exception as e:
        return _handle_tool_error(e, tool_name, comment_id)

@mcp.tool()
async def delete_comment(ctx: Context, comment_id: str) -> str:
    """Delete a comment."""
    tool_name = "delete_comment"
    try:
        client = await _get_or_init_client(ctx, tool_name)
        if not client: return _serialize_response({"error": "Client could not be initialized."})
        print(f"Tool '{tool_name}' called for comment_id='{comment_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_comment, comment_id=comment_id) # type: ignore
        return _serialize_response({"success": success, "comment_id": comment_id, "action": "deleted"})
    except Exception as e:
        return _handle_tool_error(e, tool_name, comment_id)


# MODIFIED: main function for SSE host/port
async def main():
    transport = os.getenv("TRANSPORT", "stdio") 
    print(f"Starting Todoist MCP server with {transport} transport...", file=sys.stderr)

    if transport == "stdio":
        await mcp.run_stdio_async()
    elif transport == "sse" or transport == "streamable_http":
        if hasattr(mcp, "run_sse_async"):
            sse_host = os.getenv("MCP_HOST", "127.0.0.1") 
            sse_port_str = os.getenv("MCP_PORT", "8080")  
            try:
                sse_port = int(sse_port_str)
            except ValueError:
                print(f"Warning: Invalid MCP_PORT value '{sse_port_str}'. Defaulting to 8080.", file=sys.stderr)
                sse_port = 8080
            
            print(f"Attempting to run MCP server with SSE transport on {sse_host}:{sse_port}", file=sys.stderr)
            await mcp.run_sse_async(host=sse_host, port=sse_port)
        else:
            print("Error: mcp.run_sse_async() not found. SSE transport might not be supported by this FastMCP version or setup.", file=sys.stderr)
            print("Falling back to STDIO transport as a last resort.", file=sys.stderr)
            await mcp.run_stdio_async() 
    else:
        print(f"Error: Unknown transport '{transport}' specified. Supported transports: 'stdio', 'sse'. Defaulting to 'stdio'.", file=sys.stderr)
        await mcp.run_stdio_async() 


if __name__ == "__main__":
    print("Starting Todoist MCP server...", file=sys.stderr)
    asyncio.run(main())
    print("Todoist MCP server finished.", file=sys.stderr)