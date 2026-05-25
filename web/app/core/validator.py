import re

ACCOUNT_RE = re.compile(r'^[^:\s]+:[^:\s]+$|^[^:\s]+:[^:\s]+:[^:\s]+$')
PROXY_RE = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}(?::[^:\s]+:[^:\s]+)?$')
EMAIL_RE = re.compile(r'^[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}:[^:\s]+$')


def _split(lines: list[str], regex: re.Pattern[str]) -> tuple[list[str], list[str]]:
    valid, invalid = [], []
    for line in lines:
        (valid if regex.match(line) else invalid).append(line)
    return valid, invalid


def validate_accounts(lines: list[str]) -> tuple[list[str], list[str]]:
    return _split(lines, ACCOUNT_RE)


def validate_proxies(lines: list[str]) -> tuple[list[str], list[str]]:
    return _split(lines, PROXY_RE)


def validate_emails(lines: list[str]) -> tuple[list[str], list[str]]:
    return _split(lines, EMAIL_RE)