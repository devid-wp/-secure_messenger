import asyncio
import unittest

from app.services.realtime import ConnectionManager


class DisconnectedWebSocket:
    async def accept(self, subprotocol=None):
        return None

    async def close(self, code, reason):
        raise RuntimeError("client already disconnected")


class RealtimeRevocationTests(unittest.TestCase):
    def test_revocation_ignores_stale_transport_and_removes_connection(self):
        async def scenario():
            manager = ConnectionManager()
            socket = DisconnectedWebSocket()
            await manager.connect("session-token", 1, "lost-device", socket)

            await manager.close_device("lost-device")

            self.assertNotIn("session-token", manager._connections)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
