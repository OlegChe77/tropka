import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from most import config


class DataDirTest(unittest.TestCase):
    def test_moves_old_data(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            (Path(tmp) / "Most").mkdir()
            (Path(tmp) / "Most" / "most.db").write_text("x")
            path = config.data_dir()
            self.assertEqual(path, Path(tmp) / "Tropka")
            self.assertEqual((path / "most.db").read_text(), "x")
            self.assertFalse((Path(tmp) / "Most").exists())

    def test_keeps_existing_new_dir(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            (Path(tmp) / "Most").mkdir()
            (Path(tmp) / "Tropka").mkdir()
            config.data_dir()
            self.assertTrue((Path(tmp) / "Most").exists())


if __name__ == "__main__":
    unittest.main()
