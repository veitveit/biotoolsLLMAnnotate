#!/bin/bash
# Install the Ollama model specified in config.py
# Usage: bash install_ollama_model.sh

set -e

# Get model name from config.py (default: llama3.2)
MODEL="llama3.2"
CONFIG_FILE="$(dirname "$0")/../src/biotoolsllmannotate/config.py"

# Try to extract model from config.py
if [[ -f "$CONFIG_FILE" ]]; then
    MODEL_LINE=$(grep '"ollama_model"' "$CONFIG_FILE" | head -n1)
    if [[ $MODEL_LINE =~ "ollama_model"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]]; then
        MODEL="${BASH_REMATCH[1]}"
    fi
fi

echo "Installing Ollama model: $MODEL"
ollama pull "$MODEL"
echo "Model '$MODEL' installed."
