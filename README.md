# Codex CLI for macOS Mojave

This repository automatically builds unofficial x86_64 Codex CLI packages for
macOS 10.14 Mojave.

Every six hours, GitHub Actions checks the latest stable release in
[`openai/codex`](https://github.com/openai/codex/releases). Drafts and tags that
contain alpha, beta, or release-candidate suffixes are rejected. When a stable
release has not been built before, the workflow:

1. checks out the exact upstream `rust-vX.Y.Z` tag;
2. adds a Bazel configuration targeting macOS 10.14;
3. rebuilds the matching V8 and `rusty_v8` artifacts;
4. rejects artifacts that reference `_aligned_alloc`;
5. runs the V8 smoke tests and builds the complete Codex package;
6. verifies the final x86_64 executables and publishes a GitHub Release.

## Run a build manually

Open **Actions → Build stable Codex for macOS Mojave → Run workflow**. Leave the
version blank to select the latest stable release, or enter a stable version
such as `0.154.0`.

If the corresponding `mojave-vX.Y.Z` release already exists, the workflow exits
successfully without rebuilding it. A failed build does not create a release,
so it can be rerun after the compatibility logic is updated.

The V8 build is large and can take several hours on the Intel macOS runner.

## Install a release

Download the `.tar.gz` file from this repository's Releases page, then run:

```bash
version="0.154.0"
archive="$HOME/Downloads/codex-mojave-${version}-x86_64-apple-darwin.tar.gz"
install_dir="$HOME/.local/opt/codex-mojave"

mkdir -p "$install_dir"
tar -xzf "$archive" -C "$install_dir"
xattr -dr com.apple.quarantine "$install_dir" 2>/dev/null || true

printf '%s\n' 'export PATH="$HOME/.local/opt/codex-mojave/bin:$PATH"' \
  >> "$HOME/.bash_profile"
source "$HOME/.bash_profile"

codex --version
```

User configuration and login data remain under `~/.codex`.

## Maintenance

The workflow intentionally stops when upstream changes any required V8 Bazel
configuration or when the resulting binaries are no longer Mojave-compatible.
This prevents silently publishing a package that only builds on newer macOS
versions.

This project is independent of OpenAI. Codex itself is licensed by its upstream
project; this repository only contains automation and compatibility logic.

