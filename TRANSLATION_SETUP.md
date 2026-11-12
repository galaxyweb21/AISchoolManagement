# EduAI Ghanaian Language Translation

This build replaces the old LLM-first Ga/Twi translation approach with a provider chain designed for low-resource Ghanaian languages.

## Translation order

### Twi
1. Optional Google Cloud Translation NMT when `EDUAI_TRANSLATOR_TWI_PROVIDER=google` and `GOOGLE_TRANSLATE_API_KEY` are configured.
2. NLLB neural translation service.
3. Existing Groq AI gateway as fallback.

Google Cloud officially lists Twi (Akan) as language code `ak` for its Translation API.

### Ga
1. NLLB neural translation service using `gaa_Latn`.
2. Existing Groq AI gateway as fallback.

Ga is deliberately **not** routed through Google Cloud Translation because Ga is not listed among Google's current official NMT language codes. Do not substitute Twi for Ga.

## Environment variables

The application already works without adding these variables because sensible defaults are provided.

```env
# Recommended for a better Twi route
EDUAI_TRANSLATOR_TWI_PROVIDER=nllb
GOOGLE_TRANSLATE_API_KEY=

# NLLB service; keep configurable so production can later point to a private/self-hosted service
EDUAI_NLLB_API_URL=https://winstxnhdw-nllb-api.hf.space/api/v4/translator
EDUAI_NLLB_TIMEOUT=45
EDUAI_TRANSLATOR_TIMEOUT=45

# Existing AI fallback
GROQ_TRANSLATION_MODEL=openai/gpt-oss-120b
```

For Twi with Google Cloud, set:

```env
EDUAI_TRANSLATOR_TWI_PROVIDER=google
GOOGLE_TRANSLATE_API_KEY=your_google_cloud_api_key
```

The key must only be stored in the server environment; never put it in JavaScript or a template.

## Why this is different

The page translator no longer sends every page string to a general chatbot as its primary translation engine. Ga and Twi use a dedicated neural translation path first. The application also protects URLs, email addresses, IDs, numbers, dates and Django template tokens from translation.

The page translator translates text nodes in batches while leaving buttons, form controls, scripts, URLs and interactive elements untouched. The selected language is persisted in browser storage and English restores the original DOM text.

## Production recommendation

The default NLLB URL is a configurable public service used to make the demo practical without adding a multi-gigabyte model to the Django Render image. For a commercial production deployment, point `EDUAI_NLLB_API_URL` at an EduAI-controlled NLLB/CTranslate2 service so availability, latency, privacy and model version are under your control.

For official school, disciplinary, examination, legal or government communication, final Ga/Twi text should still receive native-speaker review. The Bureau of Ghana Languages identifies translation, proofreading and orthographic vetting among its responsibilities.
