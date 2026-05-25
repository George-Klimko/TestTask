import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import jobs, upload, ws

app = FastAPI(title='Automation Panel Backend')

# Динамически определяем путь к папке web
# __file__ — это путь к main.py
# .parent — это папка app
# .parent.parent — это папка web
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(ws.router)

# Проверка для дебага: выведет в консоль, где именно мы ищем папку
if not FRONTEND_DIR.exists():
    print(f"❌ ERROR: Frontend directory not found at {FRONTEND_DIR}")
else:
    print(f"✅ Success: Static files served from {FRONTEND_DIR}")
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")