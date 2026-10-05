import json
import os

import requests
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ai_engine.services.services import AIService

LANGUAGES = {
    "English": "English",
    "Twi": "Twi (Akan)",
    "Ga": "Ga (Gã)",
    "Ewe": "Ewe",
    "Yoruba": "Yoruba",
    "French": "French",
    "Arabic": "Arabic",
}

# Khaya/GhanaNLP language codes.  Keep these separate from the UI labels.
KHAYA_CODES = {
    # Khaya Translation API v2 requires ISO 639-3 language codes.
    "English": "eng",
    "Twi": "twi",
    "Ga": "gaa",
    "Ewe": "ewe",
    "Yoruba": "yor",
}

# Khaya Translation API v2 endpoint. Do not use the deprecated v1 endpoint.
KHAYA_API_URL = os.getenv("KHAYA_API_URL", "https://translation-api.ghananlp.org/v2/translate")
KHAYA_API_KEY = os.getenv("KHAYA_API_KEY", "").strip()
KHAYA_TIMEOUT = max(5, int(os.getenv("KHAYA_TIMEOUT", "20")))

MAX_TEXT_LENGTH = 4000
MAX_PAGE_TEXT_LENGTH = 12000
MAX_PAGE_ITEMS = 35


def _language_instruction(language):
    if language == "Ga":
        return """
Translate into natural, contemporary Ga (Gã), the language of the Ga people of Greater Accra, Ghana.
This is Ga, NOT Twi, Ewe, Ghanaian Pidgin, or a generic Ghanaian-language approximation.
Preserve names, personal names, school names, class names, subjects, dates, fees, IDs, URLs,
numbers, abbreviations and product/module names unless they are ordinary translatable words.
Do not invent a Ga word when you are uncertain. Keep uncertain proper nouns unchanged.
"""
    if language == "Twi":
        return """
Translate into natural contemporary Twi (Akan) suitable for a Ghanaian school-management application.
Do not use Ghanaian Pidgin. Preserve names, school names, class names, subjects, dates, amounts,
IDs, URLs, numbers, abbreviations and product/module names.
"""
    if language == "Ewe":
        return """
Translate into natural contemporary Ewe suitable for a Ghanaian school-management application.
Do not substitute Twi, Ga, Ghanaian Pidgin, or another Ghanaian language.
Preserve names, school names, class names, subjects, dates, amounts, IDs, URLs and numbers.
"""
    if language == "Yoruba":
        return """
Translate into natural contemporary Yoruba suitable for a professional school-management application.
Preserve Yoruba tone marks/diacritics where appropriate. Do not substitute Twi, Ga, Ewe, or Nigerian Pidgin.
Preserve names, school names, class names, subjects, dates, amounts, IDs, URLs and numbers.
"""
    if language == "French":
        return """
Translate into clear, professional French suitable for a school-management application.
Preserve names, school names, class names, dates, amounts, IDs, URLs and numbers.
"""
    if language == "Arabic":
        return """
Translate into clear Modern Standard Arabic suitable for a school-management application.
Preserve names, school names, class names, dates, amounts, IDs, URLs and numbers.
"""
    return """
Translate into clear, natural English suitable for a professional school-management application.
Preserve names, school names, class names, dates, amounts, IDs, URLs and numbers.
"""


def _khaya_pair(source, target):
    """Return the Khaya language pair, or None when Khaya does not cover it."""
    if source not in KHAYA_CODES or target not in KHAYA_CODES or source == target:
        return None
    return f"{KHAYA_CODES[source]}-{KHAYA_CODES[target]}"


def _extract_khaya_translation(data):
    """Handle the response shapes used by current/older GhanaNLP clients."""
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return ""

    # Current API/library variants commonly expose the translated value as
    # 'out', 'translation', or 'translated_text'. Keep this tolerant so a
    # gateway response change does not crash the Django view.
    for key in ("out", "translation", "translated_text", "text", "result"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Some wrappers return {"data": {"out": "..."}}.
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("out", "translation", "translated_text", "text", "result"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def _translate_with_khaya(text, source, target):
    """Translate Ghanaian-language pairs through Khaya/GhanaNLP."""
    global KHAYA_API_KEY

    pair = _khaya_pair(source, target)
    if not pair:
        return None, ""
    if not KHAYA_API_KEY:
        return None, "KHAYA_API_KEY is not configured."

    try:
        response = requests.post(
            KHAYA_API_URL,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "Ocp-Apim-Subscription-Key": KHAYA_API_KEY,
            },
            json={"in": text, "lang": pair},
            timeout=KHAYA_TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, f"Khaya connection failed: {exc}"

    if response.status_code != 200:
        # Never expose the secret key or a full provider response to users.
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("error") or "")
        except (ValueError, TypeError):
            pass
        if response.status_code in (401, 403):
            return None, "Khaya authentication failed. Check KHAYA_API_KEY and the Khaya subscription key permissions."
        return None, f"Khaya returned HTTP {response.status_code}{(': ' + detail) if detail else '.'}"

    try:
        data = response.json()
    except ValueError:
        # Accept a plain-text translation as well as the documented JSON
        # translation response.
        data = response.text

    translation = _extract_khaya_translation(data)
    if not translation:
        return None, "Khaya returned no translation."
    return translation, ""


def _translate_with_groq(text, source, target):
    system_prompt = f"""
You are the professional translation assistant for EduAI School Management, a Ghanaian school-management application.
Source language: {LANGUAGES[source]}
Target language: {LANGUAGES[target]}
{_language_instruction(target)}
Preserve paragraph structure and punctuation. Return only the translation.
"""
    return AIService._call_groq(
        system_prompt,
        text,
        max_tokens=1800,
        temperature=0.1,
        model="openai/gpt-oss-120b" if target in ("Ga", "Twi", "Ewe", "Yoruba") else None,
    )


def _translate_single(text, source, target):
    """Primary Khaya for Ghanaian pairs; Groq remains a safe fallback."""
    if source == target:
        return text, ""

    khaya_result, khaya_error = _translate_with_khaya(text, source, target)
    if khaya_result:
        return khaya_result, ""

    groq_result = _translate_with_groq(text, source, target)
    if groq_result:
        return groq_result.strip(), khaya_error

    return None, khaya_error or AIService.LAST_ERROR or "Translation service is unavailable."


@login_required
def language_translator(request):
    return render(request, "ai_engine/language_translator.html", {"languages": LANGUAGES})


@login_required
@require_POST
def language_translator_api(request):
    """Translate standalone text and batches of visible rendered page text."""
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
            return JsonResponse({
                "success": False,
                "error": provider_error or AIService.LAST_ERROR or "Translation service is unavailable.",
            }, status=503)

        return JsonResponse({"success": True, "translation": translation, "source": source, "target": target})

    raw_items = payload.get("items")
    if not raw_items or len(raw_items) > MAX_PAGE_ITEMS:
        return JsonResponse({"success": False, "error": "Invalid page translation batch."}, status=400)

    items = [str(item or "")[:500] for item in raw_items]
    if sum(len(item) for item in items) > MAX_PAGE_TEXT_LENGTH:
        return JsonResponse({"success": False, "error": "Page translation batch is too large."}, status=400)
    if source == target:
        return JsonResponse({"success": True, "translations": items, "source": source, "target": target})

    translations = []
    errors = []

    # Khaya's documented endpoint translates one text payload at a time. We
    # therefore translate each visible text node independently when a Khaya
    # pair is available. This costs more API calls but prevents one failed or
    # malformed node from shifting every subsequent page translation.
    if _khaya_pair(source, target) and KHAYA_API_KEY:
        for item in items:
            translated, error = _translate_with_khaya(item, source, target)
            if translated:
                translations.append(translated)
            else:
                fallback = _translate_with_groq(item, source, target)
                if fallback:
                    translations.append(fallback.strip())
                else:
                    errors.append(error or AIService.LAST_ERROR or "Translation failed.")
                    translations.append(item)

        if errors and len(errors) > max(2, len(items) // 3):
            return JsonResponse({
                "success": False,
                "error": "The Ghanaian-language translation service is temporarily unavailable. Please try again.",
            }, status=503)

        return JsonResponse({"success": True, "translations": translations, "source": source, "target": target})

    # Non-Khaya pairs (French/Arabic, or a missing Khaya key) retain the
    # previous batched Groq path so the page translator remains functional.
    numbered = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(items))
    system_prompt = f"""
You are the page-translation engine for EduAI School Management, a Ghanaian school-management application.
Source language: {LANGUAGES[source]}
Target language: {LANGUAGES[target]}
{_language_instruction(target)}

Translate every numbered item independently and preserve the exact order.
Return exactly one translated line for each input item.
Do not add numbering, explanations, markdown, quotation marks, or extra commentary.
If an item is a proper name, identifier, number, URL, abbreviation, or product/module name that should remain unchanged, return it unchanged.
"""
    # Keep the historical batch request for efficiency, but never make the
    # whole page fail just because the model returned fewer lines than asked.
    result = AIService._call_groq(
        system_prompt,
        numbered,
        max_tokens=max(500, min(2200, sum(len(x) for x in items) * 2)),
        temperature=0.1,
        model="openai/gpt-oss-120b" if target in ("Ga", "Twi", "Ewe", "Yoruba") else None,
    )

    def parse_lines(value):
        if not value:
            return []
        parsed = []
        for line in str(value).splitlines():
            line = line.strip()
            if not line:
                continue
            if ". " in line and line.split(". ", 1)[0].isdigit():
                line = line.split(". ", 1)[1].strip()
            parsed.append(line)
        return parsed

    lines = parse_lines(result)

    # If the batch response is malformed/incomplete, translate each item
    # independently. This is slower but guarantees positional integrity.
    if len(lines) != len(items):
        translations = []
        failed = 0
        for item in items:
            single, _ = _translate_single(item, source, target)
            if single:
                translations.append(single.strip())
            else:
                translations.append(item)
                failed += 1

        # Returning the original text for a failed node is preferable to
        # breaking the entire UI. The caller can still see which nodes were
        # not translated rather than receiving a misleading partial batch.
        return JsonResponse({
            "success": True,
            "translations": translations,
            "source": source,
            "target": target,
            "partial": bool(failed),
            "failed_items": failed,
        })

    return JsonResponse({"success": True, "translations": lines, "source": source, "target": target})
