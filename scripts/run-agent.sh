#!/bin/zsh
set -euo pipefail

readonly runtime_dir="${HOME}/Library/Application Support/RepoHunter"
readonly env_file="${runtime_dir}/agent.env"

if [[ ! -r "${env_file}" ]]; then
  print -u2 "RepoHunter agent runtime file is missing: ${env_file}"
  exit 1
fi

set -a
source "${env_file}"
set +a

exec /opt/homebrew/bin/python3 \
  /Users/bgorzelic/dev/projects/repohunter/repohunter_agent.py \
  --host 127.0.0.1 \
  --port 8765 \
  --base-url https://dickie.taild93f81.ts.net:8765/a2a
