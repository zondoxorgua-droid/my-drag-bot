import aiohttp
import re

# Xsolla Pay Station payment method IDs
PAYMENT_METHODS = {
    "razer_gold": 1553,
}

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

    async def generate_payment_link(self, item_id: str, user_id: str, platform: str, email: str, payment_method: str = "razer_gold") -> str:
        session_id = await self._get_session_id()
        api_url = (
            f"{self.BASE_URL}/api/v1/lots/{item_id}?" +
            f"userId={user_id}&project={platform}&email={email}&sessionId={session_id}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                response.raise_for_status()
                link = await response.text()

        # Append payment method ID to redirect directly to Razer Gold
        method_id = PAYMENT_METHODS.get(payment_method)
        if method_id and link.startswith("http"):
            separator = "&" if "?" in link else "?"
            link = f"{link}{separator}payment_method={method_id}"

        return link
