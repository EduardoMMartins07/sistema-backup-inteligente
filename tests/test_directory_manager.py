import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from interface.gui import BackupGUI


class DirectoryManagerTests(unittest.TestCase):

    def test_saving_new_directories_only_shows_saved_alert(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = root / "original"
            added = root / "added"
            original.mkdir()
            added.mkdir()

            gui = BackupGUI.__new__(BackupGUI)
            gui.directories = [str(original), str(added)]
            gui.backup_in_progress = False
            gui.save_directories = Mock()
            gui.start_backup_execution = Mock()
            parent = object()
            original_directories = {
                os.path.normcase(os.path.abspath(str(original)))
            }

            with patch("interface.gui.messagebox.showinfo") as showinfo:
                gui.save_directory_manager_changes(
                    original_directories,
                    parent=parent
                )

        gui.save_directories.assert_called_once_with()
        gui.start_backup_execution.assert_not_called()
        showinfo.assert_called_once_with("Salvo", "Salvo", parent=parent)


if __name__ == "__main__":
    unittest.main()
