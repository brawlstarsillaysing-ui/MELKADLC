import httpx

from telegram_bot.config import settings


class APIError(Exception):
    def __init__(self, code):
        self.code = code


class API:
    def __init__(self):
        self.http = httpx.AsyncClient(
            base_url=settings().api_base_url.rstrip("/"),
            timeout=30,
            headers={"Authorization": "Bearer " + settings().service_token.get_secret_value()},
        )

    async def call(self, method, path, data=None, params=None):
        try:
            response = await self.http.request(method, path, json=data, params=params)
        except httpx.HTTPError:
            raise APIError("connection") from None
        if not response.is_success:
            try:
                code = response.json().get("error", "invalid_input")
            except ValueError:
                code = "connection"
            raise APIError(code)
        return response.json()

    async def get(self, path, params=None):
        return await self.call("GET", path, params=params)

    async def post(self, path, data=None):
        return await self.call("POST", path, data)
