import unittest
from unittest.mock import Mock

import tray.tray_icon as tray_icon


class TrayThreadingTests(unittest.TestCase):

    def tearDown(self):
        tray_icon.configure_tray_callbacks()

    def test_open_gui_uses_callback_instead_of_creating_tk_thread(self):
        open_callback = Mock()
        tray_icon.configure_tray_callbacks(on_open_gui=open_callback)

        tray_icon.open_gui(None, None)

        open_callback.assert_called_once_with()

    def test_run_backup_uses_callback_instead_of_opening_login_from_tray_thread(self):
        backup_callback = Mock()
        tray_icon.configure_tray_callbacks(on_run_backup=backup_callback)

        tray_icon.run_backup(None, None)

        backup_callback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
