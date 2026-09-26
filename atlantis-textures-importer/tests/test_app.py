import itertools
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import testkit
from importer.app import AppLayout, InstallError, install, preflight, uninstall, verify
from importer.stage import stage


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = testkit.make_app(self.root)
        self.layout = AppLayout(self.app)
        self.build = testkit.make_build(self.root / "build")
        self.stock = testkit.snapshot(self.app)
        self.rooms = testkit.make_rooms()
        self.ai = testkit.write_ai(self.root / "ai", self.rooms)
        self.counter = itertools.count()

    def tearDown(self):
        self.tmp.cleanup()

    def staged(self) -> Path:
        hd = self.root / f"staged-{next(self.counter)}" / "hd"
        stage(self.rooms, self.ai, hd, "test")
        return hd

    def install(self, runner=None):
        install(self.layout, self.build, self.staged(), runner or testkit.Runner(), log=lambda m: None)

    def uninstall(self, runner=None):
        uninstall(self.layout, runner or testkit.Runner(), log=lambda m: None)

    def test_install_then_uninstall_restores_the_stock_app(self):
        runner = testkit.Runner()
        self.install(runner)
        self.assertEqual(self.layout.binary.read_bytes(), (self.build / "Contents/MacOS/scummvm").read_bytes())
        self.assertEqual((self.layout.backup / "Contents/MacOS/scummvm").read_bytes(), testkit.STOCK_BINARY)
        self.assertTrue((self.layout.hd / "manifest.json").is_file())
        self.assertEqual(runner.programs(), ["xattr"])  # never re-signs: GOG's signature stays as it was

        self.layout.config.write_text("[scummvm]\nversioninfo=2026.3.0\n")  # ScummVM rewrites it on exit
        runner = testkit.Runner()
        self.uninstall(runner)
        self.assertEqual(testkit.snapshot(self.app), self.stock)
        self.assertEqual(runner.programs(), ["pgrep"])

    def test_reinstall_keeps_the_original_backup(self):
        self.install()
        self.install()
        self.assertEqual((self.layout.backup / "Contents/MacOS/scummvm").read_bytes(), testkit.STOCK_BINARY)
        self.assertEqual(self.layout.binary.read_bytes(), (self.build / "Contents/MacOS/scummvm").read_bytes())

    def test_install_after_an_interrupted_one(self):
        self.layout.engine.rename(self.layout.backup)  # a crash right after the backup
        self.install()
        self.assertEqual((self.layout.backup / "Contents/MacOS/scummvm").read_bytes(), testkit.STOCK_BINARY)
        self.assertEqual(verify(self.layout), [])

    def test_install_adds_the_engine_id_once(self):
        # ScummVM 2026 cannot upgrade GOG's 1.7-era [atlantis] target without it.
        self.install()
        self.install()
        self.assertEqual(self.layout.config.read_text(),
                         "[scummvm]\nversioninfo=1.7.0\n\n[atlantis]\nengineid=scumm\ngameid=atlantis\n")

    def test_a_configfile_without_the_target_rolls_back(self):
        self.layout.config.write_text("[scummvm]\nversioninfo=1.7.0\n")
        stock = testkit.snapshot(self.app)
        with self.assertRaisesRegex(InstallError, r"no \[atlantis\] target"):
            self.install()
        self.assertEqual(testkit.snapshot(self.app), stock)

    def test_a_failed_copy_rolls_back_to_stock(self):
        self.build = self.root / "missing.app"
        with self.assertRaisesRegex(InstallError, "rolled back"):
            self.install()
        self.assertEqual(testkit.snapshot(self.app), self.stock)

    def test_uninstall_refuses_while_running(self):
        self.install()
        installed = testkit.snapshot(self.app)
        with self.assertRaisesRegex(InstallError, "running"):
            self.uninstall(testkit.Runner(running=True))
        self.assertEqual(testkit.snapshot(self.app), installed)

    def test_uninstall_of_a_stock_app_changes_nothing(self):
        runner = testkit.Runner()
        self.uninstall(runner)
        self.assertEqual(testkit.snapshot(self.app), self.stock)
        self.assertEqual(runner.programs(), ["pgrep"])

    def test_preflight(self):
        no_game = self.root / "empty.app"
        cases = [
            ("ready", self.layout, self.build, testkit.Runner(), []),
            ("running", self.layout, self.build, testkit.Runner(running=True),
             ["the game is running; quit it first"]),
            ("not built", self.layout, self.root / "nowhere.app", testkit.Runner(),
             [f"{self.root / 'nowhere.app'}: no built ScummVM; run make build"]),
            ("not the game", AppLayout(no_game), None, None,
             [f"{no_game}: not the GOG Fate of Atlantis app (no ATLANTIS.001)"]),
        ]
        for name, layout, build, runner, expected in cases:
            with self.subTest(name):
                self.assertEqual(preflight(layout, build, runner), expected)

    def test_verify(self):
        self.assertEqual(verify(self.layout), [f"{self.layout.hd / 'manifest.json'}: missing; HD backgrounds are not installed"])
        self.install()
        self.assertEqual(verify(self.layout), [])

        (self.layout.hd / "room_001.png").write_bytes(b"edited")
        self.layout.binary.write_bytes(testkit.ARM64_HEADER + b"stock")
        self.assertEqual(verify(self.layout), [
            "room_001.png: changed since install",
            f"{self.layout.binary}: not the patched engine",
        ])
