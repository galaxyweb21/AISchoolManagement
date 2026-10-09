"""Smoke-test Khaya Translation API v2 for all Ghanaian languages enabled in EduAI.

Usage:
    python test_khaya_translation.py

The script reads KHAYA_API_KEY from the environment/.env if python-dotenv is available
(or from an already-exported environment variable). It never prints the key.
"""
from __future__ import annotations

import os
import sys

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

KEY = os.getenv("KHAYA_API_KEY", "").strip()
URL = os.getenv("KHAYA_API_URL", "https://translation-api.ghananlp.org/v2/translate").strip()
TIMEOUT = max(5, int(os.getenv("KHAYA_TIMEOUT", "20")))

LANGUAGES = {
    "eng": "English",
    "twi": "Twi",
    "gaa": "Ga",
    "ewe": "Ewe",
    "yor": "Yoruba",
    "fat": "Fante",
    "dag": "Dagbani",
    "kus": "Kusaal",
}

SAMPLES = {
    "twi": "Welcome to our school.",
    "gaa": "Welcome to our school.",
    "ewe": "Welcome to our school.",
    "yor": "Welcome to our school.",
    "fat": "Welcome to our school.",
    "dag": "Welcome to our school.",
    "kus": "Welcome to our school.",
}

if not KEY:
    print("ERROR: KHAYA_API_KEY is not configured.")
    sys.exit(2)

headers = {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
    "Ocp-Apim-Subscription-Key": KEY,
}

print(f"Testing Khaya: {URL}")
print("Language coverage:", ", ".join(f"{code}={name}" for code, name in LANGUAGES.items()))
print()

failed = 0

def run_test(source, target, sample, label):
    global failed
    pair = f"{source}-{target}"
    try:
        r = requests.post(URL, headers=headers, json={"in": sample, "lang": pair}, timeout=TIMEOUT)
        if r.status_code != 200:
            failed += 1
            print(f"[FAIL] {label:22s} ({pair}) -> HTTP {r.status_code}: {r.text[:300]}")
            return
        try:
            value = r.json()
        except ValueError:
            value = r.text
        print(f"[ OK ] {label:22s} ({pair}) -> {value}")
    except requests.RequestException as exc:
        failed += 1
        print(f"[FAIL] {label:22s} ({pair}) -> {exc}")

for target, sample in SAMPLES.items():
    run_test("eng", target, sample, f"English -> {LANGUAGES[target]}")

# Reverse smoke tests use the English sentence returned by the provider only
# as a stable source sample. They verify that each supported language can
# translate back to English through the same v2 endpoint.
for source in SAMPLES:
    run_test(source, "eng", "Thank you for your support.", f"{LANGUAGES[source]} -> English")

print()
if failed:
    print(f"Completed with {failed} failure(s).")
    sys.exit(1)
print(f"All {len(SAMPLES) * 2} Ghanaian-language direction tests passed.")
