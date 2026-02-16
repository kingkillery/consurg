"""Constants for tool names and their associated path fields."""

PATH_FIELDS = {
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "Grep": "path",
    "Glob": "path",
}

COMMAND_TOOLS = {"Bash"}
COMMAND_FIELD = "command"

READ_TOOLS = {"Read", "Grep", "Glob"}
WRITE_TOOLS = {"Edit", "Write"}
