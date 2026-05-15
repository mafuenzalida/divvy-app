"""Process-wide mutable state (dev live reload)."""

from fastapi import WebSocket

live_reload_clients: list[WebSocket] = []
