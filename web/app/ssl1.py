# import imaplib
# import ssl

# ctx = ssl.create_default_context()
# ctx.set_ciphers('DEFAULT:@SECLEVEL=1')

# with imaplib.IMAP4_SSL('mobile.charter.net', 993, ssl_context=ctx) as mail:
#     mail.login('sdebster@charter.net', 'Ms4d2808@')
#     mail.select('INBOX')
#     typ, data = mail.search(None, 'ALL')
#     print(typ, data)
    
import imaplib
import ssl
import certifi

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.minimum_version = ssl.TLSVersion.TLSv1_2
ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
ctx.check_hostname = True
ctx.verify_mode = ssl.CERT_REQUIRED
ctx.load_verify_locations(certifi.where())  # берём CA из certifi

with imaplib.IMAP4_SSL('mobile.charter.net', 993, ssl_context=ctx) as mail:
    mail.login('klevins@san.rr.com', 'Michele07$')
    mail.select('INBOX')
    typ, data = mail.search(None, 'ALL')
    print(typ, data)