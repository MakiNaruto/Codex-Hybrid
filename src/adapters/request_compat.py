"""Compatibility exports for history, routing context and stream error helpers."""
from adapters.history import inline_history, native_plaintext_marker, normalize_history
from adapters.context import (
    PARENT_GUIDANCE, WORKER_GUIDANCE, agent_message_kinds, collaboration_namespaces,
    context_position, delegated_task, external_context, progress_guidance,
)
from adapters.stream_errors import stream_error_event, upstream_error

__all__ = [
    "inline_history", "native_plaintext_marker", "normalize_history",
    "PARENT_GUIDANCE", "WORKER_GUIDANCE", "agent_message_kinds",
    "collaboration_namespaces", "context_position", "delegated_task",
    "external_context", "progress_guidance", "stream_error_event", "upstream_error",
]
