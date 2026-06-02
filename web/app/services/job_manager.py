import asyncio
import itertools
import traceback
import uuid
from dataclasses import dataclass
from app.services.email_pool import email_pool
from app.services.browser_runner import (
    parse_account,
    parse_proxy,
    run_ip_check,
    safe_close_browser,
    start_browser,
)


@dataclass
class JobState:
    job_id: str
    status: str = "running"
    total: int = 0
    done: int = 0
    success: int = 0
    error: int = 0
    progress_pct: int = 0


class JobManager:
    def __init__(self):
        self._jobs: dict[str, JobState] = {}

        # MULTI WS
        self._queues: dict[str, list[asyncio.Queue]] = {}

        self._tasks: dict[str, asyncio.Task] = {}
        self._pause_gate: dict[str, asyncio.Event] = {}
        self._stop_flag: dict[str, asyncio.Event] = {}

        # LOG HISTORY
        self._history: dict[str, list[dict]] = {}

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def create_listener(self, job_id: str) -> asyncio.Queue:
        q = asyncio.Queue()

        if job_id not in self._queues:
            self._queues[job_id] = []

        self._queues[job_id].append(q)

        return q
    def remove_listener(self, job_id: str, queue: asyncio.Queue) -> None:
        listeners = self._queues.get(job_id, [])
        try:
            listeners.remove(queue)
        except ValueError:
            pass

    async def replay(self, job_id: str, queue: asyncio.Queue):
        for msg in self._history.get(job_id, []):
            await queue.put(msg)

    async def emit(self, job_id: str, msg: dict):
        print("EMIT:", job_id, msg)
        self._history.setdefault(job_id, []).append(msg)

        for q in self._queues.get(job_id, []):
            await q.put(msg)

    async def _log(self, job_id: str, line: str):
        print(line)

        await self.emit(job_id, {
            "type": "log_line",
            "payload": {
                "line": line
            }
        })

    async def start(
        self,
        accounts: list[str],
        proxies: list[str],
        threads: int = 10,
        headless: bool = True,
        timeout_sec: int = 45,
    ) -> str:
        job_id = str(uuid.uuid4())

        state = JobState(
            job_id=job_id,
            total=len(accounts)
        )

        self._jobs[job_id] = state
        self._pause_gate[job_id] = asyncio.Event()
        self._pause_gate[job_id].set()

        self._stop_flag[job_id] = asyncio.Event()

        self._history[job_id] = []

        t = asyncio.create_task(
            self._run(
                job_id,
                accounts,
                proxies,
                threads,
                headless,
                timeout_sec
            )
        )

        self._tasks[job_id] = t

        return job_id

    async def pause(self, job_id: str):
        st = self._jobs.get(job_id)

        if not st:
            return

        st.status = "paused"

        self._pause_gate[job_id].clear()

        await self.emit(job_id, {
            "type": "job_paused",
            "payload": st.__dict__
        })

        await self._log(
            job_id,
            f"[manager] job_paused id={job_id}"
        )

    async def resume(self, job_id: str):
        st = self._jobs.get(job_id)

        if not st:
            return

        st.status = "running"

        self._pause_gate[job_id].set()

        await self.emit(job_id, {
            "type": "job_resumed",
            "payload": st.__dict__
        })

        await self._log(
            job_id,
            f"[manager] job_resumed id={job_id}"
        )

    async def stop(self, job_id: str):
        st = self._jobs.get(job_id)

        if not st:
            return

        st.status = "stopped"

        self._stop_flag[job_id].set()
        self._pause_gate[job_id].set()

        task = self._tasks.get(job_id)

        if task:
            task.cancel()

        await self._log(
            job_id,
            f"[manager] job_stop_requested id={job_id}"
        )

    async def _run(
        self,
        job_id: str,
        accounts: list[str],
        proxies: list[str],
        threads: int,
        headless: bool,
        timeout_sec: int,
    ):
        st = self._jobs[job_id]

        await self.emit(job_id, {
            "type": "job_started",
            "payload": st.__dict__
        })

        await self._log(
            job_id,
            f"[manager] job_started id={job_id} total={len(accounts)} "
            f"threads={threads} headless={headless} "
            f"timeout_sec={timeout_sec} proxies={len(proxies)}"
        )

        sem = asyncio.Semaphore(threads)

        proxy_cycle = (
            itertools.cycle(proxies)
            if proxies
            else iter([])
        )

        browser = None

        async def handle(account_line: str):
            proxy_line = None

            async with sem:
                await self._log(
                    job_id,
                    f"[worker] enter account={account_line}"
                )

                await self._pause_gate[job_id].wait()

                if self._stop_flag[job_id].is_set():
                    return

                try:
                    acc = parse_account(account_line)

                    proxy_line = next(proxy_cycle, None)

                    px = (
                        parse_proxy(proxy_line)
                        if proxy_line
                        else None
                    )

                    result = await run_ip_check(
                        browser=browser,
                        account=acc,
                        proxy=px,
                        email_pool=email_pool,
                        timeout_sec=timeout_sec,
                    )



                    if result.get("status") == "ok":
                        st.success += 1
                    else:
                        st.error += 1

                    await self.emit(job_id, {
                        "type": "result_row",
                        "payload": result
                    })

                except asyncio.TimeoutError:
                    st.error += 1

                    await self.emit(job_id, {
                        "type": "result_row",
                        "payload": {
                            "status": "error",
                            "stage": "browser",
                            "account": account_line,
                            "proxy": proxy_line,
                            "error": "TIMEOUT",
                            "message": (
                                f"Скрипт завис "
                                f"или прокси не ответил "
                                f"за {timeout_sec} сек"
                            )
                        }
                    })

                except Exception as e:
                    st.error += 1

                    await self._log(
                        job_id,
                        traceback.format_exc()
                    )

                    await self.emit(job_id, {
                        "type": "result_row",
                        "payload": {
                            "status": "error",
                            "stage": "system",
                            "account": account_line,
                            "proxy": proxy_line,
                            "error": "CRITICAL_ERROR",
                            "message": str(e)
                        }
                    })

                finally:
                    st.done += 1

                    st.progress_pct = int(
                        (st.done / max(st.total, 1)) * 100
                    )

                    await self.emit(job_id, {
                        "type": "progress_update",
                        "payload": st.__dict__
                    })

        try:
            await self._log(
                job_id,
                "[manager] starting_shared_browser"
            )

            browser = await start_browser(
                headless=headless
            )

            await self._log(
                job_id,
                "[manager] shared_browser_started"
            )

            await asyncio.gather(
                *(handle(a) for a in accounts)
            )

            if st.status != "stopped":
                st.status = "done"

                await self._log(
                    job_id,
                    f"[manager] job_done id={job_id}"
                )

        except asyncio.CancelledError:
            st.status = "stopped"

            await self._log(
                job_id,
                f"[manager] job_cancelled id={job_id}"
            )

        except Exception:
            st.status = "error"

            await self._log(
                job_id,
                f"[manager] job_failed id={job_id}"
            )

            await self._log(
                job_id,
                traceback.format_exc()
            )

        finally:
            await self._log(
                job_id,
                "[manager] closing_shared_browser"
            )

            await safe_close_browser(browser)

            await self._log(
                job_id,
                "[manager] shared_browser_closed"
            )

            await self.emit(job_id, {
                "type": "job_finished",
                "payload": st.__dict__
            })

            await self._log(
                job_id,
                f"[manager] job_finished "
                f"id={job_id} status={st.status}"
            )


job_manager = JobManager()