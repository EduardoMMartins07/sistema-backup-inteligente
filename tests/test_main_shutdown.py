import threading
import unittest
from unittest.mock import Mock

import main
from scanner.scanner import set_shutdown_event
from scanner.scanner import wait_for_shutdown


class MainShutdownTests(unittest.TestCase):

    def tearDown(self):
        set_shutdown_event(main.SHUTDOWN_EVENT)

    def test_wait_for_background_threads_joins_alive_threads(self):
        alive_thread = Mock(spec=threading.Thread)
        alive_thread.is_alive.return_value = True

        finished_thread = Mock(spec=threading.Thread)
        finished_thread.is_alive.return_value = False

        main.wait_for_background_threads(
            [alive_thread, finished_thread],
            join_timeout=0.25
        )

        alive_thread.join.assert_called_once_with(timeout=0.25)
        finished_thread.join.assert_not_called()

    def test_wait_for_shutdown_returns_immediately_when_event_is_set(self):
        event = threading.Event()
        event.set()
        set_shutdown_event(event)

        self.assertTrue(wait_for_shutdown(10))


if __name__ == "__main__":
    unittest.main()
