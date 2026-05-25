import sqlite3
import imaplib
import email
from email.header import decode_header

DB_PATH = "/home/raw/prosch/web/app/imapdatabase.db"

def get_imap(email: str) -> dict | None:
    email = email.strip().lower()
    if "@" not in email:
        return {"error": "Некорректный email"}
    domain = email.split("@")[-1]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for table in '0123456789ABCDEF':
        cursor.execute(
            f'SELECT Server, Port, Socket FROM "{table}" '
            f'WHERE Server = ? OR Server LIKE ? LIMIT 1',
            (domain, f'%.{domain}')
        )
        row = cursor.fetchone()
        if row:
            server, port, socket = row
            conn.close()
            return {"domain": domain, "imap": server.strip().rstrip("."), "imap_port": port, "ssl": socket == 0}
    for table in '0123456789ABCDEF':
        cursor.execute(
            f'SELECT Server, Port, Socket FROM "{table}" '
            f'WHERE Server LIKE ? LIMIT 1',
            (f'%{domain}%',)
        )
        row = cursor.fetchone()
        if row:
            server, port, socket = row
            conn.close()
            return {"domain": domain, "imap": server.strip().rstrip("."), "imap_port": port, "ssl": socket == 0}
    conn.close()
    return None


def connect_imap(email: str, password: str):
    settings = get_imap(email)
    if not settings:
        print(f"❌ Настройки IMAP для {email} не найдены в базе")
        return None
    print(f"📡 Подключаемся к {settings['imap']}:{settings['imap_port']} (SSL: {settings['ssl']})")
    try:
        if settings["ssl"]:
            mail = imaplib.IMAP4_SSL(settings["imap"], settings["imap_port"])
        else:
            mail = imaplib.IMAP4(settings["imap"], settings["imap_port"])
        mail.login(email, password)
        print(f"✅ Успешно подключились как {email}")
        return mail
    except imaplib.IMAP4.error as e:
        print(f"❌ Ошибка авторизации: {e}")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
    return None


def find_latest_from(mail, sender_keyword: str):
    """Ищет последнее письмо от отправителя по всем папкам"""
    status, folder_list = mail.list()

    all_found = []

    for f in folder_list:
        # парсим имя папки
        folder_name = f.decode().split('"/"')[-1].strip().strip('"').strip()

        try:
            res, _ = mail.select(f'"{folder_name}"', readonly=True)
            if res != "OK":
                continue
            status, data = mail.search(None, f'FROM "{sender_keyword}"')
            ids = data[0].split()
            if ids:
                print(f"  📂 '{folder_name}': {len(ids)} писем")
                all_found.append((folder_name, ids[-1]))
        except:
            continue

    if not all_found:
        print(f"❌ Писем от '{sender_keyword}' не найдено ни в одной папке")
        return

    # Берём последнее найденное
    folder_name, latest_id = all_found[-1]
    mail.select(f'"{folder_name}"', readonly=True)
    status, msg_data = mail.fetch(latest_id, "(RFC822)")
    msg = email.message_from_bytes(msg_data[0][1])

    # Декодируем тему
    subject, enc = decode_header(msg["Subject"])[0]
    if isinstance(subject, bytes):
        subject = subject.decode(enc or "utf-8", errors="ignore")

    # Тело
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                break
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

    print(f"\n📧 От:   {msg['From']}")
    print(f"📅 Дата: {msg['Date']}")
    print(f"📝 Тема: {subject}")
    print(f"{'─'*50}")
    print(body[:1000])


if __name__ == "__main__":
    EMAIL    = "agg.mastrangeli@libero.it"
    PASSWORD = "Antonio1971+"

    mail = connect_imap(EMAIL, PASSWORD)
    if mail:
        print("\n🔍 Ищем письма от Poshmark...\n")
        find_latest_from(mail, "poshmark")
        mail.logout()