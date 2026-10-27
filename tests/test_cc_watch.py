from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from management.cc_watch import CCWatch


class CCWatchTests(unittest.TestCase):
    def test_filters_read_events_and_unrelated_files_and_debounces_wal(self):
        watch = CCWatch(Path('cc.db'))

        def event(path, kind='modified', dest=''):
            watch.on_event(SimpleNamespace(is_directory=False, event_type=kind,
                                           src_path=str(path), dest_path=str(dest)))

        with patch('management.cc_watch.time.monotonic', return_value=10) as now:
            event(watch.path, 'opened')
            event(str(watch.path) + '-shm')
            event(watch.path.parent / 'other.db')
            self.assertFalse(watch.ready())
            event(watch.path)
            now.return_value = 10.2
            event(str(watch.path) + '-wal')
            now.return_value = 10.4
            self.assertFalse(watch.ready())
            now.return_value = 10.6
            self.assertTrue(watch.ready())
            self.assertFalse(watch.ready())
            event(watch.path.parent / 'replacement.tmp', 'moved', watch.path)
            now.return_value = 11
            self.assertTrue(watch.ready())
