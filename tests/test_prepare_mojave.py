import tempfile
import unittest
from pathlib import Path

from scripts.prepare_mojave import MOJAVE_CONFIG_LINES, prepare


class PrepareMojaveTest(unittest.TestCase):
    def create_source_tree(self, root: Path):
        codex_rs = root / "codex-rs"
        codex_rs.mkdir()
        (codex_rs / "Cargo.toml").write_text(
            '[workspace]\n[workspace.package]\nversion = "0.154.0"\n',
            encoding="utf-8",
        )
        (codex_rs / "Cargo.lock").write_text(
            'version = 4\n\n[[package]]\nname = "v8"\nversion = "150.4.0"\n',
            encoding="utf-8",
        )
        (root / "MODULE.bazel").write_text(
            'bazel_dep(name = "v8", version = "15.0.245.2")\n',
            encoding="utf-8",
        )
        (root / ".bazelrc").write_text(
            "common:v8-release-compat --flag=true\n"
            "common:v8-target-x64 --flag=true\n"
            "common:rusty-v8-upstream-libcxx --flag=true\n",
            encoding="utf-8",
        )

    def test_prepares_matching_source_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_source_tree(root)

            self.assertEqual(
                prepare(root, "0.154.0"),
                {
                    "codex_version": "0.154.0",
                    "rusty_v8_version": "150.4.0",
                    "embedded_v8_version": "15.0.245.2",
                    "bazelrc_changed": True,
                },
            )
            bazelrc = (root / ".bazelrc").read_text(encoding="utf-8")
            for line in MOJAVE_CONFIG_LINES:
                self.assertIn(line, bazelrc)

            self.assertFalse(prepare(root, "0.154.0")["bazelrc_changed"])

    def test_rejects_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_source_tree(root)

            with self.assertRaisesRegex(ValueError, "does not match"):
                prepare(root, "0.155.0")

    def test_rejects_missing_upstream_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_source_tree(root)
            (root / ".bazelrc").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "upstream Bazel configuration changed"):
                prepare(root, "0.154.0")


if __name__ == "__main__":
    unittest.main()

