#!/usr/bin/env python3
"""Prepare V8 and its bundled C++ runtimes for macOS 10.14."""

import argparse
import json
import re
import tomllib
from pathlib import Path


BEGIN_MARKER = "# >>> codex-mojave-auto >>>"
END_MARKER = "# <<< codex-mojave-auto <<<"
MOJAVE_CONFIG_LINES = (
    "common:macos-x86_64-10-14 --copt=-mmacosx-version-min=10.14",
    "common:macos-x86_64-10-14 --linkopt=-mmacosx-version-min=10.14",
)
REQUIRED_UPSTREAM_CONFIGS = (
    "v8-release-compat",
    "v8-target-x64",
    "rusty-v8-upstream-libcxx",
)
PATCH_NAME = "libcxx_apple_posix_memalign.patch"
RUNTIME_CONFIG = '''
# Runtime transitions do not reliably inherit top-level --copt flags.
config_setting(
    name = "is_macos_x86_64",
    constraint_values = [
        "@platforms//cpu:x86_64",
        "@platforms//os:macos",
    ],
)
'''
RUNTIME_COPTS = ''' + select({
        ":is_macos_x86_64": ["-mmacosx-version-min=10.14"],
        "//conditions:default": [],
    })'''


def replace_once(text: str, old: str, new: str, surface: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"upstream {surface} changed; expected one matching block")
    return text.replace(old, new, 1)


def prepare_runtimes(source_root: Path) -> bool:
    # Validate every surface before writing any of these runtime changes.
    updates = {}
    for runtime in ("libcxx", "libcxxabi"):
        path = source_root / "third_party" / "v8" / f"{runtime}.BUILD.bazel"
        text = path.read_text(encoding="utf-8")
        if RUNTIME_CONFIG in text and RUNTIME_COPTS in text:
            continue
        if "is_macos_x86_64" in text:
            raise ValueError(f"incomplete or unfamiliar Mojave configuration in {path}")
        text = replace_once(
            text, "cc_runtime_stage0_library(",
            RUNTIME_CONFIG + "\ncc_runtime_stage0_library(", str(path),
        )
        # Attach the flag to copts on the runtime itself, not its header target.
        text = replace_once(
            text, "    }),\n    defines = [",
            f"    }}){RUNTIME_COPTS},\n    defines = [", str(path),
        )
        updates[path] = text

    module_path = source_root / "MODULE.bazel"
    module = module_path.read_text(encoding="utf-8")
    blocks = list(re.finditer(
        r'git_repository\(\s*name = "rusty_v8_libcxx",.*?\n\)',
        module, re.DOTALL,
    ))
    if len(blocks) != 1:
        raise ValueError("upstream rusty_v8_libcxx repository declaration changed")
    block = blocks[0].group()
    attributes = (
        '    patch_args = ["-p1"],\n'
        f'    patches = ["//patches:{PATCH_NAME}"],\n'
    )
    if attributes not in block:
        if re.search(r"\b(patches|patch_args|patch_cmds)\s*=", block):
            raise ValueError("upstream libc++ already has unfamiliar patch configuration")
        updated = block[:-2] + "\n" + attributes + ")"
        updates[module_path] = module.replace(block, updated, 1)

    exports_path = source_root / "patches" / "BUILD.bazel"
    exports = exports_path.read_text(encoding="utf-8")
    if f'"{PATCH_NAME}"' not in exports:
        updates[exports_path] = replace_once(
            exports, "exports_files([",
            f'exports_files([\n    "{PATCH_NAME}",', str(exports_path),
        )

    # Bazel applies this to the pinned external libc++ repository before compiling.
    # Both new.cpp and libc++abi's fallback_malloc.cpp use the patched helper.
    patch = (Path(__file__).resolve().parents[1] / "patches" / PATCH_NAME).read_text(
        encoding="utf-8"
    )
    destination = source_root / "patches" / PATCH_NAME
    if destination.exists():
        if destination.read_text(encoding="utf-8") != patch:
            raise ValueError("found a different libc++ Mojave patch in upstream source")
    else:
        updates[destination] = patch
    for path, text in updates.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    return bool(updates)


def workspace_version(source_root: Path) -> str:
    cargo_toml = tomllib.loads(
        (source_root / "codex-rs" / "Cargo.toml").read_text(encoding="utf-8")
    )
    try:
        version = cargo_toml["workspace"]["package"]["version"]
    except (KeyError, TypeError) as exc:
        raise ValueError("could not read workspace.package.version") from exc
    if not isinstance(version, str):
        raise ValueError("workspace.package.version is not a string")
    return version


def resolved_v8_crate_version(source_root: Path) -> str:
    cargo_lock = tomllib.loads(
        (source_root / "codex-rs" / "Cargo.lock").read_text(encoding="utf-8")
    )
    versions = {
        package["version"]
        for package in cargo_lock.get("package", [])
        if package.get("name") == "v8"
    }
    if len(versions) != 1:
        raise ValueError(f"expected one resolved v8 crate version, found {versions}")
    return versions.pop()


def embedded_v8_version(source_root: Path) -> str:
    module_bazel = (source_root / "MODULE.bazel").read_text(encoding="utf-8")
    match = re.search(r'bazel_dep\(name = "v8", version = "([0-9.]+)"\)', module_bazel)
    if match is None:
        raise ValueError("could not find the embedded V8 Bazel version")
    return match.group(1)


def inject_mojave_config(source_root: Path) -> bool:
    bazelrc_path = source_root / ".bazelrc"
    bazelrc = bazelrc_path.read_text(encoding="utf-8")

    missing_upstream = [
        config
        for config in REQUIRED_UPSTREAM_CONFIGS
        if f"common:{config} " not in bazelrc
    ]
    if missing_upstream:
        raise ValueError(
            "upstream Bazel configuration changed; missing: "
            + ", ".join(missing_upstream)
        )

    present_mojave_lines = [line in bazelrc for line in MOJAVE_CONFIG_LINES]
    if all(present_mojave_lines):
        return False
    if any(present_mojave_lines) or BEGIN_MARKER in bazelrc or END_MARKER in bazelrc:
        raise ValueError("found an incomplete macOS Mojave Bazel configuration")

    block = "\n".join((BEGIN_MARKER, *MOJAVE_CONFIG_LINES, END_MARKER))
    bazelrc_path.write_text(bazelrc.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
    return True


def prepare(source_root: Path, expected_version: str) -> dict:
    actual_version = workspace_version(source_root)
    if actual_version != expected_version:
        raise ValueError(
            f"upstream source version {actual_version!r} does not match "
            f"expected version {expected_version!r}"
        )

    changed = inject_mojave_config(source_root)
    runtimes_changed = prepare_runtimes(source_root)
    return {
        "codex_version": actual_version,
        "rusty_v8_version": resolved_v8_crate_version(source_root),
        "embedded_v8_version": embedded_v8_version(source_root),
        "bazelrc_changed": changed,
        "runtimes_changed": runtimes_changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()

    result = prepare(args.source_root.resolve(), args.expected_version)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

