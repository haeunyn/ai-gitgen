"""전체 흐름 테스트 — API 를 가짜로 바꿔서 돌린다. 비용 0.

검증·재생성·후처리가 맞물려 도는지, 호출 횟수가 제약(1~2회)을 지키는지 본다.
실제 API 를 부르는 테스트는 돈이 들고 결과가 매번 달라서 자동화에 맞지 않는다.
"""

from __future__ import annotations

import main as cli
from aigitgen import llm


class FakeAPI:
    """정해진 답을 순서대로 돌려주는 가짜 API."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def __call__(self, system: str, user: str, cfg: llm.CallConfig, usage: llm.Usage) -> str:
        self.prompts.append(user)
        usage.calls += 1
        usage.input_tokens += 100
        usage.output_tokens += 20
        if not self.responses:
            raise AssertionError("가짜 API 가 예상보다 많이 호출됐습니다")
        return self.responses.pop(0)


GOOD_COMMIT = "feat: 커밋 생성 기능 추가\n\n- aigitgen/llm.py 에 호출 래퍼 추가"
# 72자(최대치)를 확실히 넘겨야 '실패'다. 50자는 권장치일 뿐이라 경고만 난다.
BAD_COMMIT = "feat: " + "매우긴제목 " * 20
GOOD_PR = (
    "feat: 커밋/PR 자동 생성\n\n"
    "## Why\n- 시간이 걸려서\n\n## What\n- gitctl.py 추가\n\n## How to Test\n- python main.py commit"
)
BAD_PR = "feat: 제목\n\n## Why\n- 이유만 있고 나머지 섹션이 없습니다"


def _run(monkeypatch, responses, kind="commit", allow_retry=True):
    fake = FakeAPI(responses)
    monkeypatch.setattr(llm, "call", fake)
    usage = llm.Usage()
    text = cli._generate(
        kind=kind,
        system="sys",
        user="user",
        cfg=llm.CallConfig(),
        usage=usage,
        allow_retry=allow_retry,
    )
    return text, usage, fake


def test_good_first_try_uses_one_call(monkeypatch):
    text, usage, _ = _run(monkeypatch, [GOOD_COMMIT])
    assert usage.calls == 1
    assert text == GOOD_COMMIT


def test_bad_then_good_uses_two_calls(monkeypatch):
    text, usage, fake = _run(monkeypatch, [BAD_COMMIT, GOOD_COMMIT])
    assert usage.calls == 2
    assert text == GOOD_COMMIT
    # 재생성 요청에는 '무엇이 틀렸는지'가 들어가야 한다
    assert "위반 내용" in fake.prompts[1]
    assert "직전 출력" in fake.prompts[1]


def test_never_exceeds_two_calls(monkeypatch):
    """제약 사항: 1회 실행 시 요청 횟수는 1~2회 이내."""
    text, usage, _ = _run(monkeypatch, [BAD_COMMIT, BAD_COMMIT])
    assert usage.calls == 2            # 3회 이상 부르지 않는다
    from aigitgen import validate
    assert validate.validate_commit(text).ok   # 후처리로 형식은 맞춰진다


def test_no_retry_flag_uses_one_call(monkeypatch):
    text, usage, _ = _run(monkeypatch, [BAD_COMMIT], allow_retry=False)
    assert usage.calls == 1
    from aigitgen import validate
    assert validate.validate_commit(text).ok


def test_pr_flow(monkeypatch):
    text, usage, _ = _run(monkeypatch, [GOOD_PR], kind="pr")
    assert usage.calls == 1
    from aigitgen import validate
    assert validate.validate_pr(text).ok


def test_pr_bad_then_postprocess(monkeypatch):
    text, usage, _ = _run(monkeypatch, [BAD_PR, BAD_PR], kind="pr")
    assert usage.calls == 2
    from aigitgen import validate
    assert validate.validate_pr(text).ok
    assert "## How to Test" in text


def test_cost_is_computed(monkeypatch):
    _, usage, _ = _run(monkeypatch, [GOOD_COMMIT])
    cost = usage.cost_usd("claude-haiku-5-5")
    assert cost is not None and cost > 0
    assert usage.cost_usd("made-up-model") is None


# ── 파라미터 조립 ──────────────────────────────────────────────────────────

def test_effort_sent_to_supporting_model():
    usage = llm.Usage()
    kwargs = llm._build_kwargs(
        llm.CallConfig(model="claude-opus-5-5", effort="high"), "s", "u", usage
    )
    assert kwargs["output_config"] == {"effort": "high"}
    assert "temperature" not in kwargs


def test_temperature_not_sent_to_current_model_but_warned():
    usage = llm.Usage()
    cfg = llm.CallConfig(model="claude-opus-5-5", temperature=0.9, temperature_explicit=True)
    kwargs = llm._build_kwargs(cfg, "s", "u", usage)
    assert "temperature" not in kwargs          # 400 을 피한다
    assert usage.notes and "temperature" in usage.notes[0]


def test_temperature_sent_to_legacy_model():
    usage = llm.Usage()
    cfg = llm.CallConfig(model="claude-haiku-4-5", temperature=0.7, temperature_explicit=True)
    kwargs = llm._build_kwargs(cfg, "s", "u", usage)
    assert kwargs["temperature"] == 0.7
    assert "output_config" not in kwargs        # 구세대는 effort 를 모른다


def test_legacy_temperature_forces_send():
    """일부러 전송해 400 을 보여주는 시연용 옵션."""
    usage = llm.Usage()
    cfg = llm.CallConfig(model="claude-opus-5-5", temperature=0.5, legacy_temperature=True)
    kwargs = llm._build_kwargs(cfg, "s", "u", usage)
    assert kwargs["temperature"] == 0.5
