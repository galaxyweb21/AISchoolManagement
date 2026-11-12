# ai_engine/services/tools/base.py
"""
STEP 1 — AI Tool Registry: base contracts for secure tool execution.

Every tool that the AI copilot can call is described declaratively:
name, human description, the capability required to use it (checked
against the single source of truth in role_ai_policy.py), and the
parameters it accepts. The registry (tool_registry.py) is the only
thing that is allowed to actually run a tool — it enforces the
permission check, validates arguments against the schema, applies a
timeout, and writes an audit log entry, so no caller can accidentally
skip a security check by calling a tool's legacy `.run()` directly.
"""

import logging

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Base class for all tool-execution failures."""


class ToolPermissionDenied(ToolExecutionError):
    """Raised when the requesting user's role lacks the required capability."""


class ToolValidationError(ToolExecutionError):
    """Raised when required arguments are missing or the wrong type."""


class ToolTimeoutError(ToolExecutionError):
    """Raised when a tool exceeds its allotted execution time."""


class ToolParameter:
    """Declarative description of one argument a tool accepts."""

    def __init__(self, name, type=str, required=False, description="", default=None):
        self.name = name
        self.type = type
        self.required = required
        self.description = description
        self.default = default


class AITool:
    """
    Base class every registry-managed tool wraps.

    Subclasses (or thin adapters around the school's existing service
    classes) set the class attributes below and implement `run()`.
    Nothing outside ai_engine.services.tool_registry should instantiate
    or call a tool directly — always go through ToolRegistry.execute()
    so permission checks, validation, timeouts and audit logging apply.
    """

    name = "tool"
    description = ""
    # Capability string that must appear in the user's role_ai_policy
    # capability set (e.g. "students", "finance", "risk", "research").
    # None means "no capability gate beyond can_chat" — use sparingly.
    required_capability = None
    parameters = ()  # tuple[ToolParameter, ...]
    timeout_seconds = 20

    def validate(self, kwargs):
        for param in self.parameters:
            value = kwargs.get(param.name, param.default)
            if param.required and (value is None or value == ""):
                raise ToolValidationError(
                    f"Missing required parameter '{param.name}' for tool '{self.name}'"
                )
            if value is not None and param.type is not None and not isinstance(value, param.type):
                raise ToolValidationError(
                    f"Parameter '{param.name}' for tool '{self.name}' must be "
                    f"{param.type.__name__}, got {type(value).__name__}"
                )

    def run(self, *, school, user, question="", context=None, **kwargs):
        """Subclasses implement the actual tool logic here."""
        raise NotImplementedError
