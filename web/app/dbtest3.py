import sqlite3
import imaplib
import email
from email.header import decode_header
import os
import ssl
import certifi
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
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    # Разрешаем старые протоколы, если сервер древний
    context.set_ciphers('DEFAULT@SECLEVEL=1')
    # 1. Проверяем, вернулось ли вообще что-то
    if not settings:
        print(f"❌ Настройки IMAP для {email} не найдены в базе")
        return None
        
    # 2. Проверяем, нет ли там сообщения об ошибке (как для 'T_R-A X')
    if "error" in settings:
        print(f"⚠️ Пропуск {email}: {settings['error']}")
        return None
        
    # 3. Проверяем наличие всех необходимых ключей перед выводом
    required_keys = ['imap', 'imap_port', 'ssl']
    if not all(key in settings for key in required_keys):
        print(f"❌ Кривая запись в БД для {email} (не хватает данных)")
        return None

    print(f"📡 Подключаемся к {settings['imap']}:{settings['imap_port']} (SSL: {settings['ssl']})")
    
    try:
        if settings["ssl"]:
            mail = imaplib.IMAP4_SSL(settings["imap"], settings["imap_port"], ssl_context=context)
        else:
            mail = imaplib.IMAP4(settings["imap"], settings["imap_port"])
            try:
                mail.starttls()
            except:
                pass  # если сервер не поддерживает STARTTLS, просто продолжим без него
        mail.login(email, password)
        print(f"✅ Успешно подключились как {email}")
        return mail
        
    except imaplib.IMAP4.error as e:
        # Обычно здесь b'[AUTHENTICATIONFAILED]'
        print(f"❌ Ошибка авторизации для {email}: {e}")
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")
        
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


# ================= НОВАЯ ФУНКЦИЯ ДЛЯ ЧТЕНИЯ ИЗ ФАЙЛА =================

def process_accounts_from_file(filepath: str, keyword: str):
    """Считывает txt файл со строками email:pass и проверяет каждый аккаунт"""
    if not os.path.exists(filepath):
        print(f"❌ Файл {filepath} не найден. Создай его и добавь аккаунты.")
        return

    with open(filepath, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    for line in lines:
        line = line.strip()
        # Пропускаем пустые строки
        if not line:
            continue
            
        # Разбиваем строку по ПЕРВОМУ двоеточию (на случай если в пароле тоже есть двоеточие)
        parts = line.split(':', 1)
        if len(parts) != 2:
            print(f"\n⚠️ Пропущена некорректная строка (ожидался формат email:pass): {line}")
            continue

        email_addr, password = parts
        # Убираем возможные лишние пробелы вокруг почты и пароля
        email_addr = email_addr.strip()
        password = password.strip()

        print(f"\n{'='*60}")
        print(f"⏳ Проверяем аккаунт: {email_addr}")
        
        # Подключаемся
        mail_client = connect_imap(email_addr, password)
        
        # Если подключились успешно — ищем письма
        if mail_client:
            print(f"🔍 Ищем письма от {keyword}...\n")
            find_latest_from(mail_client, keyword)
            
            # Закрываем соединение, чтобы не висели открытые сессии
            try:
                mail_client.logout()
            except:
                pass


if __name__ == "__main__":
    # Укажи путь к txt файлу (если лежит рядом, можно просто имя файла)
    ACCOUNTS_FILE = "/home/raw/prosch/web/app/mix.txt"
    SEARCH_KEYWORD = "poshmark"

    # Запускаем прогонку базы
    process_accounts_from_file(ACCOUNTS_FILE, SEARCH_KEYWORD)