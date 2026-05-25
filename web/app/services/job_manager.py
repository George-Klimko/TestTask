import asyncio
import itertools
import traceback
import uuid
from dataclasses import dataclass

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
        self._queues: dict[str, asyncio.Queue] = {}
        self._tasks: dict[str, asyncio.Task] = {}

        # pause only blocks NEW starts
        self._pause_gate: dict[str, asyncio.Event] = {}
        # stop = immediate cancel
        self._stop_flag: dict[str, asyncio.Event] = {}

    def queue(self, job_id: str) -> asyncio.Queue:
        return self._queues[job_id]

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    async def emit(self, job_id: str, msg: dict):
        await self._queues[job_id].put(msg)

    async def _log(self, job_id: str, line: str):
        await self.emit(job_id, {"type": "log_line", "payload": {"line": line}})

    async def start(
        self,
        accounts: list[str],
        proxies: list[str],
        threads: int = 10,
        headless: bool = True,
        timeout_sec: int = 45,
    ) -> str:
        job_id = str(uuid.uuid4())

        state = JobState(job_id=job_id, total=len(accounts))
        self._jobs[job_id] = state
        self._queues[job_id] = asyncio.Queue()
        self._pause_gate[job_id] = asyncio.Event()
        self._pause_gate[job_id].set()  # not paused
        self._stop_flag[job_id] = asyncio.Event()

        t = asyncio.create_task(
            self._run(job_id, accounts, proxies, threads, headless, timeout_sec)
        )
        self._tasks[job_id] = t
        return job_id

    async def pause(self, job_id: str):
        st = self._jobs.get(job_id)
        if not st:
            return
        st.status = "paused"
        self._pause_gate[job_id].clear()
        await self.emit(job_id, {"type": "job_paused", "payload": st.__dict__})
        await self._log(job_id, f"[manager] job_paused id={job_id}")

    async def resume(self, job_id: str):
        st = self._jobs.get(job_id)
        if not st:
            return
        st.status = "running"
        self._pause_gate[job_id].set()
        await self.emit(job_id, {"type": "job_resumed", "payload": st.__dict__})
        await self._log(job_id, f"[manager] job_resumed id={job_id}")

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
        await self._log(job_id, f"[manager] job_stop_requested id={job_id}")

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
        await self.emit(job_id, {"type": "job_started", "payload": st.__dict__})
        await self._log(
            job_id,
            f"[manager] job_started id={job_id} total={len(accounts)} "
            f"threads={threads} headless={headless} timeout_sec={timeout_sec} proxies={len(proxies)}"
        )

        sem = asyncio.Semaphore(threads)
        proxy_cycle = itertools.cycle(proxies) if proxies else iter([])

        async def handle(account_line: str):
            browser = None
            async with sem:
                await self._log(job_id, f"[worker] enter account={account_line}")

                # pause blocks only NEW task entry
                await self._pause_gate[job_id].wait()

                if self._stop_flag[job_id].is_set():
                    await self._log(job_id, f"[worker] stopped_before_start account={account_line}")
                    return

                try:
                    await self._log(job_id, f"[worker] parse_account account={account_line}")
                    acc = parse_account(account_line)

                    proxy_line = next(proxy_cycle, None)
                    await self._log(job_id, f"[worker] proxy_selected account={account_line} proxy={proxy_line}")
                    px = parse_proxy(proxy_line) if proxy_line else None

                    await self._log(job_id, f"[worker] start_browser account={account_line}")
                    browser = await start_browser(headless=headless)
                    await self._log(job_id, f"[worker] browser_started account={account_line}")

                    await self._log(job_id, f"[worker] ip_check_start account={account_line}")
                    result = await run_ip_check(
                        browser=browser,
                        account=acc,
                        proxy=px,
                        timeout_sec=timeout_sec,
                    )
                    await self._log(job_id, f"[worker] ip_check_done account={account_line}")

                    st.success += 1
                    await self.emit(job_id, {
                        "type": "result_row",
                        "payload": {
                            "account": account_line,
                            "stats": "ok",
                            "result": str(result),
                        },
                    })

                except asyncio.TimeoutError:
                    st.error += 1
                    await self._log(job_id, f"[worker][timeout] account={account_line} timeout_sec={timeout_sec}")
                except Exception as e:
                    st.error += 1
                    await self._log(job_id, f"[worker][error] account={account_line} err={e}")
                    await self._log(job_id, traceback.format_exc())
                finally:
                    await self._log(job_id, f"[worker] closing_browser account={account_line}")
                    await safe_close_browser(browser)

                    st.done += 1
                    st.progress_pct = int((st.done / max(st.total, 1)) * 100)
                    await self.emit(job_id, {
                        "type": "progress_update",
                        "payload": st.__dict__,
                    })
                    await self._log(
                        job_id,
                        f"[worker] done account={account_line} done={st.done}/{st.total} "
                        f"success={st.success} error={st.error} progress={st.progress_pct}%"
                    )

        try:
            await asyncio.gather(*(handle(a) for a in accounts))
            if st.status != "stopped":
                st.status = "done"
                await self._log(job_id, f"[manager] job_done id={job_id}")
        except asyncio.CancelledError:
            st.status = "stopped"
            await self._log(job_id, f"[manager] job_cancelled id={job_id}")
        except Exception:
            st.status = "error"
            await self._log(job_id, f"[manager] job_failed id={job_id}")
            await self._log(job_id, traceback.format_exc())
        finally:
            await self.emit(job_id, {"type": "job_finished", "payload": st.__dict__})
            await self._log(job_id, f"[manager] job_finished id={job_id} status={st.status}")


job_manager = JobManager()