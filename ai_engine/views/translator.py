import json
import logging
import os
import time

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ai_engine.services.services import AIService

logger = logging.getLogger(__name__)

LANGUAGES = {
    "English": "English",
    "Twi": "Twi (Akan)",
    "Ga": "Ga (Gã)",
    "Ewe": "Ewe",
    "Yoruba": "Yoruba",
    "Fante": "Fante",
    "Dagbani": "Dagbani",
    "Kusaal": "Kusaal",
    "French": "French",
    "Arabic": "Arabic",
}

KHAYA_CODES = {
    "English": "eng", "Twi": "twi", "Ga": "gaa", "Ewe": "ewe",
    "Yoruba": "yor", "Fante": "fat", "Dagbani": "dag", "Kusaal": "kus",
}

KHAYA_DEFAULT_API_URL = "https://translation-api.ghananlp.org/v2/translate"
KHAYA_DEFAULT_TIMEOUT = 20
MAX_TEXT_LENGTH = 4000
MAX_PAGE_TEXT_LENGTH = 24000
MAX_PAGE_ITEMS = 80
KHAYA_BATCH_SIZE = 20

# Provider circuit breakers. A failed Khaya subscription must never make
# every page load repeat the same 403 request. Network failures are also
# suppressed briefly so an offline browser does not wait on provider timeouts.
KHAYA_AUTH_COOLDOWN = 600
KHAYA_NETWORK_COOLDOWN = 60
_KHAYA_AUTH_UNAVAILABLE_UNTIL = 0.0
_KHAYA_NETWORK_UNAVAILABLE_UNTIL = 0.0


def _khaya_config():
    key = str(getattr(settings, "KHAYA_API_KEY", "") or os.getenv("KHAYA_API_KEY", "") or "").strip()
    url = str(getattr(settings, "KHAYA_API_URL", "") or os.getenv("KHAYA_API_URL", "") or KHAYA_DEFAULT_API_URL).strip()
    timeout_raw = getattr(settings, "KHAYA_TIMEOUT", None) or os.getenv("KHAYA_TIMEOUT", str(KHAYA_DEFAULT_TIMEOUT))
    try:
        timeout = max(5, int(timeout_raw))
    except (TypeError, ValueError):
        timeout = KHAYA_DEFAULT_TIMEOUT
    return key, url, timeout


def _language_instruction(language):
    instructions = {
        "Twi": "Translate into natural contemporary Twi (Akan) suitable for a Ghanaian school-management application.",
        "Ga": "Translate into natural contemporary Ga (Gã) used in Greater Accra, Ghana. Do not substitute Twi or Ewe.",
        "Ewe": "Translate into natural contemporary Ewe. Do not substitute Twi or Ga.",
        "Yoruba": "Translate into natural contemporary Yoruba and preserve appropriate diacritics.",
        "Fante": "Translate into natural contemporary Fante suitable for a Ghanaian school-management application.",
        "Dagbani": "Translate into natural contemporary Dagbani suitable for a Ghanaian school-management application.",
        "Kusaal": "Translate into natural contemporary Kusaal suitable for a Ghanaian school-management application.",
        "French": "Translate into clear professional French.",
        "Arabic": "Translate into clear Modern Standard Arabic.",
    }
    return instructions.get(language, "Translate into clear natural English.")


def _khaya_pair(source, target):
    if source not in KHAYA_CODES or target not in KHAYA_CODES or source == target:
        return None
    return f"{KHAYA_CODES[source]}-{KHAYA_CODES[target]}"


def _extract_khaya_translation(data):
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        for item in data:
            value = _extract_khaya_translation(item)
            if value:
                return value
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("out", "translation", "translated_text", "text", "result"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        return _extract_khaya_translation(nested)
    return ""


def _translate_with_khaya(text, source, target):
    global _KHAYA_AUTH_UNAVAILABLE_UNTIL, _KHAYA_NETWORK_UNAVAILABLE_UNTIL

    pair = _khaya_pair(source, target)
    if not pair:
        return None, ""

    now = time.monotonic()
    if now < _KHAYA_AUTH_UNAVAILABLE_UNTIL:
        return None, "Khaya access is temporarily unavailable (HTTP 403). Using the translation fallback without retrying Khaya."
    if now < _KHAYA_NETWORK_UNAVAILABLE_UNTIL:
        return None, "No internet connection. EduAI language translation requires an internet connection to reach Khaya."

    api_key, api_url, timeout = _khaya_config()
    if not api_key:
        logger.error("Khaya translation: KHAYA_API_KEY is empty.")
        return None, "KHAYA_API_KEY is not configured."

    try:
        response = requests.post(
            api_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Ocp-Apim-Subscription-Key": api_key,
            },
            json={"in": text, "lang": pair},
            timeout=timeout,
        )
    except requests.exceptions.ConnectionError:
        _KHAYA_NETWORK_UNAVAILABLE_UNTIL = time.monotonic() + KHAYA_NETWORK_COOLDOWN
        logger.warning("Khaya unavailable: no internet/DNS connection for %s", pair)
        return None, "No internet connection. EduAI language translation requires an internet connection to reach Khaya. Please reconnect and try again."
    except requests.exceptions.Timeout:
        _KHAYA_NETWORK_UNAVAILABLE_UNTIL = time.monotonic() + KHAYA_NETWORK_COOLDOWN
        logger.warning("Khaya request timed out for %s", pair)
        return None, "Khaya translation timed out. Please check your internet connection and try again."
    except requests.RequestException as exc:
        _KHAYA_NETWORK_UNAVAILABLE_UNTIL = time.monotonic() + KHAYA_NETWORK_COOLDOWN
        logger.warning("Khaya request failed for %s: %s", pair, exc)
        return None, "Khaya translation is temporarily unavailable. Please check your internet connection and try again."

    logger.info("Khaya translation response: pair=%s status=%s bytes=%s", pair, response.status_code, len(response.content or b""))

    if response.status_code != 200:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or "")
                else:
                    detail = str(body.get("message") or "")
        except (ValueError, TypeError):
            pass
        if response.status_code == 401:
            _KHAYA_AUTH_UNAVAILABLE_UNTIL = time.monotonic() + KHAYA_AUTH_COOLDOWN
            return None, "Khaya rejected the subscription key (HTTP 401). Please verify the Khaya subscription key configuration."
        if response.status_code == 403:
            _KHAYA_AUTH_UNAVAILABLE_UNTIL = time.monotonic() + KHAYA_AUTH_COOLDOWN
            return None, "Khaya denied access (HTTP 403). Using the translation fallback without repeatedly contacting Khaya."
        if response.status_code == 429:
            return None, "Khaya translation limit reached (HTTP 429). Please wait a moment and try again."
        return None, f"Khaya returned HTTP {response.status_code}{(': ' + detail) if detail else '.'}"

    try:
        data = response.json()
    except ValueError:
        data = response.text

    translation = _extract_khaya_translation(data)
    if not translation:
        logger.error("Khaya returned HTTP 200 but no translation for pair=%s. Response=%r", pair, response.text[:500])
        return None, "Khaya returned no translation."
    return translation, ""


def _translate_with_groq(text, source, target):
    system_prompt = f"""
You are the professional translation assistant for EduAI School Management, a Ghanaian school-management application.
Source language: {LANGUAGES[source]}
Target language: {LANGUAGES[target]}
{_language_instruction(target)}
Preserve names, school names, class names, dates, amounts, IDs, URLs, numbers and abbreviations.
Return only the translation.
"""
    return AIService._call_groq(system_prompt, text, max_tokens=1800, temperature=0.1, model=None)


def _translate_single(text, source, target):
    if source == target:
        return text, ""
    if _khaya_pair(source, target):
        translated, error = _translate_with_khaya(text, source, target)
        # Khaya remains the preferred provider for Ghanaian languages. If the
        # subscription is currently returning 401/403, however, keep the
        # translator usable by falling back to one Groq translation request.
        # This is deliberately a single fallback, never a retry storm.
        if translated:
            return translated, ""
        if error and ("HTTP 401" in error or "HTTP 403" in error):
            result = _translate_with_groq(text, source, target)
            if result:
                logger.warning("Khaya unavailable for %s; used Groq fallback.", _khaya_pair(source, target))
                return result.strip(), ""
        return None, error
    result = _translate_with_groq(text, source, target)
    if result:
        return result.strip(), ""
    return None, AIService.LAST_ERROR or "Translation service is unavailable."


def _parse_groq_translation_batch(result, expected):
    """Parse a numbered Groq translation batch without requiring one line/item.

    Translated text can legitimately contain line breaks, so the old
    splitlines() parser could report a perfectly valid response as
    "incomplete" and turn a successful request into HTTP 503.
    """
    if not result:
        return None
    text = str(result).strip()
    # Prefer a JSON array when the model followed the requested format.
    try:
        candidate = text
        if candidate.startswith("```"):
            candidate = candidate.strip("`").strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
        data = json.loads(candidate)
        if isinstance(data, list) and len(data) == expected:
            values = [str(x).strip() for x in data]
            if all(values):
                return values
    except (ValueError, TypeError):
        pass

    # Fallback: numbered sections. A translation may contain newlines; keep
    # those lines attached to the current numbered item.
    import re
    matches = list(re.finditer(r"(?m)^\s*(\d+)\.\s*", text))
    if not matches:
        return None
    values = [None] * expected
    for pos, match in enumerate(matches):
        try:
            index = int(match.group(1)) - 1
        except ValueError:
            continue
        if not 0 <= index < expected:
            continue
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        value = text[match.end():end].strip()
        if value:
            values[index] = value
    if all(values):
        return values
    return None


def _translate_with_groq_batch(items, source, target):
    system_prompt = f"""
You are the professional translation assistant for EduAI School Management, a Ghanaian school-management application.
Translate the input items from {LANGUAGES[source]} to {LANGUAGES[target]}.
{_language_instruction(target)}
Preserve names, school names, class names, dates, amounts, IDs, URLs, numbers and abbreviations.
Return ONLY a valid JSON array containing exactly {len(items)} strings, in the same order as the input items.
Do not add markdown fences, numbering, commentary, or extra fields.
"""
    numbered = json.dumps(items, ensure_ascii=False)
    result = AIService._call_groq(
        system_prompt,
        numbered,
        max_tokens=max(700, min(6000, sum(len(x) for x in items) * 2)),
        temperature=0.1,
        model="openai/gpt-oss-20b",
    )
    values = _parse_groq_translation_batch(result, len(items))
    if values:
        return values, ""
    return [None] * len(items), AIService.LAST_ERROR or "The translation service returned an invalid batch response."


def _khaya_page_batch(items, source, target):
    """Translate a small group in one Khaya request to avoid a request storm.

    Khaya v2 accepts one text field per request. A stable delimiter lets us
    send several UI strings together while preserving their order.
    """
    marker = "\n\n<<<EDUAI_ITEM_%02d>>>\n\n"
    text = "".join(marker % i + item for i, item in enumerate(items))
    translated, error = _translate_with_khaya(text, source, target)
    if not translated:
        return [None] * len(items), error

    parts = translated.split("<<<EDUAI_ITEM_")
    if len(parts) != len(items) + 1:
        logger.warning("Khaya batch delimiter was not preserved for %s items.", len(items))
        return [None] * len(items), "Khaya returned an invalid batch response."

    result = [None] * len(items)
    for part in parts[1:]:
        try:
            number_text, value = part.split(">>>", 1)
            index = int(number_text.split("_")[-1])
            if 0 <= index < len(items):
                result[index] = value.strip()
        except (ValueError, IndexError):
            return [None] * len(items), "Khaya returned an invalid batch response."
    if any(not value for value in result):
        return [None] * len(items), "Khaya returned an incomplete batch."
    return result, ""


@login_required
def language_translator(request):
    return render(request, "ai_engine/language_translator.html", {"languages": LANGUAGES})


@login_required
@require_POST
def language_translator_api(request):
    content_type = request.META.get("CONTENT_TYPE", "")
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            return JsonResponse({"success": False, "error": "Invalid JSON request."}, status=400)
    else:
        payload = request.POST

    target = str(payload.get("target") or "").strip()
    source = str(payload.get("source") or "English").strip()
    page_mode = str(payload.get("page_mode") or "").strip().lower() in ("1", "true", "yes")
    if source not in LANGUAGES or target not in LANGUAGES:
        return JsonResponse({"success": False, "error": "Please select supported languages."}, status=400)

    if not page_mode or not isinstance(payload.get("items"), list):
        text = str(payload.get("text") or "").strip()
        if not text:
            return JsonResponse({"success": False, "error": "Enter text to translate."}, status=400)
        if len(text) > MAX_TEXT_LENGTH:
            return JsonResponse({"success": False, "error": f"Please keep the text below {MAX_TEXT_LENGTH:,} characters."}, status=400)
        translation, provider_error = _translate_single(text, source, target)
        if translation is None:
            return JsonResponse({"success": False, "error": provider_error or "Translation service is unavailable."}, status=503)
        return JsonResponse({"success": True, "translation": translation, "source": source, "target": target})

    raw_items = payload.get("items")
    if not raw_items or len(raw_items) > MAX_PAGE_ITEMS:
        return JsonResponse({"success": False, "error": "Invalid page translation batch."}, status=400)
    items = [str(item or "")[:500] for item in raw_items]
    if sum(len(item) for item in items) > MAX_PAGE_TEXT_LENGTH:
        return JsonResponse({"success": False, "error": "Page translation batch is too large."}, status=400)
    if source == target:
        return JsonResponse({"success": True, "translations": items, "source": source, "target": target})

    if _khaya_pair(source, target):
        # Try Khaya once for this page. If the subscription is denied, or
        # Khaya is unreachable, immediately switch to ONE Groq batch. Never
        # retry Khaya once the circuit breaker has opened.
        values, khaya_error = _khaya_page_batch(items, source, target)
        if not khaya_error and all(values):
            return JsonResponse({
                "success": True,
                "translations": values,
                "source": source,
                "target": target,
            })

        fallback_values, fallback_error = _translate_with_groq_batch(items, source, target)
        if fallback_values and all(fallback_values):
            return JsonResponse({
                "success": True,
                "translations": fallback_values,
                "source": source,
                "target": target,
                "provider_fallback": True,
            })

        # Keep the page usable even when the fallback provider has a bad
        # response. Returning 503 caused the browser translator to enter a
        # long provider-unavailable state and stop translating later pages.
        # The original text is safe for failed items and the caller can keep
        # working normally.
        return JsonResponse({
            "success": True,
            "translations": items,
            "source": source,
            "target": target,
            "partial": True,
            "failed_items": len(items),
            "error": fallback_error or khaya_error or "Some page text could not be translated yet.",
        })

    numbered = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(items))
    system_prompt = f"""
Translate every numbered item independently from {LANGUAGES[source]} to {LANGUAGES[target]}.
{_language_instruction(target)}
Return exactly one translated line for each input item, preserving order.
"""
    result = AIService._call_groq(system_prompt, numbered, max_tokens=max(500, min(2200, sum(len(x) for x in items) * 2)), temperature=0.1, model=None)
    lines = []
    if result:
        for line in str(result).splitlines():
            line = line.strip()
            if line:
                if ". " in line and line.split(". ", 1)[0].isdigit():
                    line = line.split(". ", 1)[1].strip()
                lines.append(line)
    if len(lines) != len(items):
        return JsonResponse({"success": True, "translations": items, "source": source, "target": target, "partial": True, "failed_items": len(items), "error": "The translation service returned an incomplete batch. Please try again."})
    return JsonResponse({"success": True, "translations": lines, "source": source, "target": target})
