"""Local/offline translation provider for EduAI.

This provider talks only to a local Ollama-compatible endpoint. It never calls
Khaya, Groq, Google, or any other external service.
"""
import os

import requests


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = max(5, int(os.getenv("OLLAMA_TIMEOUT", "45")))


def _prompt(source, target, text):
    return f"""You are the offline translation engine for EduAI School Management in Ghana.
Translate the text from {source} to {target}.

Rules:
- Return ONLY the translation. No explanation, labels, quotation marks or markdown.
- Use the requested language, not another African language.
- Preserve names, school names, people names, class names, subjects, IDs, URLs,
  dates, numbers, currency amounts, abbreviations and product/module names.
- Preserve paragraph structure and punctuation where practical.
- For Ga, use natural contemporary Ga (Gã) of Greater Accra.
- For Twi, use natural contemporary Akan/Twi used in Ghana.
- For Ewe, use natural contemporary Ewe.
- For Fante, use natural contemporary Fante.
- For Dagbani, use natural contemporary Dagbani.
- For Kusaal, use natural contemporary Kusaal.
- For Yoruba, use natural contemporary Yoruba and preserve appropriate diacritics.
- Do not invent a translation for a proper noun.

Text:
{text}
"""


def translate_offline(text, source, target):
    """Return (translation, error). Only localhost is contacted."""
    if source == target:
        return text, ""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": _prompt(source, target, text),
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
    except requests.RequestException:
        return None, "Local offline translation service is not running."

    if response.status_code != 200:
        return None, f"Local translation service returned HTTP {response.status_code}."

    try:
        data = response.json()
    except ValueError:
        return None, "Local translation service returned invalid data."

    result = str(data.get("response") or "").strip()
    if not result:
        return None, "Local translation service returned no translation."

    return result, ""
