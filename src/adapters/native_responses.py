"""Responses transport without portable history or tool-schema conversion."""
import copy

from adapters.request_compat import inline_history, stream_error_event


class NativeResponsesAdapter:
    def __init__(self, *, history_migration=False):
        self.history_migration = history_migration

    def request(self, original):
        # Migration is explicit: provider-local item IDs cannot be assumed portable.
        return inline_history(original) if self.history_migration else copy.deepcopy(original)

    def stream_events(self, original):
        failure = stream_error_event(original)
        if failure is not None:
            return [failure]
        if 'choices' in original:
            raise ValueError('UPSTREAM_PROTOCOL_MISMATCH')
        # Keep native tool names, namespaces, argument deltas and completion items.
        return [copy.deepcopy(original)]
