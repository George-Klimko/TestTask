from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.services.imap import connect_imap
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
    parts = [p.strip() for p in line.split(":")]
    if len(parts) != 2:
        raise ValueError(f"Invalid account format: {line}")
    return AccountCreds(raw=line, login=parts[0], password=parts[1])


def parse_proxy(line: str) -> ProxyCreds:
    raw = line.strip()

    if "://" in raw:
        return ProxyCreds(raw=line, proxy_url=raw)

    p = raw.split(":")
    if len(p) == 2:
        host, port = p
        return ProxyCreds(raw=line, proxy_url=f"http://{host}:{port}")

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
    return await browser.create_context(url="https://poshmark.com/user/password/reset")


async def run_ip_check(
    browser: Any,
    account: AccountCreds,
    proxy: ProxyCreds | None,
    timeout_sec: int = 45,
) -> dict[str, Any]:

    proxy_url = proxy.proxy_url if proxy else None

    # =====================================
    # IMAP CHECK
    # =====================================

    imap_result = await asyncio.to_thread(
        connect_imap,
        account.login,
        account.password,
        proxy_url
    )

    # ========= IMAP FAILED =========

    if not imap_result["success"]:
        return {
            "status": "error",
            "stage": "imap",

            "account": account.login,
            "proxy": proxy.raw if proxy else None,

            "error": imap_result["error"],
            "message": imap_result["message"],
        }

    # ========= CLOSE IMAP =========

    try:
        imap_result["mail"].logout()
    except Exception:
        pass

    # =====================================
    # START BROWSER
    # =====================================

    tab = None

    try:

        tab = await create_context_with_proxy(browser, proxy)

        await tab.select('body')
        await asyncio.sleep(2)
        await inputHandler(
            '#usernameEmail',
            account.login,
            tab
        )

        await asyncio.sleep(1)

        btn = await tab.select('button[data-et-name="reset_password"]')
        await btn.click()
        await asyncio.sleep(2)
        # ========= WAIT FOR SUCCESS ELEMENT =========

        try:
            el = await tab.select('h2.br--light-gray.br--bottom.p--b--4', timeout=10)
            if "Reset Password Email Sent" not in (await el.get_html()):
                raise ValueError("Unexpected h2 content")

        except Exception:
            return {
                "status": "error",
                "stage": "browser",

                "account": account.login,
                "proxy": proxy.raw if proxy else None,

                "error": "IP_BANNED",
                "message": "Reset password confirmation not found — IP is likely banned",
            }

    except Exception as e:
        return {
            "status": "error",
            "stage": "browser",

            "account": account.login,
            "proxy": proxy.raw if proxy else None,

            "error": "BROWSER_ERROR",
            "message": str(e),
        }

    finally:
        if tab is not None:
            try:
                await tab.close()
            except Exception:
                pass

    return {
        "status": "ok",
        "stage": "done",

        "account": account.login,
        "proxy": proxy.raw if proxy else None,
    }


async def safe_close_browser(browser: Any) -> None:
    if not browser:
        return
    try:
        await browser.stop()
    except Exception:
        pass