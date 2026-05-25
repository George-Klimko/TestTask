from dataclasses import dataclass, field


@dataclass
class UserUploadData:
    accounts: list[str] = field(default_factory=list)
    proxies: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)


class UploadStorage:
    def __init__(self) -> None:
        self._by_user: dict[str, UserUploadData] = {}

    def for_user(self, user_id: str) -> UserUploadData:
        if user_id not in self._by_user:
            self._by_user[user_id] = UserUploadData()
        return self._by_user[user_id]


storage = UploadStorage()