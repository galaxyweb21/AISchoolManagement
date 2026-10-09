# EduAI Offline Translation Setup

EduAI now supports three translation modes:

- `auto` — Khaya/Groq online first, then the local Ollama provider if an online provider is unavailable.
- `offline` — **no external translation calls**. Uses only the local Ollama service.
- `local` — local Ollama only; useful for a school LAN even when internet is available.

## Important quality note

Khaya remains the preferred provider for Ghanaian-language translation when internet is available. The offline provider is a general local multilingual model, so it should be tested and approved by Ghanaian-language speakers before it is used for official notices, report-card comments, legal text, or other high-stakes communication.

GhanaNLP's public work confirms that Ghanaian-language translation is a low-resource NLP problem and that GhanaNLP maintains datasets/models for research. The project should therefore treat offline translation as a fallback until a language-specific local model has been benchmarked for EduAI.

## Windows/local development

Install Ollama on the computer that runs Django, then download the model once while online:

```text
ollama pull qwen2.5:3b
```

Set:

```env
TRANSLATION_MODE=auto
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT=45
```

For a completely offline test:

```env
TRANSLATION_MODE=offline
```

Start Ollama and Django. The translator will not call Khaya or Groq in `offline` mode.

## Docker LAN demo

Start the optional local AI service:

```text
docker compose --profile offline-ai up -d
```

While internet is available, download the model into the Ollama volume:

```text
docker exec -it <ollama-container-name> ollama pull qwen2.5:3b
```

After the model has been downloaded, the Docker stack can run without internet. Set:

```env
TRANSLATION_MODE=offline
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
```

The Django container and Ollama container communicate over the local Docker network.

## What happens when internet is unavailable

`auto` mode stops repeatedly retrying Khaya after the first failed request for a page batch and switches to the local provider. This prevents an offline page translation from waiting through dozens of external requests.

`offline` mode skips external providers completely.
