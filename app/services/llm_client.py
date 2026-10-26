import base64
import mimetypes
import os
from contextlib import ExitStack

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
IMAGES_EDIT_URL = "https://api.openai.com/v1/images/edits"


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
def chat_completion(messages, model="gpt-4o", max_tokens=500, json_mode=False, temperature=0.2):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


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
def get_embedding(text: str, model="text-embedding-3-small") -> list[float]:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": text}

    response = requests.post(EMBEDDINGS_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


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
def image_edit(image_paths: list[str], prompt: str, size: str = "1024x1024") -> bytes:
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    data = {"model": "gpt-image-1-mini", "prompt": prompt, "size": size, "n": 1}

    with ExitStack() as stack:
        files = []
        for path in image_paths:
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            fh = stack.enter_context(open(path, "rb"))
            files.append(("image[]", (os.path.basename(path), fh, mime)))

        response = requests.post(IMAGES_EDIT_URL, headers=headers, data=data, files=files, timeout=120)

    response.raise_for_status()
    b64_data = response.json()["data"][0]["b64_json"]
    return base64.b64decode(b64_data)


def image_to_data_url(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lstrip(".").lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{b64}"
