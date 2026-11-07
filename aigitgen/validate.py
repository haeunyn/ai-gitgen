"""출력 형식 검증 및 다듬기 (과제 요구사항 5번).

과제는 "검증 후 재생성 또는 후처리 중 택 1" 을 허용한다.
이 도구는 **둘 다** 쓴다. 다만 순서와 횟수에 제한을 둔다.

  1회차 호출 → 검증 → 통과하면 끝
                     → 실패하면 "무엇이 틀렸는지"를 알려주고 **1회만** 재생성
  2회차 결과 → 검증 → 그래도 실패하면 **후처리**로 규칙을 강제

왜 이렇게 했나: 제약 사항에 "1회 실행 시 요청 횟수는 1~2회 이내" 가 있다.
재생성을 무한히 돌리면 그 제약을 깬다. 그래서 재생성은 딱 한 번이고,
그 다음은 돈이 들지 않는 후처리로 마무리한다.

후처리가 재생성보다 나쁜 이유도 분명하다. 제목을 기계적으로 자르면
문장이 어색해진다. 그래서 재생성을 먼저 시도한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 과제 4쪽의 길이/형식 규칙
COMMIT_TITLE_RECOMMENDED = 50
COMMIT_TITLE_MAX = 72
PR_TITLE_MAX = 80
PR_SECTIONS = ("Why", "What", "How to Test")

_BULLET = re.compile(r"^\s*[-*+]\s+\S")


@dataclass
class Issue:
    """검증 실패 한 건."""

    rule: str
    detail: str


@dataclass
class Result:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def feedback(self) -> str:
        """재생성 요청에 붙일 피드백 문장. AI 에게 '무엇이 틀렸는지' 알려준다."""
        lines = [f"- {i.detail}" for i in self.issues]
        return "\n".join(lines)


# ── 커밋 메시지 ────────────────────────────────────────────────────────────

def split_commit(text: str) -> tuple[str, str]:
    """커밋 메시지를 (제목, 본문) 으로 나눈다. 첫 줄이 제목이다."""
    lines = text.strip().splitlines()
    if not lines:
        return "", ""
    title = lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    return title, body


def validate_commit(text: str) -> Result:
    issues: list[Issue] = []
    warnings: list[Issue] = []
    title, body = split_commit(text)

    if not title:
        issues.append(Issue("title_required", "커밋 제목 1줄이 비어 있습니다."))
    if len(title) > COMMIT_TITLE_MAX:
        issues.append(
            Issue(
                "title_max",
                f"커밋 제목이 {len(title)}자입니다. 최대 {COMMIT_TITLE_MAX}자 이내로 줄이세요.",
            )
        )
    elif len(title) > COMMIT_TITLE_RECOMMENDED:
        # 권장치 초과는 '경고'다. 과제가 50자를 권장, 72자를 최대로 구분했다.
        warnings.append(
            Issue(
                "title_recommended",
                f"커밋 제목이 {len(title)}자입니다 (권장 {COMMIT_TITLE_RECOMMENDED}자 이내).",
            )
        )

    # 본문은 선택이다. 다만 본문을 포함한다면 최소 기준이 있다(요구사항 3번):
    # 변경 파일 1~3개 언급 또는 핵심 변경 1~2개 불릿.
    if body:
        has_bullet = any(_BULLET.match(ln) for ln in body.splitlines())
        if not has_bullet:
            issues.append(
                Issue(
                    "body_quality",
                    "커밋 본문이 있는데 불릿이 없습니다. 핵심 변경 사항을 '- ' 불릿 1~2개로 적으세요.",
                )
            )

    return Result(ok=not issues, issues=issues, warnings=warnings)


# 제목이 아예 비었을 때 쓰는 자리표시. 내용을 지어내지 않고 사람이 채우게 한다.
PLACEHOLDER_TITLE = "chore: (제목을 직접 작성해주세요)"


def postprocess_commit(text: str) -> str:
    """재생성도 실패했을 때 규칙을 기계적으로 강제한다.

    **후처리를 거친 결과는 반드시 검증을 통과해야 한다.** 그게 이 함수의 존재 이유다.
    (2026-11-07: 제목이 빈 입력에서 이 보장이 깨지는 걸 테스트가 잡아냈다.)
    """
    title, body = split_commit(text)
    if not title:
        title = PLACEHOLDER_TITLE
    if len(title) > COMMIT_TITLE_MAX:
        # 단어 경계에서 자른다. 글자 중간에서 끊으면 더 이상해진다.
        cut = title[:COMMIT_TITLE_MAX]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        title = cut.rstrip(" ,.;:-")
    out = title
    if body:
        out += "\n\n" + body
    return out


# ── PR ────────────────────────────────────────────────────────────────────

def split_pr(text: str) -> tuple[str, str]:
    """AI 출력에서 PR 제목과 본문을 분리한다.

    본문은 '## Why' 부터 시작한다고 본다. 그 앞의 첫 비어있지 않은 줄이 제목이다.
    모델이 'PR Title:' 같은 머리말을 붙이는 경우가 있어 벗겨낸다.
    """
    text = text.strip()
    idx = text.find("## Why")
    if idx == -1:
        lines = text.splitlines()
        title = lines[0].strip() if lines else ""
        body = "\n".join(lines[1:]).strip()
    else:
        head = text[:idx].strip()
        body = text[idx:].strip()
        title_lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
        title = title_lines[-1] if title_lines else ""

    title = re.sub(r"^(?:#+\s*)?(?:PR\s*)?(?:Title|제목)\s*[:：]\s*", "", title, flags=re.I).strip()
    title = title.lstrip("#").strip()
    return title, body


def _section_bodies(body: str) -> dict[str, str]:
    """'## Why' 같은 헤더로 본문을 섹션별로 쪼갠다."""
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", line)
        if m:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def validate_pr(text: str) -> Result:
    issues: list[Issue] = []
    warnings: list[Issue] = []
    title, body = split_pr(text)

    if not title:
        issues.append(Issue("pr_title_required", "PR 제목 1줄이 비어 있습니다."))
    if len(title) > PR_TITLE_MAX:
        issues.append(
            Issue("pr_title_max", f"PR 제목이 {len(title)}자입니다. 최대 {PR_TITLE_MAX}자 이내로 줄이세요.")
        )
    if "\n" in title.strip():
        issues.append(Issue("pr_title_oneline", "PR 제목은 1줄이어야 합니다."))

    sections = _section_bodies(body)
    for name in PR_SECTIONS:
        match = next((k for k in sections if k.lower() == name.lower()), None)
        if match is None:
            issues.append(Issue("pr_section", f"PR 본문에 '## {name}' 섹션 헤더가 없습니다."))
            continue
        bullets = [ln for ln in sections[match].splitlines() if _BULLET.match(ln)]
        if not bullets:
            issues.append(
                Issue("pr_bullet", f"'## {name}' 섹션에 불릿이 없습니다. '- ' 로 시작하는 항목을 최소 1개 넣으세요.")
            )

    return Result(ok=not issues, issues=issues, warnings=warnings)


def postprocess_pr(text: str) -> str:
    """재생성도 실패했을 때 최소 구조를 강제한다.

    비어 있는 섹션은 **지어내지 않는다.** 사람이 채워야 한다는 표시를 남긴다.
    AI 가 모르는 내용을 그럴듯하게 써 넣는 게 더 위험하다.

    **이 함수의 출력은 반드시 validate_pr 을 통과한다.** tests 가 이걸 검사한다.
    """
    title, body = split_pr(text)
    if not title:
        title = PLACEHOLDER_TITLE
    if len(title) > PR_TITLE_MAX:
        cut = title[:PR_TITLE_MAX]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        title = cut.rstrip(" ,.;:-")

    sections = _section_bodies(body)
    rebuilt: list[str] = []
    for name in PR_SECTIONS:
        match = next((k for k in sections if k.lower() == name.lower()), None)
        content = sections.get(match, "").strip() if match else ""
        bullets = [ln.rstrip() for ln in content.splitlines() if _BULLET.match(ln)]
        if not bullets:
            if content:
                # 산문으로 쓴 경우 → 불릿으로 바꿔준다
                bullets = [f"- {ln.strip()}" for ln in content.splitlines() if ln.strip()][:3]
            else:
                bullets = ["- (직접 채워주세요)"]
        rebuilt.append(f"## {name}\n" + "\n".join(bullets))

    return title + "\n\n" + "\n\n".join(rebuilt)
