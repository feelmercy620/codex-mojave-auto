import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_mojave import (
    MOJAVE_CONFIG_LINES,
    PATCH_NAME,
    RUNTIME_CONFIG,
    RUNTIME_COPTS,
    USER_VERIFICATION_MACOS_DEPENDENCIES,
    USER_VERIFICATION_MOJAVE_LIB,
    disable_native_user_verification,
    prepare,
)


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
            'bazel_dep(name = "v8", version = "15.0.245.2")\n'
            'git_repository(\n'
            '    name = "rusty_v8_libcxx",\n'
            '    commit = "pinned-revision",\n'
            ')\n',
            encoding="utf-8",
        )
        runtimes = root / "third_party" / "v8"
        runtimes.mkdir(parents=True)
        for runtime in ("libcxx", "libcxxabi"):
            (runtimes / f"{runtime}.BUILD.bazel").write_text(
                'cc_library(name = "headers")\n'
                'cc_runtime_stage0_library(\n'
                f'    name = "{runtime}",\n'
                '    copts = ["-std=c++23"] + select({\n'
                '        "//conditions:default": ["-fPIC"],\n'
                '    }),\n'
                '    defines = [\n'
                '        "KEEP_THIS_DEFINE",\n'
                '    ],\n'
                ')\n', encoding="utf-8",
            )
        (root / "patches").mkdir()
        (root / "patches" / "BUILD.bazel").write_text(
            'exports_files([\n    "existing.patch",\n])\n', encoding="utf-8",
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
                    "runtimes_changed": True,
                    "user_verification_disabled": False,
                },
            )
            bazelrc = (root / ".bazelrc").read_text(encoding="utf-8")
            for line in MOJAVE_CONFIG_LINES:
                self.assertIn(line, bazelrc)

            for runtime in ("libcxx", "libcxxabi"):
                text = (root / "third_party/v8" / f"{runtime}.BUILD.bazel").read_text()
                self.assertIn(RUNTIME_CONFIG, text)
                self.assertIn(RUNTIME_COPTS, text)
                self.assertIn('"KEEP_THIS_DEFINE"', text)
                self.assertIn('cc_library(name = "headers")', text)
            module = (root / "MODULE.bazel").read_text()
            self.assertIn(f'patches = ["//patches:{PATCH_NAME}"]', module)
            self.assertIn('patch_args = ["-p1"]', module)
            self.assertIn('commit = "pinned-revision"', module)
            self.assertIn(PATCH_NAME, (root / "patches/BUILD.bazel").read_text())
            self.assertIn("101500", (root / "patches" / PATCH_NAME).read_text())
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            again = prepare(root, "0.154.0")
            self.assertFalse(again["bazelrc_changed"])
            self.assertFalse(again["runtimes_changed"])
            self.assertFalse(again["user_verification_disabled"])
            self.assertEqual(
                before,
                {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()},
            )

    def test_disables_macos_10_15_user_verification_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            crate = root / "codex-rs/user-verification"
            (crate / "src").mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                "[package]\nname = \"codex-user-verification\"\n\n"
                + USER_VERIFICATION_MACOS_DEPENDENCIES,
                encoding="utf-8",
            )
            (crate / "src/lib.rs").write_text(
                '#[cfg(any(target_os = "macos", test))]\nmod platform_macos;\n'
                '#[cfg(not(target_os = "macos"))]\nmod unsupported;\n'
                'pub fn platform_supported() -> bool { cfg!(target_os = "macos") }\n',
                encoding="utf-8",
            )

            self.assertTrue(disable_native_user_verification(root))
            manifest = (crate / "Cargo.toml").read_text(encoding="utf-8")
            self.assertNotIn("security-framework", manifest)
            self.assertEqual(
                (crate / "src/lib.rs").read_text(encoding="utf-8"),
                USER_VERIFICATION_MOJAVE_LIB,
            )
            self.assertFalse(disable_native_user_verification(root))

    def test_rejects_user_verification_source_drift_before_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            crate = root / "codex-rs/user-verification"
            (crate / "src").mkdir(parents=True)
            manifest = "[package]\n" + USER_VERIFICATION_MACOS_DEPENDENCIES
            (crate / "Cargo.toml").write_text(manifest, encoding="utf-8")
            (crate / "src/lib.rs").write_text("mod changed_upstream;\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "implementation changed"):
                disable_native_user_verification(root)
            self.assertEqual((crate / "Cargo.toml").read_text(encoding="utf-8"), manifest)

    def test_rejects_runtime_drift_before_writing_runtime_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_source_tree(root)
            path = root / "third_party/v8/libcxxabi.BUILD.bazel"
            path.write_text('cc_library(name = "different-runtime")\n')
            other = root / "third_party/v8/libcxx.BUILD.bazel"
            before = other.read_bytes()
            with self.assertRaisesRegex(ValueError, "expected one matching block"):
                prepare(root, "0.154.0")
            self.assertEqual(before, other.read_bytes())

    def test_rejects_existing_external_patch_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_source_tree(root)
            path = root / "MODULE.bazel"
            path.write_text(path.read_text().replace(
                '    commit =', '    patches = ["other.patch"],\n    commit =',
            ))
            with self.assertRaisesRegex(ValueError, "unfamiliar patch configuration"):
                prepare(root, "0.154.0")

    def test_patch_applies_and_preserves_posix_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            header = root / "src/include/aligned_alloc.h"
            header.parent.mkdir(parents=True)
            header.write_text(
                '#if defined(_LIBCPP_MSVCRT_LIKE)\n'
                '  return ::_aligned_malloc(__size, __alignment);\n'
                '\n'
                '// Android only provides aligned_alloc when targeting API 28 or higher.\n'
                '#  elif !defined(__ANDROID__) || __ANDROID_API__ >= 28\n'
                '  // aligned_alloc() requires that __size is a multiple of __alignment,\n'
                '  // but for C++ [new.delete.general], only states "if the value of an\n'
                '  // alignment argument passed to any of these functions is not a valid\n'
                '  return ::aligned_alloc(__alignment, __size);\n'
                '#else\n'
                '  void* result = nullptr;\n'
                '  return ::posix_memalign(&result, __alignment, __size) == 0 ? result : nullptr;\n'
                '#endif\n', encoding="utf-8", newline="\n",
            )
            patch = Path(__file__).resolve().parents[1] / "patches" / PATCH_NAME
            subprocess.run(["git", "apply", "--check", str(patch)], cwd=root, check=True)
            subprocess.run(["git", "apply", str(patch)], cwd=root, check=True)
            self.assertIn("__ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__ >= 101500", header.read_text())
            self.assertIn("::posix_memalign", header.read_text())

    @unittest.skipUnless(os.environ.get("CODEX_SOURCE_FIXTURE"), "optional real upstream checkout")
    def test_prepares_real_upstream_build_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            upstream = Path(os.environ["CODEX_SOURCE_FIXTURE"])
            for relative in (
                ".bazelrc", "MODULE.bazel", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
                "third_party/v8/libcxx.BUILD.bazel", "third_party/v8/libcxxabi.BUILD.bazel",
                "patches/BUILD.bazel",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(upstream / relative, target)
            result = prepare(root, "0.154.0")
            self.assertTrue(result["runtimes_changed"])
            self.assertFalse(prepare(root, "0.154.0")["runtimes_changed"])

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
