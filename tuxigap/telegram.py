from .i18n import tr
from .presentation import decorate_keyboard, plain_presentation
import asyncio
import httpx


class APIError(Exception):
    def __init__(self, method, code, description):
        super().__init__(f"{method}: {code}: {description}")
        self.method, self.code, self.description = method, code, description


class Telegram:
    def __init__(self, token, base="https://api.telegram.org", client=None, test_mode=False):
        self.url = f"{base}/bot{token}/" + ("test/" if test_mode else "")
        self.file_url = f"{base}/file/bot{token}/" + ("test/" if test_mode else "")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(40, connect=10))

    async def call(self, method, **data):
        if isinstance(data.get("reply_markup"), dict):
            data["reply_markup"] = decorate_keyboard(data["reply_markup"])
        # Do not log request URLs: Telegram embeds the token in the path.
        for attempt in range(3):
            response = await self.client.post(self.url + method, json=data)
            try:
                body = response.json()
            except ValueError:
                raise APIError(method, response.status_code, "Non-JSON Telegram response") from None
            if body.get("ok"):
                return body["result"]
            if body.get("error_code") == 400 and attempt < 2:
                description = body.get("description", "").lower()
                plain = plain_presentation(data)
                if plain != data and any(word in description for word in ("emoji", "style", "button")):
                    data = plain
                    continue
            if body.get("error_code") == 429 and attempt < 2:
                delay = body.get("parameters", {}).get("retry_after", 1)
                if delay > 30:
                    raise APIError(method, 429, "Rate limit; retry in worker")
                await asyncio.sleep(max(1, delay))
                continue
            raise APIError(
                method, body.get("error_code", response.status_code), body.get("description", "API failure")
            )
        raise APIError(method, 429, "Retries exhausted")

    async def send(self, chat, text, keyboard=None, **extra):
        data = dict(
            chat_id=chat, text=str(text), parse_mode="HTML", link_preview_options={"is_disabled": True}
        )
        if keyboard is not None:
            data["reply_markup"] = {"inline_keyboard": keyboard}
        return await self.call("sendMessage", **data, **extra)

    async def document(self, chat, filename, content):
        response = await self.client.post(
            self.url + "sendDocument",
            data={"chat_id": str(chat)},
            files={"document": (filename, content, "text/csv")},
        )
        body = response.json()
        if not body.get("ok"):
            raise APIError("sendDocument", response.status_code, body.get("description", "Upload failed"))
        return body["result"]

    async def close(self):
        await self.client.aclose()

    async def photo_bytes(self, file_id, limit=2 * 1024 * 1024):
        info = await self.call("getFile", file_id=file_id)
        path = info.get("file_path", "")
        if (
            not path
            or path.startswith("/")
            or ".." in path
            or ":" in path
            or info.get("file_size", 0) > limit
        ):
            raise ValueError(tr("m_53ac47e174d3"))
        data = bytearray()
        async with self.client.stream("GET", self.file_url + path) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError(tr("m_53ac47e174d3"))
        return bytes(data)
