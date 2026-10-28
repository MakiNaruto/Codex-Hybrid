"""Startup failures expose fixed categories across platforms, never messages."""
import errno
import unittest

from management.forwarding_worker import failure


class WorkerFailureTests(unittest.TestCase):
    def test_native_port_and_permission_errors_have_actionable_categories(self):
        for code in (errno.EADDRINUSE, 10048):
            self.assertEqual(failure(OSError(code, 'private-path')), {'reason': 'port_in_use'})
        for code in (errno.EACCES, errno.EPERM, 10013):
            self.assertEqual(failure(OSError(code, 'private-path')), {'reason': 'permission_denied'})

    def test_configuration_and_unknown_errors_do_not_expose_messages(self):
        self.assertEqual(failure(ValueError('api_key=secret')), {'reason': 'invalid_configuration'})
        self.assertEqual(failure(RuntimeError('api_key=secret')), {'reason': 'worker_error'})
