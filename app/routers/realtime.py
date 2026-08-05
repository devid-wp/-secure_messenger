import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import Device, User


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Receive server-originated opaque events only.

    MLS envelopes are published through the authenticated HTTP endpoint and
    broadcast by the connection manager. Client-originated WebSocket frames are
    deliberately rejected so this channel cannot regain plaintext messages or
    delivery/read receipts.
    """
    protocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    bearer_protocol = next(
        (item.strip() for item in protocols if item.strip().startswith("bearer.")),
        None,
    )
    if bearer_protocol is None:
        await websocket.close(code=4001, reason="Missing token")
        return
    token = bearer_protocol.removeprefix("bearer.")
    session_store = websocket.app.state.session_store
    session_data = await session_store.resolve(token)
    if session_data is None:
        await websocket.close(code=4001, reason="Invalid token")
        return
    async with websocket.app.state.session_factory() as session:
        user = await session.get(User, session_data.user_id)
        device = await session.get(Device, session_data.device_id)
        if (
            user is None
            or not user.is_active
            or user.is_placeholder
            or device is None
            or device.status != "active"
            or device.revoked_at is not None
        ):
            await websocket.close(code=4001, reason="Invalid token")
            return

    manager = websocket.app.state.connection_manager
    await manager.connect(
        token,
        session_data.user_id,
        session_data.device_id,
        websocket,
        bearer_protocol,
    )
    try:
        while True:
            await websocket.receive_text()
            if await session_store.resolve(token) is None:
                await websocket.close(code=4003, reason="Session revoked")
                return
            await websocket.send_json(
                {
                    "type": "error",
                    "detail": "Client WebSocket events are disabled; publish opaque MLS envelopes",
                }
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(
            "Unexpected WebSocket error for user_id=%s", session_data.user_id
        )
