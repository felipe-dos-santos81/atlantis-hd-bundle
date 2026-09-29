import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CD = "cd atlantis-texture-enhancement && "


def dry_make(*args):
    """The ./run_* command lines `make -n` would run, whitespace collapsed."""
    out = subprocess.run(["make", "-n", "-s", *args], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return [" ".join(line.split()) for line in out.splitlines() if line.startswith(CD + "./run_")]


class MakeTests(unittest.TestCase):
    def test_targets_forward_their_arguments(self):
        cases = {
            ("enhancer-caption", "room=1 58", "force=1"):
                CD + "./run_batch.sh caption --room 1 --room 58 --force",
            ("enhancer-dry-run", "workflow=qwen-image-2.1-i2i", "strength=0.5"):
                CD + "./run_batch.sh batch --dry-run --match-strength 0.5 --workflow qwen-image-2.1-i2i",
            ("enhancer-batch", "room=58", "memcheck=0", "force=1", "dst=data/spike"):
                CD + './run_batch.sh batch --room 58 --dst "data/spike" --no-memory-check --force',
            ("enhancer-review", "force=1"): CD + "./run_batch.sh review --force",
            ("enhancer-verify", "src=/x"): CD + './run_batch.sh verify --src "/x"',
            ("enhancer-server",): CD + "./run_server.sh",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                self.assertEqual(dry_make(*args), [expected])


if __name__ == "__main__":
    unittest.main()
