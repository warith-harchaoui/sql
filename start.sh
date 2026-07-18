#!/usr/bin/env bash
# start.sh — Lance la démo text2sql de bout en bout.
#
# Étapes :
#   1. vérifie qu'Ollama répond ;
#   2. tire les modèles requis s'ils manquent ;
#   3. construit la base si elle n'existe pas ;
#   4. démarre l'API FastAPI (qui sert aussi le front).
#
# Usage :  ./start.sh          (port 8000 par défaut)
#          PORT=8080 ./start.sh
set -euo pipefail

# Port d'écoute (surchargable par variable d'environnement).
PORT="${PORT:-8000}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

# Modèles utilisés par la démo (mêmes défauts que backend/llm.py).
MODEL_SQL="${MODEL_SQL:-qwen2.5-coder:latest}"
MODEL_FIGURE="${MODEL_FIGURE:-gemma4:e4b-mlx}"
MODEL_EMBED="${MODEL_EMBED:-nomic-embed-text:latest}"

# 1) Ollama joignable ? Sinon on explique comment le démarrer.
echo "→ Vérification du serveur Ollama sur ${OLLAMA_URL}…"
if ! curl -sf "${OLLAMA_URL}/api/tags" >/dev/null; then
  echo "✗ Ollama injoignable. Démarre-le dans un autre terminal : ollama serve" >&2
  exit 1
fi

# 2) Tirage des modèles manquants (idempotent : ollama pull ne re-télécharge pas).
for m in "${MODEL_SQL}" "${MODEL_FIGURE}" "${MODEL_EMBED}"; do
  # On teste la présence du tag ; on ne tire que s'il manque.
  if ! ollama list | awk '{print $1}' | grep -qx "${m}"; then
    echo "→ Modèle manquant : ${m} — tirage…"
    ollama pull "${m}"
  fi
done

# 3) Construction de la base si absente (déterministe, ~33k lignes).
if [ ! -f "data/institut.db" ]; then
  echo "→ Construction de la base data/institut.db…"
  python -m backend.build_db
fi

# 4) Démarrage de l'API + front. --reload pratique en démo/développement.
echo "→ Démarrage sur http://localhost:${PORT}  (Ctrl+C pour arrêter)"
exec uvicorn backend.server:app --host 0.0.0.0 --port "${PORT}" --reload
