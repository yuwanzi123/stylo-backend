import base64
import os

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        requests.exceptions.SSLError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
    )),
    reraise=True,
)
def chat_completion(messages, model="gpt-4o", max_tokens=500, json_mode=False):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def image_to_data_url(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lstrip(".").lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{b64}"
