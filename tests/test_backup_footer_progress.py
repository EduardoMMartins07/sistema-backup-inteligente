import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from interface.gui import BackupGUI


class FakeWidget:

    def __init__(self):
        self.visible = False
        self.options = {}

    def grid(self, *args, **kwargs):
        self.visible = True

    def pack(self, *args, **kwargs):
        self.visible = True

    def grid_remove(self):
        self.visible = False

    def config(self, **kwargs):
        self.options.update(kwargs)

    configure = config

    def winfo_exists(self):
        return True

    def update_idletasks(self):
        pass


class FakeProgressbar(FakeWidget):

    def __init__(self):
        super().__init__()
        self.values = {}

    def __setitem__(self, key, value):
        self.values[key] = value

    def __getitem__(self, key):
        return self.values.get(key, 0)


class BackupFooterProgressTests(unittest.TestCase):

    def build_gui(self):
        gui = BackupGUI.__new__(BackupGUI)
        gui.root = Mock()
        gui.root.after = Mock()
        gui.backup_progress_frame = FakeWidget()
        gui.backup_progress_status = FakeWidget()
        gui.backup_progress_bar = FakeProgressbar()
        gui.backup_progress_cancel_button = FakeWidget()
        gui.progress_window = None
        gui.progress_label = None
        gui.progress_bar = None
        gui.cancel_button = None
        gui.cancel_backup_requested = threading.Event()
        gui.backup_in_progress = True
        gui.pending_backup_directories = ["C:/dados"]
        gui.pending_backup_trigger = "manual"
        gui.pending_backup_name = ""
        gui.pending_backup_description = ""
        gui.current_user = {
            "username": "dudu",
            "role": "operator",
            "company_id": "default",
        }
        gui.prepare_window = Mock()
        gui.center_window = Mock()
        gui.apply_button_feedback = Mock()
        gui.set_backup_button_state = Mock()
        gui.refresh_footer = Mock()
        gui.refresh_dashboard_if_home = Mock()
        return gui

    def patch_modal_widgets(self):
        fake_modal_widget = FakeWidget()
        fake_modal_widget.pack = Mock()
        return (
            patch("interface.gui.tk.Toplevel", return_value=Mock()),
            patch("interface.gui.tk.Label", return_value=fake_modal_widget),
            patch("interface.gui.ttk.Progressbar", return_value=FakeProgressbar()),
            patch("interface.gui.tk.Button", return_value=fake_modal_widget),
        )

    def test_open_progress_uses_footer_without_modal_window(self):
        gui = self.build_gui()

        toplevel_patch, label_patch, progress_patch, button_patch = self.patch_modal_widgets()
        with toplevel_patch as toplevel:
            with label_patch, progress_patch, button_patch:
                gui.open_progress_window()

        toplevel.assert_not_called()
        self.assertTrue(gui.backup_progress_frame.visible)
        self.assertIs(gui.progress_label, gui.backup_progress_status)
        self.assertIs(gui.progress_bar, gui.backup_progress_bar)
        self.assertEqual(0, gui.backup_progress_bar["value"])

    def test_progress_updates_footer_widgets(self):
        gui = self.build_gui()
        toplevel_patch, label_patch, progress_patch, button_patch = self.patch_modal_widgets()
        with toplevel_patch, label_patch, progress_patch, button_patch:
            gui.open_progress_window()

        gui.update_progress_window(42, "Processando objetos: 4/10")

        self.assertEqual(42, gui.backup_progress_bar["value"])
        self.assertEqual(
            "Processando objetos: 4/10",
            gui.backup_progress_status.options["text"],
        )

    def test_finish_success_keeps_feedback_in_footer_without_popup(self):
        gui = self.build_gui()
        result = {
            "storage_mode": "incremental",
            "snapshot_path": "snapshot.json",
            "backup_storage": "backups/dudu",
            "total_files": 10,
            "objects_stored": 2,
            "objects_referenced": 1,
            "files_unchanged": 7,
            "warnings": [],
        }

        toplevel_patch, label_patch, progress_patch, button_patch = self.patch_modal_widgets()
        with toplevel_patch, label_patch, progress_patch, button_patch:
            gui.open_progress_window()

        with patch("interface.gui.messagebox.showinfo") as showinfo:
            gui.finish_backup_success(result)

        showinfo.assert_not_called()
        self.assertFalse(gui.backup_in_progress)
        self.assertTrue(gui.backup_progress_frame.visible)
        self.assertEqual(100, gui.backup_progress_bar["value"])
        self.assertIn(
            "Backup incremental concluido",
            gui.backup_progress_status.options["text"],
        )

    def test_finish_success_monitors_aws_upload_progress(self):
        gui = self.build_gui()
        result = {
            "storage_mode": "incremental",
            "snapshot_path": "snapshot.json",
            "backup_storage": "backups/dudu",
            "total_files": 10,
            "objects_stored": 2,
            "objects_referenced": 1,
            "files_unchanged": 7,
            "cloud_sync_status": "sincronizando",
            "warnings": [],
        }

        with patch.object(gui, "start_cloud_sync_footer_monitor") as monitor:
            gui.finish_backup_success(result)

        monitor.assert_called_once_with("snapshot.json")

    def test_cloud_sync_poll_updates_footer_progress(self):
        gui = self.build_gui()
        gui.backup_in_progress = False

        with patch(
            "interface.gui.get_cloud_sync_progress",
            return_value={
                "status": "sincronizando",
                "processed": 3,
                "total": 10,
                "message": "Enviando para AWS S3: 3/10",
            },
        ):
            gui.start_cloud_sync_footer_monitor("snapshot.json")
            gui.poll_cloud_sync_footer()

        self.assertTrue(gui.backup_progress_frame.visible)
        self.assertEqual(30, gui.backup_progress_bar["value"])
        self.assertEqual(
            "Enviando para AWS S3: 3/10",
            gui.backup_progress_status.options["text"],
        )
        self.assertEqual(
            "AWS",
            gui.backup_progress_cancel_button.options["text"],
        )

    def test_cloud_sync_monitor_without_snapshot_latches_active_upload(self):
        gui = self.build_gui()
        gui.backup_in_progress = False

        with patch(
            "interface.gui.get_cloud_sync_progress",
            side_effect=[
                {
                    "snapshot_path": "snapshot.json",
                    "status": "sincronizando",
                    "processed": 1,
                    "total": 2,
                    "percent": 50,
                    "message": "Enviando para AWS S3: 1/2",
                },
                {
                    "snapshot_path": "snapshot.json",
                    "status": "sincronizado",
                    "processed": 2,
                    "total": 2,
                    "percent": 100,
                    "message": "Envio para AWS S3 concluido.",
                },
            ],
        ):
            gui.start_cloud_sync_footer_monitor()
            self.assertEqual("snapshot.json", gui.active_cloud_sync_snapshot_path)
            gui.poll_cloud_sync_footer()

        self.assertIsNone(gui.active_cloud_sync_snapshot_path)
        self.assertEqual(100, gui.backup_progress_bar["value"])
        self.assertIn(
            "concluido",
            gui.backup_progress_status.options["text"],
        )

    def test_error_feedback_uses_footer_and_history_without_popup(self):
        gui = self.build_gui()

        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "backup_history.json"
            history_path.write_text("[]", encoding="utf-8")

            with patch("interface.gui.HISTORY_PATH", str(history_path)):
                with patch("interface.gui.messagebox.showerror") as showerror:
                    gui.finish_backup_error("disco cheio")

            history = json.loads(history_path.read_text(encoding="utf-8"))

        showerror.assert_not_called()
        self.assertFalse(gui.backup_in_progress)
        self.assertTrue(gui.backup_progress_frame.visible)
        self.assertIn("Backup falhou", gui.backup_progress_status.options["text"])
        self.assertEqual("failed", history[-1]["status"])
        self.assertIn("disco cheio", history[-1]["backup_description"])

    def test_cancel_feedback_uses_footer_and_history_without_popup(self):
        gui = self.build_gui()

        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "backup_history.json"
            history_path.write_text("[]", encoding="utf-8")

            with patch("interface.gui.HISTORY_PATH", str(history_path)):
                with patch("interface.gui.messagebox.showinfo") as showinfo:
                    gui.finish_backup_cancelled("Backup cancelado pelo usuario.")

            history = json.loads(history_path.read_text(encoding="utf-8"))

        showinfo.assert_not_called()
        self.assertFalse(gui.backup_in_progress)
        self.assertTrue(gui.backup_progress_frame.visible)
        self.assertIn("Backup cancelado", gui.backup_progress_status.options["text"])
        self.assertEqual("cancelled", history[-1]["status"])
        self.assertIn("Backup cancelado", history[-1]["backup_description"])


if __name__ == "__main__":
    unittest.main()
