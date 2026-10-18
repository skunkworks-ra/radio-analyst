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

# Non-root user for scripts/dev/run-isolated.sh (podman --user analyst). No
# final USER: the GitHub container jobs run as root and still find both CLIs.
RUN useradd -m -u 1000 analyst && mkdir -p /work && chown analyst:analyst /work

# Claude Code CLI (native installer; version floor enforced via the
# project's .claude/settings.json minimumVersion, not pinned here)
RUN su analyst -c 'curl -fsSL https://claude.ai/install.sh | bash' \
    && ln -s /home/analyst/.local/bin/claude /usr/local/bin/claude

# OpenCode CLI, for runs against non-Claude models (scripts/dev/run-isolated.sh)
RUN su analyst -c 'curl -fsSL https://opencode.ai/install | bash' \
    && ln -s /home/analyst/.opencode/bin/opencode /usr/local/bin/opencode

WORKDIR /workspace
