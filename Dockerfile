# RepoHunter MCP server — for the Docker MCP Catalog / container-isolated runs.
# NOTE: RepoHunter is zero-dependency stdlib Python; `uvx repohunter-mcp` is the simpler path for
# most people. This image exists for users who prefer container isolation or discover it via Docker.
FROM python:3.12-slim
LABEL org.opencontainers.image.title="RepoHunter MCP" \
      org.opencontainers.image.description="Reuse-decision skill layer for AI coding agents (MCP server)." \
      org.opencontainers.image.source="https://github.com/meetziggy/repohunter" \
      org.opencontainers.image.licenses="MIT"
WORKDIR /app
COPY repohunter.py repohunter_mcp.py ./
# MCP speaks over stdio (stdin/stdout) — no ports to expose.
ENTRYPOINT ["python3", "repohunter_mcp.py"]
