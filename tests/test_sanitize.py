"""safe-mode 테스트. API 를 호출하지 않으므로 돈이 들지 않는다."""

from aigitgen import sanitize


def test_masks_anthropic_key():
    text = 'ANTHROPIC_API_KEY="sk-ant-api03-abcdefghijklmnop1234"'
    out, counts = sanitize.mask_secrets(text)
    assert "sk-ant-api03-abcdefghijklmnop1234" not in out
    assert "MASKED" in out
    assert counts


def test_masks_aws_access_key():
    out, counts = sanitize.mask_secrets("key = AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert counts["aws_access_key"] == 1


def test_masks_github_token():
    out, counts = sanitize.mask_secrets("ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert "abcdefghijklmnopqrstuvwxyz" not in out
    assert counts["github_token"] == 1


def test_masks_email_and_phone():
    out, counts = sanitize.mask_secrets("연락처: haeun@example.com / 010-1234-5678")
    assert "haeun@example.com" not in out
    assert "010-1234-5678" not in out
    assert counts["email"] == 1
    assert counts["phone_kr"] == 1


def test_masks_generic_secret_assignment():
    out, _ = sanitize.mask_secrets("DB_PASSWORD=supersecret123")
    assert "supersecret123" not in out


def test_leaves_ordinary_code_alone():
    code = "def add(a, b):\n    return a + b\n"
    out, counts = sanitize.mask_secrets(code)
    assert out == code
    assert counts == {}


def _fake_diff(n_files: int, lines_per_file: int) -> str:
    parts = []
    for i in range(n_files):
        body = "\n".join(f"+line {j}" for j in range(lines_per_file))
        parts.append(f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n{body}\n")
    return "".join(parts)


def test_limit_diff_by_file_count():
    diff = _fake_diff(n_files=20, lines_per_file=3)
    out, truncated = sanitize.limit_diff(diff, max_files=5, max_lines=10_000)
    assert truncated
    assert out.count("diff --git") == 5


def test_limit_diff_by_line_count():
    diff = _fake_diff(n_files=20, lines_per_file=50)
    out, truncated = sanitize.limit_diff(diff, max_files=100, max_lines=100)
    assert truncated
    # 제한 줄 수 + 안내 문구 몇 줄 이내여야 한다
    assert len(out.splitlines()) <= 100 + 3


def test_limit_diff_keeps_small_diff_whole():
    diff = _fake_diff(n_files=2, lines_per_file=3)
    out, truncated = sanitize.limit_diff(diff, max_files=10, max_lines=200)
    assert not truncated
    assert out == diff


def test_prepare_diff_masks_before_truncating():
    """순서가 중요하다. 자르기 전에 마스킹해야 보낸 것에 비밀값이 없다."""
    secret = "sk-ant-api03-SECRETSECRETSECRET123"
    head = f"diff --git a/a.py b/a.py\n+KEY = '{secret}'\n"
    tail = _fake_diff(n_files=30, lines_per_file=20)
    out, rep = sanitize.prepare_diff(head + tail, safe_mode=True, max_files=2, max_lines=20)
    assert secret not in out
    assert rep.masked_total >= 1
    assert rep.truncated


def test_prepare_diff_off_passes_through():
    diff = _fake_diff(n_files=3, lines_per_file=3)
    out, rep = sanitize.prepare_diff(diff, safe_mode=False, max_files=1, max_lines=1)
    assert out == diff
    assert rep.masked_total == 0
    assert not rep.truncated


# ── 오탐 회귀 테스트 (2026-11-09) ─────────────────────────────────────────
# 느슨한 KEY=VALUE 규칙이 평범한 코드까지 마스킹했다. 다시 생기면 여기서 잡힌다.

def test_does_not_mask_function_call():
    for code in [
        "api_key = resolve_api_key()",
        "client = anthropic.Anthropic(api_key=api_key)",
        "token = get_token()",
    ]:
        out, counts = sanitize.mask_secrets(code)
        assert out == code, f"오탐: {code} → {out}"
        assert counts == {}


def test_does_not_mask_variable_name_tuple():
    code = 'API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "AI_API_KEY")'
    out, _ = sanitize.mask_secrets(code)
    assert out == code


def test_still_masks_quoted_literal():
    out, _ = sanitize.mask_secrets('ANTHROPIC_API_KEY="sk-ant-api03-REALSECRET1234"')
    assert "REALSECRET" not in out


def test_still_masks_bare_env_value():
    out, _ = sanitize.mask_secrets("DB_PASSWORD=supersecret123")
    assert "supersecret123" not in out
