# Todoist MCP Server

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE) <!-- Assuming MIT, replace if different or remove -->

The Todoist MCP Server provides a [Message Control Protocol (MCP)](https://github.com/anthropics/mcp/) interface to interact with the Todoist API. It allows MCP clients to manage Todoist tasks, projects, labels, comments, and more, by exposing various Todoist functionalities as MCP tools. This server is built using `fastmcp` and the `todoist-api-python` library.

## About The Project

This server acts as a bridge between an MCP client and your Todoist account. You can run this server locally, and an MCP-compatible client (like a Large Language Model agent) can then call its tools to perform actions in your Todoist.

Key functionalities include:
- Creating, reading, updating, and deleting tasks, projects, sections, labels, and comments.
- Fetching data with filters and pagination.
- Support for both `stdio` and `SSE` (Server-Sent Events) transport for MCP communication.

## Features

- **Comprehensive Todoist API Coverage:** Exposes a wide range of Todoist API functionalities.
- **Task Management:** Add, get, list, filter, quick add, update, complete, uncomplete, move, and delete tasks.
- **Project Management:** Add, get, list, update, archive, unarchive, delete projects, and list project collaborators.
- **Section Management:** Add, get, list, update, and delete sections within projects.
- **Label Management:** Add, get, list, update, delete personal labels, and manage shared labels.
- **Comment Management:** Add, get, list, update, and delete comments on tasks or projects.
- **Flexible Transport:** Supports `stdio` for local communication and `SSE` for network-based communication.
- **Robust Serialization:** Handles Todoist API responses, including `datetime` objects, correctly for JSON-based MCP.
- **Environment-Based Configuration:** Easy setup using a `.env` file.

## Prerequisites

- **Python:** Version 3.12 or higher.
- **Todoist Account:** A valid Todoist account.
- **Todoist API Token:** You can get your API token from your Todoist App: Settings -> Integrations -> Developer API Token.
- **Package Manager:** Either `uv` (recommended for speed) or `pip` with `venv`/`conda`.

## Installation

Choose one of the following installation methods:

### Method 1: Using `uv` (Recommended)

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/todoist-mcp-server.git # Replace with actual URL
    cd todoist-mcp-server
    ```

2.  **Install `uv` (if you haven't already):**
    ```bash
    pip install uv  # Or follow official uv installation instructions
    ```

3.  **Install dependencies using `uv`:**
    `uv` will automatically create a virtual environment if one doesn't exist or use the existing one if `.venv` is present.
    ```bash
    uv pip install .
    ```

4.  **Set up environment variables:**
    Create a `.env` file in the project root directory (`todoist-mcp-server/.env`):
    ```env
    TODOIST_API_TOKEN="YOUR_TODOIST_API_TOKEN"

    # Optional: For SSE transport (defaults to stdio if not set or when using with Claude Desktop as shown below)
    # TRANSPORT="sse"
    # MCP_HOST="127.0.0.1"  # Default host for SSE
    # MCP_PORT="8080"       # Default port for SSE
    ```
    Replace `"YOUR_TODOIST_API_TOKEN"` with your actual Todoist API token.

### Method 2: Using `pip` and `venv`

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/todoist-mcp-server.git # Replace with actual URL
    cd todoist-mcp-server
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

3.  **Install dependencies using `pip`:**
    ```bash
    pip install .
    ```

4.  **Set up environment variables:**
    Follow step 4 from the `uv` installation method.

### Method 3: Using `conda`

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/todoist-mcp-server.git # Replace with actual URL
    cd todoist-mcp-server
    ```

2.  **Create and activate a conda environment:**
    ```bash
    conda create -n todoist-mcp python=3.12
    conda activate todoist-mcp
    ```

3.  **Install `pip` into the conda environment (if not already available):**
    ```bash
    conda install pip
    ```

4.  **Install dependencies using `pip` within the conda environment:**
    ```bash
    pip install .
    ```

5.  **Set up environment variables:**
    Follow step 4 from the `uv` installation method.

## Usage

1.  **Run the server:**
    Navigate to the project directory.

    *   **If using `uv`:**
        ```bash
        uv run server.py
        ```
        (`uv run` executes the command within the project's managed environment.)

    *   **If using `pip` with `venv` or `conda` (ensure the environment is activated):**
        ```bash
        python server.py
        ```
    You should see log messages indicating the server has started, e.g., `Starting Todoist MCP server with stdio transport...` or similar if SSE is configured.

2.  **Transport Modes:**
    The server can communicate with MCP clients using two transport modes, configured via the `TRANSPORT` environment variable (e.g., in your `.env` file or directly in the execution environment like in the Claude Desktop example).

    *   **`stdio` (default):** The server communicates over standard input/output.
        *   **When to use:** This mode is ideal for local MCP clients that manage the server as a subprocess. For example, **Claude Desktop's custom tools feature typically relies on `stdio` communication.** If `TRANSPORT` is not set, it defaults to `stdio`.
    *   **`SSE` (Server-Sent Events):** The server uses Server-Sent Events over HTTP.
        *   **When to use:** This mode is suitable for network-based MCP clients or when the server needs to be accessible over a network.
        *   To use SSE, set `TRANSPORT=sse` in your `.env` file.
        *   The host can be configured with `MCP_HOST` (default: `127.0.0.1`).
        *   The port can be configured with `MCP_PORT` (default: `8080`).

3.  **Interacting with the server (general):**
    This server is designed to be used by an MCP client. For testing, if you have the `mcp` CLI tool installed:

    **Example using `mcp` CLI with a server running in `SSE` mode (on default http://127.0.0.1:8080):**
    ```bash
    # Ensure TRANSPORT=sse is set in your .env and the server is running (e.g., via 'uv run server.py')
    # List all projects
    mcp client call --uri http://127.0.0.1:8080/mcp todoist.get_projects

    # Add a new task
    mcp client call --uri http://127.0.0.1:8080/mcp todoist.add_task --content "Buy groceries" --due_string "tomorrow"
    ```

### Using with Claude Desktop

Claude Desktop's custom tools feature allows you to integrate local MCP servers like this one.

1.  **Ensure Prerequisites are Met:**
    *   You have installed the server following one of the methods above.
    *   Your `TODOIST_API_TOKEN` is accessible to the server (either via `.env` or directly in the Claude Desktop tool configuration as shown below).

2.  **Configure Custom Tool in Claude Desktop:**
    *   Open Claude Desktop and navigate to the custom tools configuration.
    *   Add a new tool, using a configuration structure similar to the example below.
    *   **Important:** You **must** adjust the paths in the `command` and `args` (specifically the `--directory` path) to match your local setup. Also, the `command` itself (e.g., `/opt/anaconda3/envs/mcp-py312/bin/uv`) should point to your specific `uv` executable or the Python executable from your chosen virtual environment if you are not using `uv` as the direct command.

    **Example JSON Configuration for Claude Desktop:**
    ```json
    {
        "mcpServers": {
            "todoist": {
                "command": "/opt/anaconda3/envs/mcp-py312/bin/uv", // <-- REPLACE with absolute path to your 'uv' or python executable
                "args": [
                    "--directory",
                    "/Users/kojiwong/Developer/todoist-mcp-server", // <-- REPLACE with absolute path to your project directory
                    "run",
                    "server.py"
                ],
                "env": {
                    "TODOIST_API_TOKEN": "<YOUR_TODOIST_API_TOKEN>", // <-- REPLACE with your actual API token
                    "PYTHONUNBUFFERED": "1",
                    "TRANSPORT": "stdio"
                }
            }
        }
    }
    ```

    **Notes on the configuration:**
    *   **`command`**: This should be the absolute path to the executable that starts the server.
        *   If using `uv` as in the example, it's the path to your `uv` binary.
        *   If using a Python virtual environment (venv) directly, it would be the absolute path to the `python` (or `python.exe`) executable inside your `.venv/bin` (or `.venv/Scripts`) folder, and the `args` would change to `["/absolute/path/to/your/todoist-mcp-server/server.py"]`.
    *   **`args`**:
        *   The `--directory` argument tells `uv` where the project is located. **Replace this path.**
        *   `run server.py` are arguments for `uv`.
    *   **`env`**:
        *   `TODOIST_API_TOKEN`: **Crucial.** Replace `<YOUR_TODOIST_API_TOKEN>` with your actual token.
        *   `PYTHONUNBUFFERED=1`: Recommended for `stdio` tools to ensure smooth communication.
        *   `TRANSPORT="stdio"`: Explicitly sets the transport mode for Claude Desktop.
    *   **Tool Name/Namespace:** Claude Desktop will discover tools under the `todoist` namespace (e.g., `todoist.add_task`).

3.  **Using the Tools in Claude:**
    Once configured, you should be able to invoke the Todoist tools from your Claude conversations. For example:
    `"Claude, can you add a task to my Todoist to 'Review project proposal' for tomorrow?"`
    Claude should then identify the need to use the `todoist.add_task` tool.

## Configuration (via .env file)

If not configuring environment variables directly in the MCP client (like the Claude Desktop example), the server can be configured using a `.env` file in the project root:

-   `TODOIST_API_TOKEN` (Required): Your API token for accessing Todoist.
-   `TRANSPORT` (Optional): Specifies the communication transport.
    -   `stdio` (default): Uses standard input/output.
    -   `sse`: Uses Server-Sent Events over HTTP.
-   `MCP_HOST` (Optional, for SSE): The host address for the SSE server to bind to. Defaults to `127.0.0.1`.
-   `MCP_PORT` (Optional, for SSE): The port for the SSE server to listen on. Defaults to `8080`.

## Available MCP Tools

The server exposes the following tools under the `todoist` namespace:

### Tasks
*   `add_task`: Create a new task.
*   `get_task`: Get a specific task by its ID.
*   `get_tasks`: Get active tasks, optionally filtered.
*   `filter_tasks`: Get active tasks matching a filter query.
*   `add_task_quick`: Create a new task using Todoist's Quick Add syntax.
*   `update_task`: Update an existing task.
*   `complete_task`: Complete a task (maps to `close_task`).
*   `uncomplete_task`: Uncomplete a task (maps to `reopen_task`).
*   `move_task`: Move a task to a different project or section (via `update_task`).
*   `delete_task`: Delete a task.
*   `get_completed_tasks_by_due_date`: Get completed tasks within a due date range.
*   `get_completed_tasks_by_completion_date`: Get completed tasks within a completion date range.

### Projects
*   `add_project`: Create a new project.
*   `get_project`: Get a project by its ID.
*   `get_projects`: Get all active projects.
*   `update_project`: Update an existing project.
*   `archive_project`: Archive a project.
*   `unarchive_project`: Unarchive a project.
*   `delete_project`: Delete a project.
*   `get_collaborators`: Get collaborators in a shared project.

### Sections
*   `add_section`: Create a new section within a project.
*   `get_section`: Get a specific section by its ID.
*   `get_sections`: Get all active sections, optionally filtered by project.
*   `update_section`: Update an existing section's name.
*   `delete_section`: Delete a section.

### Labels
*   `add_label`: Create a new personal label.
*   `get_label`: Get a specific personal label by its ID.
*   `get_labels`: Get all personal labels.
*   `update_label`: Update a personal label.
*   `delete_label`: Delete a personal label.
*   `get_shared_labels`: Get shared labels.
*   `rename_shared_label`: Rename a shared label (finds by name, updates by ID).
*   `remove_shared_label`: Remove a shared label (finds by name, deletes by ID).

### Comments
*   `add_comment`: Create a new comment on a task or project.
*   `get_comment`: Get a specific comment by its ID.
*   `get_comments`: Get comments for a task or project.
*   `update_comment`: Update an existing comment's content.
*   `delete_comment`: Delete a comment.

Refer to the `server.py` file for detailed parameters of each tool.

## Project Structure

-   `server.py`: Contains the main application logic, MCP tool definitions, and server execution.
-   `utils.py`: Utility functions, primarily for initializing the Todoist API client.
-   `main.py`: A minimal entry point (currently `server.py` is the primary executable script).
-   `pyproject.toml`: Defines project metadata, dependencies, and build system configuration.
-   `uv.lock`: Lock file for `uv` package manager, ensuring reproducible builds.
-   `.gitignore`: Specifies files and directories to be ignored by Git.
-   `.python-version`: Specifies the Python version (used by tools like `pyenv`).
-   `README.md`: This file.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for bugs, feature requests, or improvements.

1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

## License

Distributed under the MIT License. See `LICENSE` for more information. (Note: Add a `LICENSE` file if one does not exist, e.g., with MIT License text).
