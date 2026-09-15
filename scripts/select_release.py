#!/usr/bin/env python3
"""Validate and select a stable openai/codex GitHub release."""

import argparse
import json
import re
from pathlib import Path


STABLE_TAG = re.compile(r"^rust-v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$")


def select_release(payload: dict, requested_version: str | None = None) -> dict:
    if payload.get("draft") is not False:
        raise ValueError("the selected upstream release is a draft")
    if payload.get("prerelease") is not False:
        raise ValueError("the selected upstream release is a prerelease")

    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise ValueError("the upstream release does not contain a tag_name")

    match = STABLE_TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"not a stable Codex release tag: {tag!r}")

    version = match.group("version")
    if requested_version is not None and version != requested_version:
        raise ValueError(
            f"requested version {requested_version!r} resolved to {version!r}"
        )

    html_url = payload.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith(
        "https://github.com/openai/codex/releases/"
    ):
        raise ValueError("the upstream release URL is missing or unexpected")

    return {
        "version": version,
        "upstream_tag": tag,
        "release_tag": f"mojave-v{version}",
        "upstream_url": html_url,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_json", type=Path)
    parser.add_argument("--requested-version")
    args = parser.parse_args()

    payload = json.loads(args.release_json.read_text(encoding="utf-8"))
    selected = select_release(payload, args.requested_version)
    print(json.dumps(selected, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

