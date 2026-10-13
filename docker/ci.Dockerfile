# Tight CI image: just the tools needed to install and exercise the plugin.
# Repo code is checked out and mounted at run time, not baked into the image,
# so this only needs to be rebuilt when the toolchain itself changes.
FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git bash xz-utils python3 \
    && rm -rf /var/lib/apt/lists/*

# pixi — manages the Python/casatools environment declared in pixi.toml
RUN curl -fsSL https://pixi.sh/install.sh | bash \
    && mv /root/.pixi/bin/pixi /usr/local/bin/pixi

# Claude Code CLI (native installer; version floor enforced via the
# project's .claude/settings.json minimumVersion, not pinned here)
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"

# OpenCode CLI, for runs against non-Claude models (scripts/dev/run-isolated.sh)
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/root/.opencode/bin:${PATH}"

WORKDIR /workspace
