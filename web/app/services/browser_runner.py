#browser_runner.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import random
from typing import Any

import nodriver as nd 


@dataclass
class AccountCreds:
    raw: str
    login: str
    password: str


@dataclass
class ProxyCreds:
    raw: str
    proxy_url: str  # http://... or socks5://...


def parse_account(line: str) -> AccountCreds:
    # format: mail:pass
    parts = [p.strip() for p in line.split(":")]
    if len(parts) != 2:
        raise ValueError(f"Invalid account format: {line}")
    return AccountCreds(raw=line, login=parts[0], password=parts[1])


def parse_proxy(line: str) -> ProxyCreds:
    raw = line.strip()

    # already full URL: socks5://user:pass@host:port
    if "://" in raw:
        return ProxyCreds(raw=line, proxy_url=raw)

    # ip:port
    p = raw.split(":")
    if len(p) == 2:
        host, port = p
        return ProxyCreds(raw=line, proxy_url=f"http://{host}:{port}")

    # ip:port:user:pass
    if len(p) == 4:
        host, port, user, pwd = p
        return ProxyCreds(raw=line, proxy_url=f"http://{user}:{pwd}@{host}:{port}")

    raise ValueError(f"Invalid proxy format: {line}")

async def inputHandler(selector: str, text: str, tab: Any):
    input_el = await tab.select(selector)
    await input_el.clear_input()
    await input_el.click()
    await input_el.send_keys(text)

    

async def start_browser(headless: bool = False) -> Any:
    return await nd.start(headless=headless)


async def create_context_with_proxy(browser: Any, proxy: ProxyCreds | None) -> Any:
    if proxy:
        return await browser.create_context(
            url="https://poshmark.com",
            proxy_server=proxy.proxy_url,
            

        )
    return await browser.create_context(url="https://poshmark.com/user/password/reset" )


async def run_ip_check(
    browser: Any,
    account: AccountCreds,
    proxy: ProxyCreds | None,
    timeout_sec: int = 45,
) -> dict[str, Any]:
    try:
        tab = await create_context_with_proxy(browser, proxy)
        await asyncio.sleep(4)
        

        await inputHandler('#usernameEmail', account.login, tab)
        await asyncio.sleep(1)
        btn = await tab.select('button[data-et-name="reset_password"]')
        await btn.click()  
        
        await asyncio.sleep(10000)
    except Exception as e:
        raise RuntimeError("Failed to create browser context with proxy") from e
    
    return {
        "status": "ok",
        "account": account.login,
        "proxy": proxy.raw if proxy else None,
        "result": "browser_started_and_ip_checked",
    }


async def safe_close_browser(browser: Any) -> None:
    if not browser:
        return
    try:
        await browser.stop()
    except Exception:
        pass
