import unittest
from unittest.mock import Mock, patch

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

    def test_viewer_cannot_exit_from_tray_menu(self):
        self.assertFalse(tray_icon.is_exit_enabled({"role": "viewer"}))

    def test_operator_can_exit_from_tray_menu(self):
        self.assertTrue(tray_icon.is_exit_enabled({"role": "operator"}))

    def test_admin_can_exit_from_tray_menu(self):
        self.assertTrue(tray_icon.is_exit_enabled({"role": "admin"}))

    def test_api_admin_can_exit_from_tray_menu(self):
        self.assertTrue(tray_icon.is_exit_enabled({"role": "ADMIN_EMPRESA"}))

    def test_api_operator_can_exit_from_tray_menu(self):
        self.assertTrue(tray_icon.is_exit_enabled({"role": "OPERADOR"}))

    def test_missing_user_cannot_exit_from_tray_menu(self):
        with patch("tray.tray_icon.get_current_user", return_value=None):
            self.assertFalse(tray_icon.is_exit_enabled())

    def test_menu_disables_exit_for_viewer(self):
        created_items = []

        def fake_item(*args, **kwargs):
            created_items.append((args, kwargs))
            return (args, kwargs)

        with (
            patch("tray.tray_icon.item", side_effect=fake_item),
            patch("tray.tray_icon.pystray.Menu", side_effect=lambda *items: items),
            patch("tray.tray_icon.get_current_user", return_value={"role": "viewer"}),
            patch("tray.tray_icon.get_latest_backup_timestamp", return_value="Nenhum backup"),
            patch("tray.tray_icon.get_backup_destination", return_value="backups"),
        ):
            tray_icon.build_menu()
            exit_items = [
                (args, kwargs)
                for args, kwargs in created_items
                if args and args[0] == "Sair"
            ]
            self.assertEqual(1, len(exit_items))
            enabled = exit_items[0][1]["enabled"]
            self.assertTrue(callable(enabled))
            self.assertFalse(enabled())

    def test_menu_enables_exit_for_operator(self):
        created_items = []

        def fake_item(*args, **kwargs):
            created_items.append((args, kwargs))
            return (args, kwargs)

        with (
            patch("tray.tray_icon.item", side_effect=fake_item),
            patch("tray.tray_icon.pystray.Menu", side_effect=lambda *items: items),
            patch("tray.tray_icon.get_current_user", return_value={"role": "operator"}),
            patch("tray.tray_icon.get_latest_backup_timestamp", return_value="Nenhum backup"),
            patch("tray.tray_icon.get_backup_destination", return_value="backups"),
        ):
            tray_icon.build_menu()
            exit_items = [
                (args, kwargs)
                for args, kwargs in created_items
                if args and args[0] == "Sair"
            ]
            self.assertEqual(1, len(exit_items))
            enabled = exit_items[0][1]["enabled"]
            self.assertTrue(callable(enabled))
            self.assertTrue(enabled())

    def test_menu_enables_exit_for_admin(self):
        created_items = []

        def fake_item(*args, **kwargs):
            created_items.append((args, kwargs))
            return (args, kwargs)

        with (
            patch("tray.tray_icon.item", side_effect=fake_item),
            patch("tray.tray_icon.pystray.Menu", side_effect=lambda *items: items),
            patch("tray.tray_icon.get_current_user", return_value={"role": "admin"}),
            patch("tray.tray_icon.get_latest_backup_timestamp", return_value="Nenhum backup"),
            patch("tray.tray_icon.get_backup_destination", return_value="backups"),
        ):
            tray_icon.build_menu()
            exit_items = [
                (args, kwargs)
                for args, kwargs in created_items
                if args and args[0] == "Sair"
            ]
            self.assertEqual(1, len(exit_items))
            enabled = exit_items[0][1]["enabled"]
            self.assertTrue(callable(enabled))
            self.assertTrue(enabled())

    def test_exit_app_continues_to_use_exit_callback(self):
        exit_callback = Mock()
        tray_icon.configure_tray_callbacks(on_exit=exit_callback)

        tray_icon.exit_app(None, None)

        exit_callback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
