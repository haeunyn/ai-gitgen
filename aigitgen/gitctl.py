"""git 명령 실행 결과를 프로그램 입력으로 연결하는 층.

과제 요구사항 1번("Git 변경 사항 수집")을 담당한다.
수집 범위는 `git status` 와 `git diff` 로만 제한한다(제약 사항).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class GitError(RuntimeError):
    """git 명령 자체가 실패했을 때."""


def _run(args: list[str], cwd: str = ".") -> str:
    """git 명령을 돌리고 표준출력을 돌려준다.

    왜 subprocess 인가: 파이썬에서 git 을 다루는 라이브러리(GitPython 등)도 있지만,
    이 과제는 "git 명령 실행 결과를 프로그램 입력으로 연결하는 방식"을 설명하는 게
    목표다. subprocess 로 직접 실행하면 그 연결 지점이 코드에 그대로 보인다.

    text=True 로 바이트가 아니라 문자열을 받는다.
    errors="replace" 는 diff 안에 UTF-8 이 아닌 바이트가 섞여도 죽지 않게 한다
    (이미지 같은 바이너리 파일이 변경되면 실제로 생긴다).
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git 명령을 찾을 수 없습니다. git 이 설치돼 있는지 확인하세요.") from exc

    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} 실패 (종료코드 {proc.returncode})\n{proc.stderr.strip()}"
        )
    return proc.stdout


def ensure_git_repo(cwd: str = ".") -> None:
    """CLI 는 git 이 초기화된 프로젝트 루트에서 실행되어야 한다(요구사항 1번)."""
    try:
        inside = _run(["rev-parse", "--is-inside-work-tree"], cwd).strip()
    except GitError as exc:
        raise GitError(
            "여기는 git 저장소가 아닙니다. git 이 초기화된 프로젝트 루트에서 실행하세요.\n"
            f"  (원인: {exc})"
        ) from exc
    if inside != "true":
        raise GitError("여기는 git 작업 트리가 아닙니다.")


def current_branch(cwd: str = ".") -> str:
    """현재 브랜치 이름. 커밋이 하나도 없으면 'HEAD' 가 나올 수 있다."""
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


@dataclass
class Changes:
    """수집한 변경 사항 한 묶음."""

    status_text: str          # git status --short 원문
    diff_text: str            # git diff 원문
    files: list[str]          # 변경된 파일 경로
    staged: bool              # staged(--cached) 쪽을 봤는지
    diff_line_count: int

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.diff_text.strip()


def collect(cwd: str = ".", staged: bool | None = None) -> Changes:
    """status + diff 를 수집한다.

    staged=None 이면 **자동 판단**한다. staged 변경이 있으면 그쪽을, 없으면
    unstaged 쪽을 본다. 커밋 메시지를 뽑는 도구이므로 "이제 커밋할 것"이
    staged 에 있을 때 그걸 우선하는 게 자연스럽다.
    """
    status_text = _run(["status", "--short"], cwd)

    if staged is None:
        has_staged = bool(_run(["diff", "--cached", "--name-only"], cwd).strip())
        staged = has_staged

    diff_args = ["diff", "--cached"] if staged else ["diff"]
    name_args = [*diff_args, "--name-only"]

    diff_text = _run(diff_args, cwd)
    files = [p for p in _run(name_args, cwd).splitlines() if p.strip()]

    # 추적되지 않은 새 파일(untracked)은 git diff 에 안 나온다.
    # 목록에만이라도 포함시켜야 "무엇이 바뀌었나"가 정확해진다.
    if not staged:
        untracked = [p for p in _run(["ls-files", "--others", "--exclude-standard"], cwd).splitlines() if p.strip()]
        for p in untracked:
            if p not in files:
                files.append(p)

    return Changes(
        status_text=status_text,
        diff_text=diff_text,
        files=files,
        staged=bool(staged),
        diff_line_count=len(diff_text.splitlines()),
    )
