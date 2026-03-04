from __future__ import annotations
import httpx, json

class TelegramClient:
    def __init__(self, bot_token: str): self.bot_token = bot_token.strip()
    def _url(self, method: str) -> str: return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    async def send_message(self, chat_id: int, text: str, parse_mode: str = None, reply_markup: dict = None, disable_web_page_preview: bool = True):
        body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_web_page_preview}
        if parse_mode: body["parse_mode"] = parse_mode
        if reply_markup: body["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=30.0) as c: return (await c.post(self._url("sendMessage"), json=body)).json().get("result", {})

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, parse_mode: str = None, reply_markup: dict = None, disable_web_page_preview: bool = True):
        body = {"chat_id": chat_id, "message_id": message_id, "text": text, "disable_web_page_preview": disable_web_page_preview}
        if parse_mode: body["parse_mode"] = parse_mode
        if reply_markup is not None: body["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(self._url("editMessageText"), json=body)
            data = r.json()
            if not data.get("ok"):
                if "message is not modified" in str(data.get("description", "")).lower(): return {}
                raise RuntimeError(data.get("description", r.text))
            return data.get("result", {})

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, reply_markup: dict = None):
        body = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None: body["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=30.0) as c: return (await c.post(self._url("editMessageReplyMarkup"), json=body)).json().get("result", {})

    async def answer_callback_query(self, cb_id: str, text: str = "", show_alert: bool = False):
        async with httpx.AsyncClient(timeout=20.0) as c: await c.post(self._url("answerCallbackQuery"), json={"callback_query_id": cb_id, "text": text, "show_alert": show_alert})

    async def get_updates(self, offset: int, timeout_s: int = 30):
        async with httpx.AsyncClient(timeout=timeout_s + 5) as c: return (await c.get(self._url("getUpdates"), params={"offset": offset, "timeout": timeout_s})).json().get("result", [])

    async def get_file(self, file_id: str):
        async with httpx.AsyncClient() as c: return (await c.get(self._url("getFile"), params={"file_id": file_id})).json().get("result", {})

    async def download_file_bytes(self, file_path: str):
        async with httpx.AsyncClient(timeout=60.0) as c: return (await c.get(f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}")).content
            
    async def send_photo(self, chat_id: int, photo_bytes: bytes, filename="photo.png", caption="", parse_mode="HTML", reply_markup=None):
        data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": parse_mode}
        if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
        async with httpx.AsyncClient(timeout=60.0) as c: return (await c.post(self._url("sendPhoto"), data=data, files={"photo": (filename, photo_bytes, "image/png")})).json().get("result", {})
    
    async def send_document(self, chat_id: int, doc_bytes: bytes, filename: str, caption: str = "", parse_mode: str = "HTML", reply_markup: dict = None):
        data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": parse_mode}
        if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
        mime = "application/pdf" if str(filename).lower().endswith(".pdf") else "application/octet-stream"
        async with httpx.AsyncClient(timeout=60.0) as c: return (await c.post(self._url("sendDocument"), data=data, files={"document": (filename, doc_bytes, mime)})).json().get("result", {})

    async def delete_message(self, chat_id: int, message_id: int):
        async with httpx.AsyncClient(timeout=10.0) as c: await c.get(self._url("deleteMessage"), params={"chat_id": chat_id, "message_id": message_id})

    async def set_my_commands(self, commands: list[dict], scope: dict | None = None, language_code: str | None = None):
        body = {"commands": commands}
        if scope:
            body["scope"] = scope
        if language_code:
            body["language_code"] = language_code
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(self._url("setMyCommands"), json=body)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", r.text))
            return data.get("result", False)
