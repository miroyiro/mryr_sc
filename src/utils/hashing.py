import hashlib
import json
from typing import Any


def sha256_hex(*parts: Any) -> str:
    """raw_item.hash 용. None 은 빈 문자열, dict/list 는 키 정렬 JSON → 순서가 달라도 같은 해시."""
    h = hashlib.sha256()
    for p in parts:
        if p is None:
            s = ""
        elif isinstance(p, (dict, list)):
            s = json.dumps(p, ensure_ascii=False, sort_keys=True, default=str)
        else:
            s = str(p)
        h.update(s.encode("utf-8"))
        h.update(b"\x1f")  # 구분자: ("ab","c") 와 ("a","bc") 가 같은 해시가 되지 않게
    return h.hexdigest()
