import asyncio
import json

from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from app.services.job_manager import job_manager

router = APIRouter(tags=['ws'])


@router.websocket('/ws/jobs/{job_id}')
async def ws_events(
    websocket: WebSocket,
    job_id: str
) -> None:

    # ✅ сначала accept, потом close — иначе краш
    if not job_manager.get(job_id):
        await websocket.accept()
        await websocket.close(code=4004)
        return

    await websocket.accept()

    queue = job_manager.create_listener(job_id)

    # ✅ replay — догоняем сообщения которые уже были до коннекта
    await job_manager.replay(job_id, queue)

    try:
        while True:
            try:
                msg = await asyncio.wait_for(
                    queue.get(),
                    timeout=20
                )

                await websocket.send_text(
                    json.dumps(msg)
                )

                if msg.get('type') == 'job_finished':
                    break

            except asyncio.TimeoutError:
                await websocket.send_text(
                    json.dumps({'type': 'ping'})
                )

    except WebSocketDisconnect:
        pass

    finally:
        # ✅ всегда чистим очередь — нет утечки памяти
        job_manager.remove_listener(job_id, queue)