from consurg.adapters.aider import generate_aider_args
from consurg.adapters.claude import generate_claude_scope
from consurg.adapters.cursor import generate_cursor_rules
from consurg.adapters.generic import generate_generic_prompt

__all__ = [
    "generate_claude_scope",
    "generate_cursor_rules",
    "generate_aider_args",
    "generate_generic_prompt",
]
