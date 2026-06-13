#!/bin/sh
set -e

OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"

echo "=== Checking Ollama availability (optional) ==="
if curl -sf --connect-timeout 5 "${OLLAMA_BASE_URL}/api/tags" > /dev/null 2>&1; then
  echo "  Ollama is available"

  echo "=== Pulling required Ollama models (skipped if already downloaded) ==="
  for model in nomic-embed-text llama3.1:8b; do
    if curl -sf "${OLLAMA_BASE_URL}/api/tags" | grep -q "\"${model}\""; then
      echo "  ${model}: already present"
    else
      echo "  Pulling ${model}..."
      curl -sf -X POST "${OLLAMA_BASE_URL}/api/pull" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"${model}\"}" | tail -1
      echo "  ${model}: done"
    fi
  done
else
  echo "  Ollama not available — local LLM and local embeddings are disabled"
  echo "  Embeddings will use OpenAI API; routing will use external LLM only"
fi

echo "=== Running DB migrations ==="
alembic upgrade head

echo "=== Starting AI Gateway ==="
exec uvicorn gateway.main:app --host 0.0.0.0 --port 8080
