import queue
import threading
import unittest
from unittest.mock import Mock, patch

import interface.gui as gui_module
from interface.gui import BackupGUI


class FakeRoot:

    def __init__(self, run_after_immediately=False):
        self.run_after_immediately = run_after_immediately
        self.after_calls = []
        self.withdraw_called = False
        self.quit_called = False
        self.deiconify_called = False
        self.lift_called = False
        self.focus_force_called = False

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

        if self.run_after_immediately:
            callback()

    def withdraw(self):
        self.withdraw_called = True

    def quit(self):
        self.quit_called = True

    def deiconify(self):
        self.deiconify_called = True

    def lift(self):
        self.lift_called = True

    def focus_force(self):
        self.focus_force_called = True

    def winfo_exists(self):
        return True


class GuiBackupLifecycleTests(unittest.TestCase):

    def make_gui(self, root=None):
        gui = object.__new__(BackupGUI)
        gui.root = root or FakeRoot()
        gui.current_user = {"username": "admin", "role": "admin"}
        gui.directories = ["C:/origem"]
        gui.backup_in_progress = False
        gui.backup_thread = None
        gui.backup_queue = queue.Queue()
        gui.progress_window = None
        gui.progress_label = None
        gui.progress_bar = None
        gui.cancel_button = None
        gui.pending_backup_notification = None
        gui.pending_backup_refresh = False
        gui.pending_backup_name = ""
        gui.pending_backup_description = ""
        gui.pending_backup_directories = None
        gui.pending_backup_trigger = "manual"
        gui.cancel_backup_requested = threading.Event()
        gui.backup_button = None
        gui.is_closing = False
        gui.logout_requested = False

        gui.open_progress_window = Mock()
        gui.close_progress_window = Mock()
        gui.set_backup_button_state = Mock()
        gui.refresh_footer = Mock()
        gui.refresh_dashboard_if_home = Mock()
        gui.schedule_dashboard_event_poll = Mock()
        gui.update_progress_window = Mock()
        gui.run_backup_in_background = Mock()
        return gui

    def test_backup_execution_starts_non_daemon_worker(self):
        gui = self.make_gui()
        worker = Mock()

        with patch("interface.gui.threading.Thread", return_value=worker) as thread_cls:
            gui.start_backup_execution(["C:/origem"], "manual")

        thread_cls.assert_called_once()
        self.assertFalse(thread_cls.call_args.kwargs["daemon"])
        self.assertIs(gui.backup_thread, worker)
        worker.start.assert_called_once_with()
        self.assertTrue(gui.backup_in_progress)

    def test_close_during_backup_keeps_window_open_without_cancelling(self):
        gui = self.make_gui()
        gui.backup_in_progress = True

        with patch("interface.gui.messagebox.showwarning") as showwarning:
            gui.request_close()

        showwarning.assert_called_once()
        self.assertFalse(gui.is_closing)
        self.assertFalse(gui.root.withdraw_called)
        self.assertFalse(gui.root.quit_called)
        self.assertFalse(gui.cancel_backup_requested.is_set())
        gui.close_progress_window.assert_not_called()

    def test_hidden_success_event_finishes_and_stores_notification(self):
        gui = self.make_gui()
        gui.is_closing = True
        gui.backup_in_progress = True
        gui.backup_queue.put((
            "success",
            {
                "storage_mode": "incremental",
                "snapshot_path": "C:/backup/snapshot.json",
                "backup_storage": "C:/backup",
                "total_files": 2,
                "objects_stored": 1,
                "objects_referenced": 1,
                "files_unchanged": 0,
                "warnings": [],
            },
        ))

        with patch("interface.gui.messagebox.showinfo") as showinfo:
            gui.process_backup_events(
                allow_when_closing=True,
                show_notifications=False,
                schedule_next=False
            )

        showinfo.assert_not_called()
        self.assertFalse(gui.backup_in_progress)
        self.assertIsNotNone(gui.pending_backup_notification)
        self.assertEqual("info", gui.pending_backup_notification[0])
        self.assertTrue(gui.pending_backup_refresh)
        gui.refresh_footer.assert_not_called()
        gui.refresh_dashboard_if_home.assert_not_called()

    def test_hidden_error_event_finishes_and_stores_notification(self):
        gui = self.make_gui()
        gui.is_closing = True
        gui.backup_in_progress = True
        gui.backup_queue.put(("error", "Falha no backup"))

        with patch("interface.gui.messagebox.showerror") as showerror:
            gui.process_backup_events(
                allow_when_closing=True,
                show_notifications=False,
                schedule_next=False
            )

        showerror.assert_not_called()
        self.assertFalse(gui.backup_in_progress)
        self.assertEqual(("error", "Erro", "Falha no backup"), gui.pending_backup_notification)

    def test_show_window_displays_pending_backup_notification(self):
        gui = self.make_gui(FakeRoot(run_after_immediately=True))
        gui.pending_backup_notification = ("error", "Erro", "Falha no backup")

        with patch("interface.gui.messagebox.showerror") as showerror:
            gui.show_window()

        self.assertTrue(gui.root.deiconify_called)
        self.assertTrue(gui.root.lift_called)
        self.assertTrue(gui.root.focus_force_called)
        self.assertIsNone(gui.pending_backup_notification)
        showerror.assert_called_once_with("Erro", "Falha no backup", parent=gui.root)

    def test_hidden_gui_pump_processes_backup_events(self):
        gui = self.make_gui()
        root = gui.root
        original_gui = gui_module._background_gui
        original_root = gui_module._background_root
        gui.process_backup_events = Mock()

        try:
            gui_module._background_gui = gui
            gui_module._background_root = root

            self.assertTrue(gui_module.process_hidden_gui_events())

            gui.process_backup_events.assert_called_once_with(
                allow_when_closing=True,
                show_notifications=False,
                schedule_next=False
            )
        finally:
            gui_module._background_gui = original_gui
            gui_module._background_root = original_root


if __name__ == "__main__":
    unittest.main()
