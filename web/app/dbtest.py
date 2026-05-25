import sqlite3
import imaplib
DB_PATH = "/home/raw/prosch/web/app/imapdatabase.db"

def get_imap(email: str) -> dict | None:
    email = email.strip().lower()
    if "@" not in email:
        return {"error": "Некорректный email"}

    domain = email.split("@")[-1]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Точный поиск: imap.san.rr.com или san.rr.com
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
            return {"domain": domain, "imap": server, "imap_port": port, "ssl": socket == 0, "source": "exact"}

    # 2. Широкий поиск: всё что содержит домен
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
            return {"domain": domain, "imap": server, "imap_port": port, "ssl": socket == 0, "source": "broad"}

    conn.close()
    return None


def connect_imap(email: str, password: str):
    """
    Подключается к IMAP почте по email и паролю.
    Возвращает объект соединения или None если не удалось.
    """
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

        # Список папок
        status, folders = mail.list()
        print("📂 Папки:")
        for f in folders:
            print(f"   {f.decode()}")

        return mail

    except imaplib.IMAP4.error as e:
        print(f"❌ Ошибка авторизации: {e}")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")

    return None


# ─── Тест ───────────────────────────────────────────
if __name__ == "__main__":
    email    = "klevins@san.rr.com"
    password = "Michele07$"

    mail = connect_imap(email, password)

    if mail:
        # Выбираем папку входящих и считаем письма
        mail.select("INBOX")
        status, messages = mail.search(None, "ALL")
        count = len(messages[0].split())
        print(f"📬 Писем в INBOX: {count}")

        mail.logout()