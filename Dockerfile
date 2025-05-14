# Stage 1: deps only, based on uv’s Debian-slim image
FROM ghcr.io/astral-sh/uv:bookworm-slim AS builder

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Default port if not overridden at runtime
ENV PORT=8000

# Expose the chosen port
EXPOSE ${PORT}

# Use the non-root uv virtualenv by default
ENV PATH="/app/.venv/bin:$PATH"

# Entrypoint: run the MCP server
CMD ["mcp-github-owners"]
