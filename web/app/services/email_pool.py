import asyncio
from dataclasses import dataclass


@dataclass
class EmailCreds:
    raw: str
    login: str
    password: str


class EmailPool:
    def __init__(self):
        self._queue: asyncio.Queue[EmailCreds] = asyncio.Queue()
        self._used: set[str] = set()
        self._lock = asyncio.Lock()

    def load(self, lines: list[str]) -> int:
        """Загружает почты в пул. Возвращает кол-во валидных."""
        # очищаем старый пул
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._used.clear()

        count = 0
        for line in lines:
            parts = line.strip().split(":", 1)
            if len(parts) != 2:
                continue
            creds = EmailCreds(raw=line.strip(), login=parts[0], password=parts[1])
            self._queue.put_nowait(creds)
            count += 1
        return count

    async def acquire(self, timeout: float = 5.0) -> EmailCreds | None:
        """Берёт почту из пула. Возвращает None если пул пуст."""
        try:
            creds = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            async with self._lock:
                self._used.add(creds.login)
            return creds
        except asyncio.TimeoutError:
            return None

    async def release(self, creds: EmailCreds) -> None:
        """Вернуть email обратно в пул (если не использован до конца)."""
        async with self._lock:
            self._used.discard(creds.login)

        await self._queue.put(creds)

    def consume(self, creds: EmailCreds) -> None:
        """Помечает почту как использованную — в пул не вернётся."""
        # уже убрана из очереди при acquire, просто оставляем в _used
        pass

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def used_count(self) -> int:
        return len(self._used)


email_pool = EmailPool()