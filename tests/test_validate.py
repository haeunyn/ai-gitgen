"""출력 형식 검증 테스트. API 를 호출하지 않는다."""

from aigitgen import validate

GOOD_COMMIT = """feat: diff 기반 커밋 메시지 생성 추가

- aigitgen/llm.py 에 API 호출 래퍼 추가
- gitctl.py 가 staged 를 자동 판단
"""

GOOD_PR = """feat: 커밋/PR 자동 생성 기능 추가

## Why
- 커밋 메시지 작성에 시간이 걸려 자동화가 필요했습니다.

## What
- gitctl.py 에 status/diff 수집 추가

## How to Test
- python main.py commit
"""


# ── 커밋 ──────────────────────────────────────────────────────────────────

def test_good_commit_passes():
    assert validate.validate_commit(GOOD_COMMIT).ok


def test_commit_title_only_passes():
    """본문은 선택이다(요구사항 3번)."""
    assert validate.validate_commit("fix: 오타 수정").ok


def test_empty_commit_fails():
    r = validate.validate_commit("")
    assert not r.ok
    assert any(i.rule == "title_required" for i in r.issues)


def test_commit_title_over_72_fails():
    r = validate.validate_commit("feat: " + "가" * 80)
    assert not r.ok
    assert any(i.rule == "title_max" for i in r.issues)


def test_commit_title_between_50_and_72_warns_only():
    title = "feat: " + "a" * 55   # 61자
    r = validate.validate_commit(title)
    assert r.ok                                  # 통과는 한다
    assert any(i.rule == "title_recommended" for i in r.warnings)


def test_commit_body_without_bullet_fails():
    r = validate.validate_commit("feat: 뭔가 추가\n\n그냥 산문으로 썼습니다.")
    assert not r.ok
    assert any(i.rule == "body_quality" for i in r.issues)


def test_postprocess_commit_shortens_title():
    long_title = "feat: " + " ".join(["word"] * 40)
    out = validate.postprocess_commit(long_title)
    title, _ = validate.split_commit(out)
    assert len(title) <= validate.COMMIT_TITLE_MAX


def test_postprocess_commit_keeps_body():
    out = validate.postprocess_commit(GOOD_COMMIT)
    assert "- aigitgen/llm.py" in out


# ── PR ────────────────────────────────────────────────────────────────────

def test_good_pr_passes():
    assert validate.validate_pr(GOOD_PR).ok


def test_pr_missing_section_fails():
    bad = "feat: 뭔가\n\n## Why\n- 이유\n\n## What\n- 변경"
    r = validate.validate_pr(bad)
    assert not r.ok
    assert any("How to Test" in i.detail for i in r.issues)


def test_pr_section_without_bullet_fails():
    bad = "feat: 뭔가\n\n## Why\n이유를 산문으로\n\n## What\n- 변경\n\n## How to Test\n- 테스트"
    r = validate.validate_pr(bad)
    assert not r.ok
    assert any(i.rule == "pr_bullet" for i in r.issues)


def test_pr_title_over_80_fails():
    bad = "feat: " + "a" * 90 + "\n\n## Why\n- a\n\n## What\n- b\n\n## How to Test\n- c"
    r = validate.validate_pr(bad)
    assert not r.ok
    assert any(i.rule == "pr_title_max" for i in r.issues)


def test_pr_title_prefix_is_stripped():
    text = "PR Title: feat: 제목입니다\n\n## Why\n- a\n\n## What\n- b\n\n## How to Test\n- c"
    title, _ = validate.split_pr(text)
    assert title == "feat: 제목입니다"


def test_postprocess_pr_fills_missing_sections_without_inventing():
    bad = "feat: 뭔가\n\n## Why\n- 이유"
    out = validate.postprocess_pr(bad)
    assert "## What" in out and "## How to Test" in out
    # 없는 내용을 지어내지 않고 사람이 채우라는 표시를 남긴다
    assert "직접 채워주세요" in out


def test_postprocess_pr_converts_prose_to_bullets():
    bad = "feat: 뭔가\n\n## Why\n산문 이유\n\n## What\n- b\n\n## How to Test\n- c"
    out = validate.postprocess_pr(bad)
    assert validate.validate_pr(out).ok
    assert "- 산문 이유" in out


def test_postprocess_pr_output_always_valid():
    """후처리를 거친 결과는 반드시 검증을 통과해야 한다."""
    for bad in ["", "제목만", "feat: x\n\n## Why\n- a", "## What\n- b"]:
        assert validate.validate_pr(validate.postprocess_pr(bad)).ok
