"""safe-mode — diff 를 AI 에 보내기 전에 손보는 층.

과제 제약 사항은 아래 둘 중 **하나 이상**을 요구한다. 둘 다 구현했다.
  (A) diff 에서 특정 패턴(API Key 형태, 이메일 등)을 마스킹 후 전송
  (B) diff 일부만 전송 (예: 최대 10개 파일, 최대 200줄)

왜 중요한가: git diff 에는 `.env` 수정, 하드코딩된 키, 테스트용 개인정보가
그대로 들어 있을 수 있다. 그걸 외부 API 로 보내면 **돌이킬 수 없다.**
요청은 취소할 수 있어도 이미 전송된 데이터는 못 지운다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── (A) 마스킹 규칙 ────────────────────────────────────────────────────────
# 순서가 중요하다. 더 구체적인 패턴을 먼저 둬야 한다.
# 예를 들어 이메일을 먼저 지우면 'user@example.com' 안의 도메인이 사라져서
# 뒤의 URL 패턴이 엉뚱한 걸 잡는다.
#
# 각 패턴은 (이름, 정규식, 치환문자열) 이다.
MASK_RULES: list[tuple[str, re.Pattern[str], str]] = [
    # Anthropic / OpenAI 계열 키
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "sk-ant-***MASKED***"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "sk-***MASKED***"),
    # AWS
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "AKIA***MASKED***"),
    ("aws_secret", re.compile(r"(?i)(aws_secret_access_key\s*[=:]\s*)\S+"), r"\1***MASKED***"),
    # GitHub 토큰
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "ghp_***MASKED***"),
    # 일반적인 KEY=VALUE 꼴 (env 파일 수정이 diff 에 들어온 경우)
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL)[A-Z0-9_]*)"
            r"(\s*[=:]\s*)(\"|')?([^\s\"']{4,})(\3)?"
        ),
        r"\1\2***MASKED***",
    ),
    # Bearer 토큰
    ("bearer", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{10,}"), r"\1***MASKED***"),
    # 개인정보: 이메일
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"), "***EMAIL***"),
    # 개인정보: 한국 휴대폰 번호
    ("phone_kr", re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b"), "***PHONE***"),
    # 개인정보: 주민등록번호 꼴
    ("rrn_kr", re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"), "***RRN***"),
    # 사설 키 블록
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "-----BEGIN ***MASKED*** KEY-----"),
]


@dataclass
class SanitizeReport:
    """무엇을 얼마나 손봤는지. 사용자에게 그대로 보여준다."""

    masked_counts: dict[str, int] = field(default_factory=dict)
    files_total: int = 0
    files_sent: int = 0
    lines_total: int = 0
    lines_sent: int = 0
    truncated: bool = False

    @property
    def masked_total(self) -> int:
        return sum(self.masked_counts.values())


def mask_secrets(text: str) -> tuple[str, dict[str, int]]:
    """(A) 민감정보로 보이는 패턴을 치환한다.

    완벽한 탐지는 불가능하다. 정규식은 '그렇게 생긴 것'만 잡는다.
    그래서 README 에 "safe-mode 는 보조 장치이고, 최종 책임은 사용자" 라고 적어뒀다.
    """
    counts: dict[str, int] = {}
    for name, pattern, repl in MASK_RULES:
        text, n = pattern.subn(repl, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


def _split_by_file(diff_text: str) -> list[str]:
    """diff 를 파일 단위 덩어리로 나눈다.

    `git diff` 는 파일마다 'diff --git a/... b/...' 로 시작한다.
    그 줄을 경계로 쓴다.
    """
    if not diff_text.strip():
        return []
    parts: list[str] = []
    buf: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git ") and buf:
            parts.append("".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        parts.append("".join(buf))
    return parts


def limit_diff(diff_text: str, max_files: int, max_lines: int) -> tuple[str, bool]:
    """(B) 파일 수와 줄 수로 전송량을 제한한다.

    파일 **경계를 지켜서** 자른다. 줄 수만 보고 자르면 diff 가 중간에서 끊겨
    AI 가 변경 내용을 오해한다. 덩어리째 버리는 게 낫다.
    """
    chunks = _split_by_file(diff_text)
    if not chunks:
        return diff_text, False

    truncated = False
    if len(chunks) > max_files:
        chunks = chunks[:max_files]
        truncated = True

    kept: list[str] = []
    used = 0
    for chunk in chunks:
        n = len(chunk.splitlines())
        if used + n > max_lines:
            remaining = max_lines - used
            if remaining > 0:
                head = "".join(chunk.splitlines(keepends=True)[:remaining])
                kept.append(head)
                used = max_lines
            truncated = True
            break
        kept.append(chunk)
        used += n

    out = "".join(kept)
    if truncated:
        out += (
            "\n[... diff 가 safe-mode 제한으로 잘렸습니다 "
            f"(최대 {max_files}개 파일 / {max_lines}줄) ...]\n"
        )
    return out, truncated


def prepare_diff(
    diff_text: str,
    *,
    safe_mode: bool,
    max_files: int = 10,
    max_lines: int = 200,
) -> tuple[str, SanitizeReport]:
    """safe-mode 전체 파이프라인. 마스킹 → 제한 순서로 돈다.

    순서가 중요하다. 먼저 자르면, 잘려나간 부분의 비밀값은 검사조차 안 된다.
    **마스킹을 먼저** 해야 "보낸 것 중에 비밀값이 없다"를 보장할 수 있다.
    """
    report = SanitizeReport(
        files_total=len(_split_by_file(diff_text)),
        lines_total=len(diff_text.splitlines()),
    )

    if not safe_mode:
        report.files_sent = report.files_total
        report.lines_sent = report.lines_total
        return diff_text, report

    masked, counts = mask_secrets(diff_text)
    report.masked_counts = counts

    limited, truncated = limit_diff(masked, max_files=max_files, max_lines=max_lines)
    report.truncated = truncated
    report.files_sent = min(report.files_total, max_files)
    report.lines_sent = len(limited.splitlines())
    return limited, report
