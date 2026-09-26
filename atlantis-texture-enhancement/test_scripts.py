import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent


def dry_make(*args):
    """The ./run_* command lines `make -n` would run, whitespace collapsed."""
    out = subprocess.run(["make", "-n", "-s", *args], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    return [" ".join(line.split()) for line in out.splitlines() if line.startswith("./run_")]


class MakeTests(unittest.TestCase):
    def test_targets_forward_their_arguments(self):
        cases = {
            ("caption", "room=1 58", "force=1"): "./run_batch.sh caption --room 1 --room 58 --force",
            ("dry-run", "workflow=qwen-image-2.1-i2i", "strength=0.5"):
                "./run_batch.sh batch --dry-run --match-strength 0.5 --workflow qwen-image-2.1-i2i",
            ("batch", "room=58", "memcheck=0", "force=1", "dst=data/spike"):
                './run_batch.sh batch --room 58 --dst "data/spike" --no-memory-check --force',
            ("review", "force=1"): "./run_batch.sh review --force",
            ("verify", "src=/x"): './run_batch.sh verify --src "/x"',
            ("server",): "./run_server.sh",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                self.assertEqual(dry_make(*args), [expected])


if __name__ == "__main__":
    unittest.main()
