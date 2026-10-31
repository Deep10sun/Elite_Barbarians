import os
import re
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["TAMU_API_KEY"]
ENDPOINT = os.getenv("TAMUS_AI_CHAT_API_ENDPOINT", "https://chat-api.tamu.ai")
MODEL = "protected.Claude Sonnet 4.6"   # or "protected.gemini-3.1-flash-lite"


def strip_think(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    return text.strip()


def _content_from_sse(body):
    """Fallback: rebuild text if the gateway streams anyway."""
    parts = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:") or line.endswith("[DONE]"):
            continue
        try:
            chunk = json.loads(line[5:].strip())
            delta = chunk["choices"][0].get("delta", {})
            if delta.get("content"):
                parts.append(delta["content"])
        except Exception:
            continue
    return "".join(parts)


def call_model(prompt, system=None, model=None, temperature=None,
               max_tokens=4000, nonce=None):
    # The gateway caches identical requests; nonce makes repeat calls distinct.
    if nonce is not None:
        system = f"{system or ''}\n[request {nonce}]".strip()
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]

    payload = {
        "model": model or MODEL, "stream": False,
        "max_tokens": max_tokens, "messages": messages
    }

    if temperature is not None:
        payload["temperature"] = temperature

    r = requests.post(
        f"{ENDPOINT}/api/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=120,
    )

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:800]}")

    try:
        text = r.json()["choices"][0]["message"]["content"]
    except Exception:
        text = _content_from_sse(r.text)
        if not text:
            raise RuntimeError(f"Unexpected response: {r.text[:800]}")
    return strip_think(text)


def extract_json(text):
    text = strip_think(text)
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if starts:
        text = text[min(starts):]
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
        return value
    except ValueError as e:
        raise ValueError(f"no parseable JSON ({e}); starts with {text[:60]!r}")