import aiohttp
import re

class VItemAPI:
    BASE_URL = "https://www.v-item.ru"

    async def _get_session_id(self) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.BASE_URL) as response:
                response.raise_for_status()
                html = await response.text()
                match = re.search(r'let sessionId = "([^"]+)"', html)
                if match:
                    return match.group(1)
                else:
                    raise ValueError("Session ID not found in HTML")

    async def generate_payment_link(self, item_id: str, user_id: str, platform: str) -> str:
        session_id = await self._get_session_id()
        api_url = (
            f"{self.BASE_URL}/api/v1/lots/{item_id}?" +
            f"userId={user_id}&project={platform}&email=test@test.com&sessionId={session_id}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                response.raise_for_status()
                return await response.text()
