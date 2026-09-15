import unittest

from scripts.select_release import select_release


class SelectReleaseTest(unittest.TestCase):
    def release(self, tag: str, *, draft: bool = False, prerelease: bool = False):
        return {
            "tag_name": tag,
            "draft": draft,
            "prerelease": prerelease,
            "html_url": f"https://github.com/openai/codex/releases/tag/{tag}",
        }

    def test_selects_stable_release(self):
        self.assertEqual(
            select_release(self.release("rust-v0.154.0")),
            {
                "version": "0.154.0",
                "upstream_tag": "rust-v0.154.0",
                "release_tag": "mojave-v0.154.0",
                "upstream_url": "https://github.com/openai/codex/releases/tag/rust-v0.154.0",
            },
        )

    def test_rejects_alpha_release(self):
        with self.assertRaisesRegex(ValueError, "not a stable"):
            select_release(self.release("rust-v0.155.0-alpha.1"))

    def test_rejects_prerelease_flag(self):
        with self.assertRaisesRegex(ValueError, "prerelease"):
            select_release(
                self.release("rust-v0.155.0", prerelease=True)
            )

    def test_rejects_draft(self):
        with self.assertRaisesRegex(ValueError, "draft"):
            select_release(self.release("rust-v0.155.0", draft=True))

    def test_rejects_requested_version_mismatch(self):
        with self.assertRaisesRegex(ValueError, "resolved to"):
            select_release(
                self.release("rust-v0.154.0"), requested_version="0.153.0"
            )


if __name__ == "__main__":
    unittest.main()

