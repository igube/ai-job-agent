"""Config used only by the Etap 2 (AI) path. Etap 1 (offline) never imports this.

Local model via Ollama — no API key, no per-token cost.
"""

import os

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b-instruct")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST")  # None = ollama package default (localhost:11434)
