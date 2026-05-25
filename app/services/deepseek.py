import json
import logging
import httpx
from typing import AsyncGenerator
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DeepSeekClient:
    def __init__(self):
        self.base_url = settings.deepseek_base_url
        self.model = settings.deepseek_model
        self.is_reasoner = "reasoner" in self.model
        self.headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        if self.is_reasoner:
            logger.info(f"DeepSeek: используется модель {self.model} (reasoning mode)")

    def _prepare_messages(self, messages: list[dict]) -> list[dict]:
        """Для R1: конвертирует system→user, т.к. R1 не поддерживает system role."""
        if not self.is_reasoner:
            return messages
        system_text = ""
        result = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                if system_text and msg["role"] == "user":
                    content = msg["content"]
                    if isinstance(content, str):
                        content = f"{system_text}\n\n{content}"
                    elif isinstance(content, list):
                        # Multimodal: вставляем system текст первым элементом
                        content = [{"type": "text", "text": system_text}] + content
                    msg = {**msg, "content": content}
                    system_text = ""
                result.append(msg)
        return result

    def _fix_temperature(self, temperature: float) -> float:
        """R1 не поддерживает произвольную temperature — игнорируем параметр."""
        if self.is_reasoner:
            return 1.0
        return temperature

    async def chat(self, messages: list[dict], max_tokens: int = 8192, temperature: float = 0.3, retries: int = 2) -> dict:
        messages = self._prepare_messages(messages)
        temperature = self._fix_temperature(temperature)
        last_error = None
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=900.0) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json={"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
                    )
                    if resp.status_code != 200:
                        error_body = resp.text[:500]
                        logger.error(f"DeepSeek API {resp.status_code}: {error_body}")
                        # Attach body to exception for upstream diagnostics
                        e = httpx.HTTPStatusError(
                            f"DeepSeek {resp.status_code}: {error_body}",
                            request=resp.request, response=resp
                        )
                        raise e
                    resp.raise_for_status()
                    data = resp.json()
                    # Validate response structure
                    choices = data.get("choices")
                    if not choices or not isinstance(choices, list) or len(choices) == 0:
                        raise ValueError(f"DeepSeek returned empty choices: {data}")
                    message = choices[0].get("message")
                    if not message:
                        raise ValueError(f"DeepSeek returned no message: {choices[0]}")
                    # R1 (reasoner) returns answer in reasoning_content, V3 in content
                    text = message.get("content") or ""
                    if not text and "reasoning_content" in message:
                        text = message["reasoning_content"]
                    if not text:
                        raise ValueError(f"DeepSeek returned empty content: {choices[0]}")
                    return {"content": text, "usage": data.get("usage", {})}
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s
                    continue
                raise
        raise last_error  # unreachable but type-safe

    async def chat_stream(self, messages: list[dict], max_tokens: int = 4096, temperature: float = 0.7, connect_retries: int = 1) -> AsyncGenerator[str, None]:
        """SSE stream with retry ONLY on connection errors.
        Once streaming begins, errors propagate immediately — never retry mid-stream
        as that would duplicate content for the user."""
        messages = self._prepare_messages(messages)
        temperature = self._fix_temperature(temperature)
        request_json = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": True}
        timeout = httpx.Timeout(connect=10.0, read=900.0, write=10.0, pool=10.0)

        last_error = None
        for attempt in range(connect_retries + 1):
            try:
                # Phase 1: CONNECT (retryable)
                client = httpx.AsyncClient(timeout=timeout)
                req = client.build_request(
                    "POST", f"{self.base_url}/chat/completions",
                    headers=self.headers, json=request_json,
                )
                resp = await client.send(req, stream=True)
                resp.raise_for_status()
                break  # connected — stop retrying
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                try:
                    await client.aclose()
                except Exception:
                    pass
                if attempt < connect_retries:
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                raise
            except httpx.HTTPStatusError:
                # Non-retryable HTTP errors (4xx, 5xx)
                await resp.aclose()
                await client.aclose()
                raise

        # Phase 2: STREAM (never retry — would duplicate content)
        try:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        finally:
            await resp.aclose()
            await client.aclose()

    async def chat_with_images(self, system_prompt: str, image_urls: list[str], user_text: str = "", **kwargs) -> dict:
        content_parts = [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
        if user_text:
            content_parts.append({"type": "text", "text": user_text})
        # system prompt идёт как system message — _prepare_messages() сконвертирует для R1
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content_parts}]
        return await self.chat(messages, **kwargs)


deepseek = DeepSeekClient()
