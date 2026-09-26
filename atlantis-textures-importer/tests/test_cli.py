import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import testkit
from importer.app import AppLayout, verify
from importer.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = testkit.make_app(self.root)
        self.build = testkit.make_build(self.root / "build")
        self.ai = testkit.write_ai(self.root / "ai", testkit.make_rooms())
        self.stock = testkit.snapshot(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, command, runner):
        argv = [command, "--ai", str(self.ai), "--app", str(self.app), "--build", str(self.build)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(argv, runner=runner, load_rooms=lambda game_dir: testkit.make_rooms())

    def test_install_stages_and_installs_and_leaves_no_temp_folder(self):
        self.assertEqual(self.cli("install", testkit.Runner()), 0)
        self.assertEqual(verify(AppLayout(self.app)), [])
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".atlantis-hd-")], [])

    def test_a_validation_problem_stops_install_before_the_app_is_touched(self):
        (self.ai / "room_002.png").unlink()
        runner = testkit.Runner()
        self.assertEqual(self.cli("install", runner), 1)
        self.assertEqual(testkit.snapshot(self.app), self.stock)
        self.assertEqual(runner.programs(), ["pgrep"])
