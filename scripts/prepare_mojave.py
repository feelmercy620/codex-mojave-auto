#!/usr/bin/env python3
"""Inject the macOS 10.14 Bazel configuration into an upstream Codex tree."""

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
    return {
        "codex_version": actual_version,
        "rusty_v8_version": resolved_v8_crate_version(source_root),
        "embedded_v8_version": embedded_v8_version(source_root),
        "bazelrc_changed": changed,
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

