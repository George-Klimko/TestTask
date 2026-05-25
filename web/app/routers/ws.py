import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.job_manager import job_manager

router = APIRouter(tags=['ws'])


@router.websocket('/ws/jobs/{job_id}')
async def ws_events(websocket: WebSocket, job_id: str) -> None:
    if not job_manager.get(job_id):
        await websocket.close(code=4004)
        return
    await websocket.accept()
    queue = job_manager.queue(job_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_text(json.dumps(msg))
                if msg.get('type') == 'job_finished':
                    break
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({'type': 'ping'}))
    except WebSocketDisconnect:
        return