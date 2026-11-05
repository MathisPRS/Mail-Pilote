import httpx

from app.config import get_settings


async def send_gotify(
    url: str, token: str, title: str, message: str, priority: int, click_url: str | None = None
) -> None:
    """Envoie une notification Gotify ; lève en cas d'échec (le jeton n'est jamais journalisé)."""
    payload: dict = {"title": title, "message": message, "priority": priority}
    if click_url:
        origin = get_settings().public_origin.rstrip("/")
        payload["extras"] = {"client::notification": {"click": {"url": origin + click_url}}}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{url.rstrip('/')}/message", json=payload, headers={"X-Gotify-Key": token}
        )
        r.raise_for_status()
