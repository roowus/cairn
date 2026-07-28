#!/usr/bin/env bash
# Pull a local model so Cairn can run end-to-end with NO cloud API key.
# Ollama exposes an OpenAI-compatible endpoint, so Cairn talks to it via
# provider=openai, base_url=http://localhost:11434/v1, api_key=ollama.
set -euo pipefail

MODEL="${CAIRN_OLLAMA_MODEL:-llama3.1}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: 'ollama' is not installed." >&2
  echo "  Install: https://ollama.com/download" >&2
  exit 1
fi

echo "Pulling '$MODEL' via Ollama (one-time)..."
ollama pull "$MODEL"

cat <<NOTE

  Done. Run Cairn against it with:
    export CAIRN_LLM__PROVIDER=openai
    export CAIRN_LLM__MODEL=$MODEL
    export CAIRN_LLM__BASE_URL=http://localhost:11434/v1
    export CAIRN_LLM__API_KEY=ollama
    uv run cairn
NOTE
