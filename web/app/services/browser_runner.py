from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.services.imap import connect_imap, find_emails
import nodriver as nd

import random
import string


def generate_password(length: int = 16) -> str:
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*"
    all_chars = lowercase + uppercase + digits + symbols
    password = [
        random.choice(lowercase),
        random.choice(uppercase),
        random.choice(digits),
        random.choice(symbols),
    ]
    password += random.choices(all_chars, k=length - 4)
    random.shuffle(password)
    return "".join(password)


@dataclass
class AccountCreds:
    raw: str
    login: str
    password: str


@dataclass
class ProxyCreds:
    raw: str
    proxy_url: str


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
        return ProxyCreds(raw=line, proxy_url=f"socks5://{host}:{port}")
    if len(p) == 4:
        host, port, user, pwd = p
        return ProxyCreds(raw=line, proxy_url=f"socks5://{user}:{pwd}@{host}:{port}")
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
            url="https://poshmark.com/user/password/reset",
            proxy_server=proxy.proxy_url,
        )
    return await browser.create_context(url="https://poshmark.com/user/password/reset")


async def run_ip_check(
    browser: Any,
    account: AccountCreds,
    proxy: ProxyCreds | None,
    timeout_sec: int = 45,
) -> dict[str, Any]:

    # =====================================
    # IMAP CHECK
    # =====================================

    imap_result = await asyncio.to_thread(
        connect_imap,
        account.login,
        account.password,
        proxy.raw if proxy else None,
    )

    if not imap_result["success"]:
        return {
            "status": "error",
            "stage": "imap",
            "account": account.login,
            "proxy": proxy.raw if proxy else None,
            "error": imap_result["error"],
            "message": imap_result["message"],
        }

    # =====================================
    # BROWSER
    # =====================================

    tab = None
    # ✅ результат формируем в переменной — return только после finally
    result: dict[str, Any] = {}

    try:
        tab = await create_context_with_proxy(browser, proxy)
        await tab.select('body')
        await asyncio.sleep(5)

        await inputHandler('#usernameEmail', account.login, tab)
        await asyncio.sleep(1)

        btn = await tab.select('button[data-et-name="reset_password"]')
        await btn.click()
        await asyncio.sleep(4)

        # ========= ПРОВЕРКА IP_BANNED =========

        try:
            el = await tab.select('h2.br--light-gray.br--bottom.p--b--4', timeout=10)
            if "Reset Password Email Sent" not in (await el.get_html()):
                raise ValueError("Unexpected h2 content")
        except Exception:
            result = {
                "status": "error",
                "stage": "browser",
                "account": account.login,
                "proxy": proxy.raw if proxy else None,
                "error": "IP_BANNED",
                "message": "Reset password confirmation not found — IP is likely banned",
            }
            # ✅ не делаем return здесь — выходим через finally
            raise _EarlyExit()

        # ========= IMAP — ИЩЕМ ПИСЬМО =========

        try:
            mail = imap_result["mail"]
            await asyncio.sleep(20)
            link = await asyncio.to_thread(
                find_emails, mail, ["poshmark", "Poshmark"], 10, 2
            )
            if not link:
                raise ValueError("no reset link found")
        except Exception as e:
            result = {
                "status": "error",
                "stage": "imap",
                "account": account.login,
                "proxy": proxy.raw if proxy else None,
                "error": "IMAP_EMAIL_NOT_FOUND",
                "message": f"Failed to find reset email: {e}",
            }
            raise _EarlyExit()

        # ========= СБРОС ПАРОЛЯ =========

        try:
            await tab.get(link)
            new_password = generate_password()

            await inputHandler('#newPassword', new_password, tab)
            await asyncio.sleep(1)
            await inputHandler('#confirmPassword', new_password, tab)
            await asyncio.sleep(1)

            checkbox = await tab.select('input[data-et-name="logout_all_sessions"]')
            await checkbox.click()
            await asyncio.sleep(1)

            reset_btn = await tab.select('button[data-et-name="reset_password"]')
            await reset_btn.click()
            await asyncio.sleep(5)

            # ✅ успех — формируем результат
            result = {
                "status": "ok",
                "stage": "done",
                "account": account.login,
                "email_password": account.password,
                "new_password": new_password,
                "proxy": proxy.raw if proxy else None,
            }

        except _EarlyExit:
            raise  # пробрасываем наверх
        except Exception as e:
            result = {
                "status": "error",
                "stage": "browser",
                "account": account.login,
                "proxy": proxy.raw if proxy else None,
                "error": "RESET_FAILED",
                "message": f"Password reset step failed: {e}",
            }

    except _EarlyExit:
        pass  # result уже заполнен выше

    except Exception as e:
        result = {
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

    return result


class _EarlyExit(Exception):
    """Внутреннее исключение для выхода из вложенных try без return."""
    pass


async def safe_close_browser(browser: Any) -> None:
    if not browser:
        return
    try:
        await browser.stop()
    except Exception:
        pass