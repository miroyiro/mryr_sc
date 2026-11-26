"""자동 게시 판단 (순수 함수). 표 한 줄 = 조건 하나만 바꾼 후보 → 기대 사유."""
from dataclasses import replace

import pytest

from src.services.auto_publish import (
    PublishCandidate, can_auto_publish, is_vocaloid, vocaloid_phrases,
)

EV = {"start_at": "2027-01-14T00:00:00+09:00", "source_url": "https://kopis.or.kr/x"}

KOPIS_OK = PublishCandidate(source_name="kopis", source_auto_publish=True, title="요네즈 켄시 내한공연",
                            event_data=EV, artist_id=7, raw_data={"visit": "Y", "cast": "요네즈 켄시"})
ANISSIA_OK = PublishCandidate(source_name="anissia", source_auto_publish=True, title="바람의 저편",
                              event_data=EV, anime_id=3)


@pytest.mark.parametrize("cand, reasons", [
    (KOPIS_OK, ()),
    (ANISSIA_OK, ()),
    (replace(KOPIS_OK, source_auto_publish=False), ("source_auto_publish_off",)),
    (replace(KOPIS_OK, title=None), ("missing_title",)),
    (replace(KOPIS_OK, event_data={**EV, "start_at": None}), ("missing_start_at",)),
    (replace(KOPIS_OK, event_data={**EV, "source_url": ""}), ("missing_source_url",)),
    (replace(KOPIS_OK, event_data=None), ("missing_start_at", "missing_source_url")),
    (replace(KOPIS_OK, raw_data={"visit": "N", "cast": "요네즈 켄시"}), ("visit_not_y",)),
    (replace(KOPIS_OK, artist_id=None), ("artist_unmatched",)),
    (replace(KOPIS_OK, artist_id=None, anime_id=5), ("artist_unmatched",)),   # kopis 는 anime 매칭으로 안 됨
    (replace(KOPIS_OK, title="初音ミク マジカルミライ 2027 in Seoul"), ("vocaloid",)),
    (replace(ANISSIA_OK, anime_id=None), ("anime_unmatched",)),
    (replace(ANISSIA_OK, anime_id=None, artist_id=9), ("anime_unmatched",)),
    (replace(KOPIS_OK, source_name="animate"), ("no_source_rule",)),
])
def test_reasons_table(cand, reasons):
    d = can_auto_publish(cand)
    assert d.reasons == reasons
    assert d.ok is (reasons == ())


def test_vocaloid_hard_excluded_flag_only():
    d = can_auto_publish(replace(KOPIS_OK, raw_data={"visit": "Y", "cast": "Hatsune Miku"}))
    assert d.ok is False and d.hard_excluded is True and "vocaloid" in d.reasons


@pytest.mark.parametrize("text, expected", [
    ("VOCALOID LIVE", True),
    ("ＶＯＣＡＬＯＩＤ ライブ", True),        # 전각 → NFKC
    ("hatsune MIKU symphony", True),          # 대소문자 무시
    ("ﾎﾞｶﾛ 커버 공연", True),                  # 반각 가타카나 → NFKC
    ("마지컬 미라이 2027", True),
    ("MIKU 단독 콘서트", False),               # 'MIKU' 단독은 매칭 안 함
    ("Mikuni Shimokawa Live", False),
    ("요네즈 켄시 내한공연", False),
])
def test_is_vocaloid(text, expected):
    assert is_vocaloid(text) is expected


def test_phrases_come_from_config_file():
    phrases = vocaloid_phrases()
    assert "vocaloid" in phrases and "miku" not in phrases     # 정규화(casefold)된 값
    assert is_vocaloid("새 구문 공연", phrases=("새 구문",)) is True  # 목록을 바꾸면 판단도 바뀜


@pytest.mark.parametrize("cand, hint", [
    (replace(KOPIS_OK, artist_id=None, raw_data={"visit": "Y", "cast": "ずっと真夜中でいいのに。"}), True),  # 히라가나
    (replace(KOPIS_OK, artist_id=None, title="ヨルシカ LIVE"), True),                                   # 가타카나
    (replace(KOPIS_OK, artist_id=None), False),                       # 한글만
    (replace(KOPIS_OK, artist_id=None, alias_matched=True), True),    # 별칭 매칭
    (replace(KOPIS_OK, title="요네즈 켄시 내한공연 Seoul"), False),     # '내한' 은 힌트 조건 아님
    (replace(ANISSIA_OK, title="ヨルシカ"), False),                     # anissia 는 힌트 계산 안 함
])
def test_jpop_hint_is_reference_only(cand, hint):
    d = can_auto_publish(cand)
    assert d.jpop_hint is hint
    # 힌트는 사유가 아님 → 게시 여부(ok)는 사유 목록만으로 정해짐
    assert not any("jpop" in r for r in d.reasons)
    assert d.ok is (d.reasons == ())


def test_alias_hint_does_not_change_ok():
    base = replace(KOPIS_OK, artist_id=None)
    assert can_auto_publish(base).ok == can_auto_publish(replace(base, alias_matched=True)).ok
