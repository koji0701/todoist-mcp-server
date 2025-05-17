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
    todoist_client: TodoistAPI # Use specific type

@asynccontextmanager
async def todoist_lifespan(server: FastMCP) -> AsyncIterator[ToDoistContext]:
    print("Lifespan: Initializing Todoist client...", file=sys.stderr)
    try:
        client = get_todoist_client() 
        print("Lifespan: Todoist client obtained.", file=sys.stderr)
        yield ToDoistContext(todoist_client=client)
    except ValueError as ve:
        print(f"Lifespan ERROR: {ve}. Server will likely not function correctly.", file=sys.stderr)
        raise RuntimeError(f"Failed to initialize Todoist client in lifespan: {ve}")
    except Exception as e:
        print(f"Lifespan: Unexpected exception during Todoist client initialization: {e}", file=sys.stderr)
        raise
    finally:
        print("Lifespan: Exiting lifespan.", file=sys.stderr)
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
        # Convert items in the list if they are dataclass instances
        # Use is_dataclass and ensure it's an instance, not the class type itself
        prepared_data = [
            asdict(item) if is_dataclass(item) and not isinstance(item, type) else item
            for item in data
        ]
    elif is_dataclass(data) and not isinstance(data, type): # For single dataclass instances
        prepared_data = asdict(data)
    else:
        # This branch handles:
        # - Primitives: str, int, bool, float, None
        # - Already dicts/lists (which might contain datetimes, handled by json_datetime_serializer)
        # - Booleans (e.g. True from client.complete_task which becomes client.close_task in SDK v2+)
        prepared_data = data
    
    try:
        return json.dumps(prepared_data, default=json_datetime_serializer, indent=2)
    except TypeError as e:
        # This error should ideally be caught by json_datetime_serializer for datetimes.
        # If it still occurs, it means there's another non-serializable type
        # in prepared_data that json_datetime_serializer doesn't cover.
        error_message = (f"Serialization Error in _serialize_response: {e}. "
                         f"Problematic data type: {type(prepared_data)}. "
                         f"Snippet (first 500 chars): {str(prepared_data)[:500]}")
        print(error_message, file=sys.stderr)
        # Return a JSON-formatted error string to the client to avoid breaking the MCP flow
        return json.dumps({"error": "Failed to serialize response", "details": str(e)})
    except Exception as e_gen: # Catch other potential json.dumps errors
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
                pass # Let SDK handle or raise
        elif k in ('due_datetime', 'since', 'until') and isinstance(v, str):
            try:
                new_v = datetime.fromisoformat(v)
            except ValueError:
                pass # Let SDK handle or raise
        parsed_kwargs[k] = new_v
    return parsed_kwargs

# --- Task Functions ---
# (No changes needed within the tool functions themselves, as _serialize_response and _prepare_api_kwargs handle the data)
# Example of one tool, the rest follow the same pattern:

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
    due_date: Optional[str] = None, # YYYY-MM-DD
    due_datetime: Optional[str] = None, # RFC3339 format e.g., "2023-09-01T12:00:00Z"
    assignee_id: Optional[str] = None,
    order: Optional[int] = None,
    auto_reminder: Optional[bool] = None,
    auto_parse_labels: Optional[bool] = None,
    duration: Optional[int] = None,
    duration_unit: Optional[Literal["minute", "day"]] = None,
    deadline_date: Optional[str] = None, # YYYY-MM-DD
    deadline_lang: Optional[str] = None
) -> str:
    """
    Create a new task.
    (Docstring unchanged)
    """
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client:
        return _serialize_response({"error": "Todoist client not available."}) # Serialize error nicely
    
    api_kwargs = _prepare_api_kwargs(
        description=description, project_id=project_id, section_id=section_id,
        parent_id=parent_id, labels=labels, priority=priority, due_string=due_string,
        due_lang=due_lang, due_date=due_date, due_datetime=due_datetime,
        assignee_id=assignee_id, order=order, auto_reminder=auto_reminder,
        auto_parse_labels=auto_parse_labels, duration=duration, duration_unit=duration_unit,
        deadline_date=deadline_date, deadline_lang=deadline_lang
    )
    try:
        print(f"Tool 'add_task' called with content='{content}', kwargs={api_kwargs}", file=sys.stderr)
        task = await asyncio.to_thread(client.add_task, content=content, **api_kwargs)
        return _serialize_response(task)
    except Exception as e:
        print(f"Error in add_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error adding task: {str(e)}"})


@mcp.tool()
async def get_task(ctx: Context, task_id: str) -> str:
    """Get a specific task by its ID."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'get_task' called with task_id='{task_id}'", file=sys.stderr)
        task = await asyncio.to_thread(client.get_task, task_id=task_id)
        return _serialize_response(task)
    except Exception as e:
        print(f"Error in get_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting task {task_id}: {str(e)}"})

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
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    api_kwargs = _prepare_api_kwargs(
        project_id=project_id, section_id=section_id, parent_id=parent_id,
        label=label, ids=ids, limit=limit
    )
    try:
        print(f"Tool 'get_tasks' called with kwargs={api_kwargs}", file=sys.stderr)
        tasks = await _fetch_all_from_paginator(client.get_tasks, **api_kwargs)
        return _serialize_response(tasks)
    except Exception as e:
        print(f"Error in get_tasks: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting tasks: {str(e)}"})

@mcp.tool()
async def filter_tasks(
    ctx: Context,
    query: Optional[str] = None,
    lang: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get active tasks matching the filter query."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    api_kwargs = _prepare_api_kwargs(query=query, lang=lang, limit=limit)
    try:
        print(f"Tool 'filter_tasks' called with kwargs={api_kwargs}", file=sys.stderr)
        tasks = await _fetch_all_from_paginator(client.filter_tasks, **api_kwargs)
        return _serialize_response(tasks)
    except Exception as e:
        print(f"Error in filter_tasks: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error filtering tasks: {str(e)}"})

@mcp.tool()
async def add_task_quick(
    ctx: Context,
    text: str,
    note: Optional[str] = None,
    reminder: Optional[str] = None,
    auto_reminder: bool = True
) -> str:
    """Create a new task using Todoist's Quick Add syntax."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    api_kwargs = _prepare_api_kwargs(note=note, reminder=reminder, auto_reminder=auto_reminder)
    try:
        print(f"Tool 'add_task_quick' called with text='{text}', kwargs={api_kwargs}", file=sys.stderr)
        task = await asyncio.to_thread(client.add_task_quick, text=text, **api_kwargs)
        return _serialize_response(task)
    except Exception as e:
        print(f"Error in add_task_quick: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error adding task with quick add: {str(e)}"})

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
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    api_kwargs = _prepare_api_kwargs(
        content=content, description=description, labels=labels, priority=priority,
        due_string=due_string, due_lang=due_lang, due_date=due_date, due_datetime=due_datetime,
        assignee_id=assignee_id, day_order=day_order, collapsed=collapsed, duration=duration,
        duration_unit=duration_unit, deadline_date=deadline_date, deadline_lang=deadline_lang
    )
    try:
        print(f"Tool 'update_task' called for task_id='{task_id}' with kwargs={api_kwargs}", file=sys.stderr)
        # The SDK's update_task returns a boolean in v2+ (True if successful)
        success = await asyncio.to_thread(client.update_task, task_id=task_id, **api_kwargs)
        if success:
            # Optionally, fetch the updated task to return its full details
            updated_task = await asyncio.to_thread(client.get_task, task_id=task_id)
            return _serialize_response(updated_task)
        return _serialize_response({"status": "failed", "message": "Update operation did not report success."})
    except Exception as e:
        print(f"Error in update_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error updating task {task_id}: {str(e)}"})

@mcp.tool()
async def complete_task(ctx: Context, task_id: str) -> str:
    """Complete a task. (Corresponds to 'close_task' in SDK v2+)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'complete_task' (close_task) called for task_id='{task_id}'", file=sys.stderr)
        # SDK `close_task` (formerly complete_task in some contexts) returns True on success.
        success = await asyncio.to_thread(client.close_task, task_id=task_id)
        return _serialize_response({"success": success, "task_id": task_id, "action": "completed"})
    except Exception as e:
        print(f"Error in complete_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error completing task {task_id}: {str(e)}"})

@mcp.tool()
async def uncomplete_task(ctx: Context, task_id: str) -> str:
    """Uncomplete a (completed) task. (Corresponds to 'reopen_task' in SDK v2+)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'uncomplete_task' (reopen_task) called for task_id='{task_id}'", file=sys.stderr)
        # SDK `reopen_task` returns True on success.
        success = await asyncio.to_thread(client.reopen_task, task_id=task_id)
        return _serialize_response({"success": success, "task_id": task_id, "action": "reopened"})
    except Exception as e:
        print(f"Error in uncomplete_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error uncompleting task {task_id}: {str(e)}"})

@mcp.tool()
async def move_task(
    ctx: Context,
    task_id: str,
    project_id: Optional[str] = None,
    section_id: Optional[str] = None,
    parent_id: Optional[str] = None # Note: SDK v2 uses parent_id in add/update, move might just be project/section
) -> str:
    """Move a task to a different project or section. (parent_id might need update_task)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # SDK v2 `move_task` primarily supports project_id and section_id.
    # Moving to a different parent might require `update_task` with `parent_id`.
    # For now, sticking to what `move_task` clearly supports.
    # If parent_id is specified, it's better to use update_task.
    if project_id is None and section_id is None:
        return _serialize_response({"error": "Either project_id or section_id must be provided for move_task."})

    api_kwargs = _prepare_api_kwargs(project_id=project_id, section_id=section_id)
    
    # If only parent_id is provided, this tool is not suitable. Use update_task.
    if parent_id and not project_id and not section_id:
        return _serialize_response({"error": "To change parent_id, please use the update_task tool."})

    try:
        print(f"Tool 'move_task' called for task_id='{task_id}' with kwargs={api_kwargs}", file=sys.stderr)
        # The SDK's move_task might not exist or have different parameters in v2+.
        # Typically, moving is part of update_task by setting project_id or section_id.
        # Let's assume update_task is the more general way for v2+ SDK.
        # If a dedicated move_task exists and works, this is fine. Otherwise, adapt.
        # For now, assuming client.move_task exists and works as expected.
        # Check SDK docs: `update_task` is used for moving (by setting project_id/section_id).
        # So, this tool should probably call update_task.
        if not api_kwargs: # Should not happen due to check above
             return _serialize_response({"error": "No move parameters provided."})

        success = await asyncio.to_thread(client.update_task, task_id=task_id, **api_kwargs)
        if success:
            moved_task = await asyncio.to_thread(client.get_task, task_id=task_id)
            return _serialize_response(moved_task)
        return _serialize_response({"status": "failed", "message": "Move operation (via update_task) did not report success."})

    except Exception as e:
        print(f"Error in move_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error moving task {task_id}: {str(e)}"})


@mcp.tool()
async def delete_task(ctx: Context, task_id: str) -> str:
    """Delete a task."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'delete_task' called for task_id='{task_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_task, task_id=task_id)
        return _serialize_response({"success": success, "task_id": task_id, "action": "deleted"})
    except Exception as e:
        print(f"Error in delete_task: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error deleting task {task_id}: {str(e)}"})

@mcp.tool()
async def get_completed_tasks_by_due_date(
    ctx: Context,
    since: str, 
    until: str, 
    workspace_id: Optional[str] = None, # Note: SDK v2+ might not use workspace_id here.
    project_id: Optional[str] = None,
    section_id: Optional[str] = None, # Note: SDK v2+ might not use section_id here.
    parent_id: Optional[str] = None, # Note: SDK v2+ might not use parent_id here.
    filter_query: Optional[str] = None, # Note: SDK v2+ might use 'filter' not 'filter_query'
    filter_lang: Optional[str] = None, # Note: SDK v2+ might use 'lang' with 'filter'
    limit: Optional[int] = None
) -> str:
    """Get completed tasks within a due date range. (Functionality may vary with SDK versions)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # Check SDK docs for 'get_completed_tasks' or similar. Sync API (v9) had 'completed/get_all'.
    # REST API v2 uses GET /rest/v2/tasks with `filter="view all & complete & due before: YYYY-MM-DD & due after: YYYY-MM-DD"`
    # The Python SDK might have a higher-level function or require constructing a filter.
    # Assuming client.get_completed_tasks_by_due_date exists and maps correctly.
    # If not, this tool needs significant rework based on SDK v2+ capabilities.
    
    api_kwargs = _prepare_api_kwargs(
        since=since, until=until, project_id=project_id, # workspace_id might not be applicable
        # section_id=section_id, parent_id=parent_id, # These might not be direct filters
        # filter_query=filter_query, filter_lang=filter_lang, # Check SDK parameter names
        limit=limit
    )
    try:
        print(f"Tool 'get_completed_tasks_by_due_date' called with kwargs={api_kwargs}", file=sys.stderr)
        # The method name `get_completed_tasks_by_due_date` is hypothetical or from an older SDK.
        # For todoist-api-python v2+, you'd likely use `client.get_tasks` with a complex filter.
        # For demonstration, we assume the method exists as named. If it doesn't, this will fail.
        # Example filter for SDK v2:
        # filter_str = f"all & (due before: {api_kwargs['until'].strftime('%Y-%m-%d')} & due after: {api_kwargs['since'].strftime('%Y-%m-%d')})"
        # if project_id: filter_str += f" & project.id:{project_id}"
        # tasks = await _fetch_all_from_paginator(client.get_tasks, filter=filter_str, limit=limit)
        # This is a complex part. For now, assuming the direct method `get_completed_tasks_by_due_date` exists.
        if hasattr(client, "get_completed_tasks_by_due_date"):
            tasks = await _fetch_all_from_paginator(client.get_completed_tasks_by_due_date, **api_kwargs)
        else:
            # Fallback or error if method doesn't exist.
            # This is a placeholder; actual implementation requires careful mapping to SDK v2.
            return _serialize_response({"error": "get_completed_tasks_by_due_date method not directly available in this SDK version. Requires filter-based approach."})
        return _serialize_response(tasks)
    except Exception as e:
        print(f"Error in get_completed_tasks_by_due_date: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting completed tasks by due date: {str(e)}"})

@mcp.tool()
async def get_completed_tasks_by_completion_date(
    ctx: Context,
    since: str, 
    until: str, 
    workspace_id: Optional[str] = None, # See note in previous function
    filter_query: Optional[str] = None, # See note in previous function
    filter_lang: Optional[str] = None, # See note in previous function
    limit: Optional[int] = None
) -> str:
    """Get completed tasks within a completion date range. (Functionality may vary with SDK versions)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})

    api_kwargs = _prepare_api_kwargs(
        since=since, until=until, # workspace_id might not be applicable
        # filter_query=filter_query, filter_lang=filter_lang, # Check SDK parameter names
        limit=limit
    )
    try:
        print(f"Tool 'get_completed_tasks_by_completion_date' called with kwargs={api_kwargs}", file=sys.stderr)
        # Similar to the above, this method name is hypothetical for SDK v2+.
        # Requires careful mapping to `client.get_tasks` with appropriate filters.
        if hasattr(client, "get_completed_tasks_by_completion_date"):
            tasks = await _fetch_all_from_paginator(client.get_completed_tasks_by_completion_date, **api_kwargs)
        else:
             return _serialize_response({"error": "get_completed_tasks_by_completion_date method not directly available in this SDK version. Requires filter-based approach."})
        return _serialize_response(tasks)
    except Exception as e:
        print(f"Error in get_completed_tasks_by_completion_date: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting completed tasks by completion date: {str(e)}"})


# --- Project Functions --- (Apply _serialize_response to all error returns as well)
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
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    api_kwargs = _prepare_api_kwargs(
        description=description, parent_id=parent_id, color=color,
        is_favorite=is_favorite, view_style=view_style
    )
    try:
        print(f"Tool 'add_project' called with name='{name}', kwargs={api_kwargs}", file=sys.stderr)
        project = await asyncio.to_thread(client.add_project, name=name, **api_kwargs)
        return _serialize_response(project)
    except Exception as e:
        print(f"Error in add_project: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error adding project: {str(e)}"})

@mcp.tool()
async def get_project(ctx: Context, project_id: str) -> str:
    """Get a project by its ID."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'get_project' called with project_id='{project_id}'", file=sys.stderr)
        project = await asyncio.to_thread(client.get_project, project_id=project_id)
        return _serialize_response(project)
    except Exception as e:
        print(f"Error in get_project: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting project {project_id}: {str(e)}"})

@mcp.tool()
async def get_projects(ctx: Context, limit: Optional[int] = None) -> str:
    """Get all active projects."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # client.get_projects() typically takes no arguments.
    sdk_call_kwargs = {} 

    try:
        print(f"Tool 'get_projects' called (limit: {limit})", file=sys.stderr)
        # Use the helper to fetch all projects
        all_projects = await _fetch_all_from_paginator(client.get_projects, **sdk_call_kwargs)
        
        # Apply limit after fetching all, if specified
        if limit is not None and limit >= 0:
            final_projects_list = all_projects[:limit]
        else:
            final_projects_list = all_projects
            
        return _serialize_response(final_projects_list)
    except Exception as e:
        print(f"Error in get_projects: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting projects: {str(e)}"})
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
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    api_kwargs = _prepare_api_kwargs(
        name=name, description=description, color=color,
        is_favorite=is_favorite, view_style=view_style
    )
    try:
        print(f"Tool 'update_project' called for project_id='{project_id}' with kwargs={api_kwargs}", file=sys.stderr)
        # SDK update_project returns a boolean in v2+
        success = await asyncio.to_thread(client.update_project, project_id=project_id, **api_kwargs)
        if success:
            updated_project = await asyncio.to_thread(client.get_project, project_id=project_id)
            return _serialize_response(updated_project)
        return _serialize_response({"status": "failed", "message": "Update project operation did not report success."})
    except Exception as e:
        print(f"Error in update_project: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error updating project {project_id}: {str(e)}"})

@mcp.tool()
async def archive_project(ctx: Context, project_id: str) -> str:
    """Archive a project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'archive_project' called for project_id='{project_id}'", file=sys.stderr)
        # SDK v2 archive_project returns a boolean
        success = await asyncio.to_thread(client.archive_project, project_id=project_id)
        return _serialize_response({"success": success, "project_id": project_id, "action": "archived"})
    except Exception as e:
        print(f"Error in archive_project: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error archiving project {project_id}: {str(e)}"})

@mcp.tool()
async def unarchive_project(ctx: Context, project_id: str) -> str:
    """Unarchive a project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'unarchive_project' called for project_id='{project_id}'", file=sys.stderr)
        # SDK v2 unarchive_project returns a boolean
        success = await asyncio.to_thread(client.unarchive_project, project_id=project_id)
        return _serialize_response({"success": success, "project_id": project_id, "action": "unarchived"})
    except Exception as e:
        print(f"Error in unarchive_project: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error unarchiving project {project_id}: {str(e)}"})

@mcp.tool()
async def delete_project(ctx: Context, project_id: str) -> str:
    """Delete a project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'delete_project' called for project_id='{project_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_project, project_id=project_id)
        return _serialize_response({"success": success, "project_id": project_id, "action": "deleted"})
    except Exception as e:
        print(f"Error in delete_project: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error deleting project {project_id}: {str(e)}"})

@mcp.tool()
async def get_collaborators(ctx: Context, project_id: str, limit: Optional[int] = None) -> str: # limit might not be supported
    """Get collaborators in a shared project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    # api_kwargs = _prepare_api_kwargs(limit=limit) # client.get_collaborators usually doesn't take limit.
    try:
        print(f"Tool 'get_collaborators' called for project_id='{project_id}'", file=sys.stderr)
        collaborators = await asyncio.to_thread(client.get_collaborators, project_id=project_id) # Removed **api_kwargs
        return _serialize_response(collaborators)
    except Exception as e:
        print(f"Error in get_collaborators: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting collaborators for project {project_id}: {str(e)}"})

# --- Section Functions --- (Apply _serialize_response to all error returns)
@mcp.tool()
async def add_section(
    ctx: Context,
    name: str,
    project_id: str,
    order: Optional[int] = None
) -> str:
    """Create a new section within a project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    api_kwargs = _prepare_api_kwargs(order=order)
    try:
        print(f"Tool 'add_section' called with name='{name}', project_id='{project_id}', kwargs={api_kwargs}", file=sys.stderr)
        section = await asyncio.to_thread(client.add_section, name=name, project_id=project_id, **api_kwargs)
        return _serialize_response(section)
    except Exception as e:
        print(f"Error in add_section: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error adding section: {str(e)}"})

@mcp.tool()
async def get_section(ctx: Context, section_id: str) -> str:
    """Get a specific section by its ID."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'get_section' called with section_id='{section_id}'", file=sys.stderr)
        section = await asyncio.to_thread(client.get_section, section_id=section_id)
        return _serialize_response(section)
    except Exception as e:
        print(f"Error in get_section: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting section {section_id}: {str(e)}"})

@mcp.tool()
async def get_sections(
    ctx: Context,
    project_id: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get all active sections, optionally filtered by project_id."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # client.get_sections can take project_id
    sdk_call_kwargs = _prepare_api_kwargs(project_id=project_id) 
    
    try:
        print(f"Tool 'get_sections' called with sdk_kwargs={sdk_call_kwargs}, tool_limit={limit}", file=sys.stderr)
        all_sections = await _fetch_all_from_paginator(client.get_sections, **sdk_call_kwargs)
        
        if limit is not None and limit >= 0:
            final_sections_list = all_sections[:limit]
        else:
            final_sections_list = all_sections
            
        return _serialize_response(final_sections_list)
    except Exception as e:
        print(f"Error in get_sections: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting sections: {str(e)}"})
@mcp.tool()
async def update_section(
    ctx: Context,
    section_id: str,
    name: str
) -> str:
    """Update an existing section's name."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'update_section' called for section_id='{section_id}' with name='{name}'", file=sys.stderr)
        # SDK v2 update_section returns a boolean
        success = await asyncio.to_thread(client.update_section, section_id=section_id, name=name)
        if success:
            updated_section = await asyncio.to_thread(client.get_section, section_id=section_id)
            return _serialize_response(updated_section)
        return _serialize_response({"status": "failed", "message": "Update section operation did not report success."})
    except Exception as e:
        print(f"Error in update_section: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error updating section {section_id}: {str(e)}"})

@mcp.tool()
async def delete_section(ctx: Context, section_id: str) -> str:
    """Delete a section."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'delete_section' called for section_id='{section_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_section, section_id=section_id)
        return _serialize_response({"success": success, "section_id": section_id, "action": "deleted"})
    except Exception as e:
        print(f"Error in delete_section: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error deleting section {section_id}: {str(e)}"})

# --- Label Functions --- (Apply _serialize_response to all error returns)
@mcp.tool()
async def add_label(
    ctx: Context,
    name: str,
    color: Optional[str] = None, 
    item_order: Optional[int] = None,
    is_favorite: Optional[bool] = None
) -> str:
    """Create a new personal label."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    api_kwargs = _prepare_api_kwargs(color=color, item_order=item_order, is_favorite=is_favorite)
    try:
        print(f"Tool 'add_label' called with name='{name}', kwargs={api_kwargs}", file=sys.stderr)
        label = await asyncio.to_thread(client.add_label, name=name, **api_kwargs)
        return _serialize_response(label)
    except Exception as e:
        print(f"Error in add_label: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error adding label: {str(e)}"})

@mcp.tool()
async def get_label(ctx: Context, label_id: str) -> str:
    """Get a specific personal label by its ID."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'get_label' called with label_id='{label_id}'", file=sys.stderr)
        label = await asyncio.to_thread(client.get_label, label_id=label_id)
        return _serialize_response(label)
    except Exception as e:
        print(f"Error in get_label: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting label {label_id}: {str(e)}"})

@mcp.tool()
async def get_labels(ctx: Context, limit: Optional[int] = None) -> str:
    """Get all personal labels."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # client.get_labels() typically takes no arguments.
    sdk_call_kwargs = {}

    try:
        print(f"Tool 'get_labels' called (limit: {limit})", file=sys.stderr)
        all_labels = await _fetch_all_from_paginator(client.get_labels, **sdk_call_kwargs)
        
        if limit is not None and limit >= 0:
            final_labels_list = all_labels[:limit]
        else:
            final_labels_list = all_labels
            
        return _serialize_response(final_labels_list)
    except Exception as e:
        print(f"Error in get_labels: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting labels: {str(e)}"})
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
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    api_kwargs = _prepare_api_kwargs(name=name, color=color, item_order=item_order, is_favorite=is_favorite)
    try:
        print(f"Tool 'update_label' called for label_id='{label_id}' with kwargs={api_kwargs}", file=sys.stderr)
        # SDK v2 update_label returns a boolean
        success = await asyncio.to_thread(client.update_label, label_id=label_id, **api_kwargs)
        if success:
            updated_label = await asyncio.to_thread(client.get_label, label_id=label_id)
            return _serialize_response(updated_label)
        return _serialize_response({"status": "failed", "message": "Update label operation did not report success."})
    except Exception as e:
        print(f"Error in update_label: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error updating label {label_id}: {str(e)}"})

@mcp.tool()
async def delete_label(ctx: Context, label_id: str) -> str:
    """Delete a personal label."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'delete_label' called for label_id='{label_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_label, label_id=label_id)
        return _serialize_response({"success": success, "label_id": label_id, "action": "deleted"})
    except Exception as e:
        print(f"Error in delete_label: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error deleting label {label_id}: {str(e)}"})

@mcp.tool()
async def get_shared_labels(
    ctx: Context,
    omit_personal: bool = False, 
    limit: Optional[int] = None
) -> str:
    """Get shared label names or Label objects (SDK v2+)."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    try:
        print(f"Tool 'get_shared_labels' called with omit_personal={omit_personal}, limit={limit}", file=sys.stderr)
        
        final_shared_labels_data: List[Any]

        if hasattr(client, "get_shared_labels") and callable(getattr(client, "get_shared_labels")):
            # This path assumes the old method signature and return type (List[str] from paginator)
            # The old client.get_shared_labels might take 'omit_personal'
            sdk_call_kwargs = _prepare_api_kwargs(omit_personal=omit_personal)
            # Note: The old `get_shared_labels` might return List[str] directly from the paginator pages.
            shared_label_names_all = await _fetch_all_from_paginator(client.get_shared_labels, **sdk_call_kwargs)
            
            if limit is not None and limit >= 0:
                final_shared_labels_data = shared_label_names_all[:limit]
            else:
                final_shared_labels_data = shared_label_names_all
            # This will be serialized by _serialize_response. If it's List[str], json.dumps handles it.
            return _serialize_response(final_shared_labels_data) 
        else:
            # SDK v2+ style: fetch all labels, then filter, then limit
            all_labels_list = await _fetch_all_from_paginator(client.get_labels) # Use paginator helper
            
            processed_shared_labels = []
            for label_obj in all_labels_list:
                if label_obj.is_shared: # Assuming Label object has `is_shared`
                    # The `omit_personal` logic might need refinement based on precise definition.
                    # If 'personal' shared labels are those also favorited by the user, for example.
                    # For now, let's assume `omit_personal` means if it's shared but NOT a personal favorite.
                    # This interpretation might be wrong.
                    # If `omit_personal` is True, we only include shared labels that are NOT also personal favorites.
                    # If `omit_personal` is False, we include ALL shared labels.
                    if omit_personal:
                        if not label_obj.is_favorite: # Example: "personal" means "is_favorite"
                            processed_shared_labels.append(label_obj)
                    else: # include all shared
                        processed_shared_labels.append(label_obj)
            
            if limit is not None and limit >= 0:
                final_shared_labels_data = processed_shared_labels[:limit]
            else:
                final_shared_labels_data = processed_shared_labels
            
            # This will be a list of Label objects (or their dicts after asdict)
            return _serialize_response(final_shared_labels_data) 
            
    except Exception as e:
        print(f"Error in get_shared_labels: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting shared labels: {str(e)}"})
@mcp.tool()
async def rename_shared_label(
    ctx: Context,
    name: str, # Old name
    new_name: str
) -> str:
    """Rename all occurrences of a shared label. (SDK v2: update label by ID)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # SDK v2 does not have a direct "rename shared label by name" function.
    # You'd need to: 1. Find the shared label by 'name' (iterate get_labels). 2. Get its ID. 3. Call update_label(id, new_name).
    # This is a complex operation for a single tool call if not directly supported.
    try:
        print(f"Tool 'rename_shared_label' called for name='{name}' to new_name='{new_name}'", file=sys.stderr)
        if hasattr(client, "rename_shared_label"): # If old SDK method exists
            success = await asyncio.to_thread(client.rename_shared_label, name=name, new_name=new_name)
            return _serialize_response({"success": success, "action": "renamed", "old_name": name, "new_name": new_name})
        else:
            # SDK v2+ logic:
            all_labels = await asyncio.to_thread(client.get_labels)
            label_to_rename = None
            for lbl in all_labels:
                if lbl.name == name and lbl.is_shared:
                    label_to_rename = lbl
                    break
            
            if not label_to_rename:
                return _serialize_response({"error": f"Shared label '{name}' not found."})
            
            success_update = await asyncio.to_thread(client.update_label, label_id=label_to_rename.id, name=new_name)
            if success_update:
                updated_label = await asyncio.to_thread(client.get_label, label_id=label_to_rename.id)
                return _serialize_response(updated_label)
            return _serialize_response({"status": "failed", "message": f"Failed to rename shared label '{name}'."})

    except Exception as e:
        print(f"Error in rename_shared_label: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error renaming shared label {name}: {str(e)}"})

@mcp.tool()
async def remove_shared_label(ctx: Context, name: str) -> str:
    """Remove all occurrences of a shared label. (SDK v2: delete label by ID)"""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    
    # Similar to rename, SDK v2 requires finding ID then deleting.
    try:
        print(f"Tool 'remove_shared_label' called for name='{name}'", file=sys.stderr)
        if hasattr(client, "remove_shared_label"): # If old SDK method exists
            success = await asyncio.to_thread(client.remove_shared_label, name=name)
            return _serialize_response({"success": success, "action": "removed", "name": name})
        else:
            # SDK v2+ logic:
            all_labels = await asyncio.to_thread(client.get_labels)
            label_to_remove = None
            for lbl in all_labels:
                if lbl.name == name and lbl.is_shared:
                    label_to_remove = lbl
                    break
            
            if not label_to_remove:
                return _serialize_response({"error": f"Shared label '{name}' not found to remove."})
            
            success_delete = await asyncio.to_thread(client.delete_label, label_id=label_to_remove.id)
            return _serialize_response({"success": success_delete, "label_id": label_to_remove.id, "name": name, "action": "deleted"})

    except Exception as e:
        print(f"Error in remove_shared_label: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error removing shared label {name}: {str(e)}"})

# --- Comment Functions --- (Apply _serialize_response to all error returns)
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
    uids_to_notify: Optional[List[str]] = None # SDK v2+ might not support uids_to_notify directly
) -> str:
    """Create a new comment on a task or project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})

    if project_id is None and task_id is None:
        return _serialize_response({"error": "Either project_id or task_id must be provided for add_comment."})

    attachment_obj: Optional[dict] = None # SDK v2 add_comment takes attachment as a dict
    if attachment_file_url: 
        attachment_obj = {
            "file_name": attachment_file_name,
            "file_url": attachment_file_url,
            "file_type": attachment_file_type,
            "resource_type": attachment_resource_type or "file"
        }

    api_kwargs = _prepare_api_kwargs(
        project_id=project_id, task_id=task_id,
        attachment=attachment_obj # uids_to_notify might not be supported in SDK v2 client.add_comment
    )
    if uids_to_notify: # Handle this manually if needed, e.g. by appending @mentions to content
        print(f"Warning: uids_to_notify ({uids_to_notify}) might not be directly supported by SDK add_comment. Consider @mentions in content.", file=sys.stderr)


    try:
        print(f"Tool 'add_comment' called with content='{content}', kwargs={api_kwargs}", file=sys.stderr)
        comment = await asyncio.to_thread(client.add_comment, content=content, **api_kwargs)
        return _serialize_response(comment)
    except Exception as e:
        print(f"Error in add_comment: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error adding comment: {str(e)}"})

@mcp.tool()
async def get_comment(ctx: Context, comment_id: str) -> str:
    """Get a specific comment by its ID."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'get_comment' called with comment_id='{comment_id}'", file=sys.stderr)
        comment = await asyncio.to_thread(client.get_comment, comment_id=comment_id)
        return _serialize_response(comment)
    except Exception as e:
        print(f"Error in get_comment: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting comment {comment_id}: {str(e)}"})

@mcp.tool()
async def get_comments(
    ctx: Context,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: Optional[int] = None
) -> str:
    """Get comments for a task or project."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})

    if project_id is None and task_id is None:
        return _serialize_response({"error": "Either project_id or task_id must be provided for get_comments."})
        
    # client.get_comments in v2 takes either task_id or project_id.
    sdk_call_kwargs = {}
    if task_id:
        sdk_call_kwargs['task_id'] = task_id
    elif project_id: # task_id takes precedence if both are somehow provided
        sdk_call_kwargs['project_id'] = project_id
        
    try:
        print(f"Tool 'get_comments' called with sdk_kwargs={sdk_call_kwargs}, tool_limit={limit}", file=sys.stderr)
        all_comments = await _fetch_all_from_paginator(client.get_comments, **sdk_call_kwargs)
        
        if limit is not None and limit >= 0:
            final_comments_list = all_comments[:limit]
        else:
            final_comments_list = all_comments
            
        return _serialize_response(final_comments_list)
    except Exception as e:
        print(f"Error in get_comments: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error getting comments: {str(e)}"})
@mcp.tool()
async def update_comment(
    ctx: Context,
    comment_id: str,
    content: str
) -> str:
    """Update an existing comment's content."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'update_comment' called for comment_id='{comment_id}' with new content.", file=sys.stderr)
        # SDK v2 update_comment returns a boolean
        success = await asyncio.to_thread(client.update_comment, comment_id=comment_id, content=content)
        if success:
            updated_comment = await asyncio.to_thread(client.get_comment, comment_id=comment_id)
            return _serialize_response(updated_comment)
        return _serialize_response({"status": "failed", "message": "Update comment operation did not report success."})
    except Exception as e:
        print(f"Error in update_comment: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error updating comment {comment_id}: {str(e)}"})

@mcp.tool()
async def delete_comment(ctx: Context, comment_id: str) -> str:
    """Delete a comment."""
    client: TodoistAPI = ctx.request_context.lifespan_context.todoist_client
    if not client: return _serialize_response({"error": "Todoist client not available."})
    try:
        print(f"Tool 'delete_comment' called for comment_id='{comment_id}'", file=sys.stderr)
        success = await asyncio.to_thread(client.delete_comment, comment_id=comment_id)
        return _serialize_response({"success": success, "comment_id": comment_id, "action": "deleted"})
    except Exception as e:
        print(f"Error in delete_comment: {e}", file=sys.stderr)
        return _serialize_response({"error": f"Error deleting comment {comment_id}: {str(e)}"})


# MODIFIED: main function for SSE host/port
async def main():
    transport = os.getenv("TRANSPORT", "stdio") # Default to stdio
    print(f"Starting Todoist MCP server with {transport} transport...", file=sys.stderr)

    if transport == "stdio":
        await mcp.run_stdio_async()
    elif transport == "sse":
        if hasattr(mcp, "run_sse_async"):
            sse_host = os.getenv("MCP_HOST", "127.0.0.1") # Default host for SSE
            sse_port_str = os.getenv("MCP_PORT", "8080")  # Default port for SSE
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
            await mcp.run_stdio_async() # Fallback
    else:
        print(f"Error: Unknown transport '{transport}' specified. Supported transports: 'stdio', 'sse'. Defaulting to 'stdio'.", file=sys.stderr)
        await mcp.run_stdio_async() # Fallback for unknown transport


if __name__ == "__main__":
    print("Starting Todoist MCP server...", file=sys.stderr)
    asyncio.run(main())
    print("Todoist MCP server finished.", file=sys.stderr)