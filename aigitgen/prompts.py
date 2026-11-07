"""프롬프트 설계 (과제 요구사항 4번 / 과제 목표 4번).

이 과제의 핵심은 "단순 API 호출"이 아니라 **어떤 입력을 주는가** 다.
그래서 프롬프트를 코드 안에 흩어놓지 않고 이 파일에 모았다.
평가에서 "프롬프트를 어떻게 구성했나"를 물으면 이 파일을 보여주면 된다.

설계 원칙 네 가지
  1. **역할과 규칙은 system 에, 변하는 데이터는 user 에** 둔다.
     system 은 매 호출마다 같으므로 캐시가 되고, 규칙이 데이터에 섞여
     희석되지 않는다.
  2. **출력 형식을 예시로 못 박는다.** "짧게 써라" 같은 말보다
     원하는 모양을 그대로 보여주는 쪽이 훨씬 잘 지켜진다.
  3. **모르는 건 지어내지 말라고 명시한다.** diff 에 없는 내용을
     그럴듯하게 쓰는 것이 이 도구의 가장 큰 위험이다.
  4. **재생성 때는 '무엇이 틀렸는지'를 되돌려준다.** 같은 요청을
     그대로 다시 보내면 같은 결과가 나온다.
"""

from __future__ import annotations

from .gitctl import Changes

# ── system 프롬프트 ────────────────────────────────────────────────────────

COMMIT_SYSTEM = """\
당신은 git 커밋 메시지를 쓰는 도구다. 사용자가 준 변경 사항만 근거로 삼는다.

규칙
- 출력은 커밋 메시지 그 자체만. 인사말·설명·코드블록 표시(```)를 붙이지 않는다.
- 첫 줄은 제목이다. 50자 이내를 목표로 하고 72자를 절대 넘기지 않는다.
- 제목은 `<type>: <요약>` 형식을 쓴다. type 은 feat, fix, docs, refactor,
  test, chore, perf, style 중에서 변경 내용에 맞는 것을 고른다.
- 제목 끝에 마침표를 찍지 않는다. 명령형 현재시제로 쓴다("추가" 아니라 "추가한다"도 아니고
  "add" 계열의 간결한 명사형/동사형 요약).
- 제목 다음은 빈 줄 하나, 그 다음 본문이다.
- 본문은 `- ` 불릿 1~3개로 쓴다. 각 불릿은 한 줄로 끝낸다.
- 본문에는 **변경된 파일이나 모듈 이름을 최소 1개** 언급한다.
- diff 에 없는 내용은 쓰지 않는다. 의도나 배경을 추측하지 않는다.
- 변경이 여러 성격이 섞여 있으면 가장 큰 것을 제목으로 잡고 나머지를 불릿에 적는다.

출력 예시 (이 모양을 그대로 따른다)
feat: diff 기반 커밋 메시지 생성 기능 추가

- aigitgen/llm.py 에 Anthropic API 호출 래퍼 추가
- gitctl.py 가 staged/unstaged 를 자동 판단하도록 변경
- API 키 미설정 시 안내 메시지 출력
"""

PR_SYSTEM = """\
당신은 Pull Request 초안을 쓰는 도구다. 사용자가 준 변경 사항만 근거로 삼는다.

규칙
- 출력은 PR 제목과 본문만. 인사말·설명·코드블록 표시(```)를 붙이지 않는다.
- 첫 줄은 PR 제목이다. 1줄이고 80자를 넘기지 않는다. 'PR Title:' 같은 머리말을 붙이지 않는다.
- 제목 다음은 빈 줄 하나, 그 다음부터 본문이다.
- 본문은 반드시 아래 세 섹션을 이 순서로, 이 헤더 글자 그대로 포함한다.
  ## Why
  ## What
  ## How to Test
- 각 섹션에는 `- ` 불릿이 최소 1개 있어야 한다. 산문으로 쓰지 않는다.
- Why 는 '왜 이 변경이 필요했나'다. diff 에서 읽을 수 있는 범위로만 쓴다.
  배경을 모르면 "diff 상으로는 ~를 위한 변경으로 보입니다" 처럼 근거를 밝힌다.
- What 은 '무엇을 바꿨나'다. 파일/모듈 이름을 언급한다.
- How to Test 는 '어떻게 확인하나'다. 실제로 저장소에 있는 명령만 적는다.
  테스트 파일이 diff 에 있으면 그 실행법을, 없으면 수동 확인 절차를 적는다.
- diff 에 없는 내용은 쓰지 않는다. 없는 명령어를 만들지 않는다.

출력 예시 (이 모양을 그대로 따른다)
feat: 커밋/PR 자동 생성 기능 추가

## Why
- 커밋 메시지와 PR 설명 작성에 시간이 걸려 자동 생성 도구가 필요했습니다.

## What
- gitctl.py 에 status/diff 수집 로직 추가
- llm.py 에 Anthropic API 호출 및 예외 처리 추가

## How to Test
- 환경변수 설정: export ANTHROPIC_API_KEY="..."
- 실행: python main.py commit
"""


# ── user 프롬프트 ──────────────────────────────────────────────────────────

def _changes_block(changes: Changes, diff_for_prompt: str) -> str:
    """변경 사항을 프롬프트에 넣을 모양으로 조립한다.

    파일 목록을 diff 앞에 따로 넣는 이유: diff 가 길면 모델이 앞부분에
    더 집중한다. "무엇이 바뀌었나"의 요약을 먼저 주면 전체 그림을 놓치지 않는다.
    """
    files = "\n".join(f"- {p}" for p in changes.files) or "- (없음)"
    scope = "staged (커밋 예정)" if changes.staged else "unstaged (작업 중)"
    return (
        f"## 변경 범위\n{scope}\n\n"
        f"## 변경된 파일 ({len(changes.files)}개)\n{files}\n\n"
        f"## git status --short\n```\n{changes.status_text.strip() or '(없음)'}\n```\n\n"
        f"## git diff ({changes.diff_line_count}줄)\n```diff\n{diff_for_prompt.strip() or '(없음)'}\n```"
    )


def commit_user(changes: Changes, diff_for_prompt: str, convention: str | None = None) -> str:
    extra = f"\n\n## 팀 컨벤션 (반드시 따른다)\n{convention.strip()}" if convention else ""
    return (
        "아래 변경 사항을 보고 커밋 메시지를 작성하라.\n\n"
        + _changes_block(changes, diff_for_prompt)
        + extra
    )


def pr_user(
    changes: Changes,
    diff_for_prompt: str,
    branch: str,
    convention: str | None = None,
) -> str:
    extra = f"\n\n## 팀 컨벤션 (반드시 따른다)\n{convention.strip()}" if convention else ""
    return (
        f"아래 변경 사항을 보고 Pull Request 제목과 본문을 작성하라.\n"
        f"현재 브랜치: {branch}\n\n"
        + _changes_block(changes, diff_for_prompt)
        + extra
    )


def retry_user(original_user: str, previous_output: str, feedback: str) -> str:
    """재생성 요청. 틀린 결과와 틀린 이유를 함께 준다.

    원래 요청을 다시 보내는 이유: API 는 상태를 기억하지 않는다. 변경 사항을
    빼고 "다시 써라"만 보내면 모델이 무엇을 대상으로 쓰는지 모른다.
    """
    return (
        original_user
        + "\n\n---\n\n"
        + "## 직전 출력 (형식 규칙 위반)\n```\n"
        + previous_output.strip()
        + "\n```\n\n## 위반 내용\n"
        + feedback
        + "\n\n위 위반을 고쳐서 다시 작성하라. 내용은 유지하고 형식만 맞춰라."
    )
