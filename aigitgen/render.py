"""출력 구획 (과제 요구사항 5번 후단).

"사용자가 결과를 검토할 수 있도록, 최종 출력은 구분선/헤더 등으로 구획이
나뉘어 표시되어야 한다" — 그 구획을 여기서 만든다.

색은 쓰지 않는다. 터미널 로그를 복사해 붙일 때 이스케이프 문자가 섞이면
리포트에 그대로 들어가기 때문이다.
"""

from __future__ import annotations

import sys

WIDTH = 72


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def done(msg: str) -> None:
    print(f"[DONE] {msg}")


def error(msg: str) -> None:
    """오류는 표준에러로 보낸다. 파이프로 넘길 때 결과물과 섞이지 않게."""
    print(f"[ERROR] {msg}", file=sys.stderr)


def block(title: str, body: str) -> None:
    """결과물 한 덩어리를 구분선으로 감싸 출력한다."""
    print()
    print(f"--- {title} " + "-" * max(0, WIDTH - len(title) - 5))
    print(body.strip())
    print("-" * WIDTH)


def section(title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f" {title}")
    print("=" * WIDTH)
