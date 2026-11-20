"""AI API 연동 층 (과제 요구사항 2번 / 과제 목표 1·2번).

요청 구성 → 응답 처리 → 예외 대응 의 전체 흐름이 이 파일 안에 있다.

## temperature 에 대한 중요한 사실 (2026-11 확인)

과제는 `temperature` 를 CLI 옵션으로 제공하라고 요구한다. 그런데 **현재
Claude 모델들은 `temperature` 를 받으면 400 에러를 돌려준다.** 샘플링
파라미터(`temperature`/`top_p`/`top_k`)가 제거됐고, 그 자리를
`output_config.effort` 가 대신한다.

| 모델 | temperature |
|---|---|
| claude-opus-5-5 / claude-sonnet-5-5 / claude-fable-5-1 | 제거됨 (400) |
| claude-haiku-5-5 | 기본값 외 400 |
| claude-haiku-4-5 / claude-sonnet-4-5 등 구세대 | 허용 |

그래서 이 도구는 이렇게 처리한다.
  - `--temperature` 옵션은 **과제 요구대로 제공**한다.
  - 모델이 받아주는 경우에만 실제로 전송한다.
  - 받지 않는 모델이면 **보내지 않고 경고를 출력**하면서 `--effort` 를 안내한다.
  - `--legacy-temperature` 를 주면 **일부러 그대로 전송**한다. 400 에러가
    어떻게 생기는지 직접 볼 수 있다(평가 시연용).

두 파라미터는 성격이 다르다. 혼동하면 안 된다.
  - `temperature`: 다음 토큰을 고를 때의 **무작위성**. 낮으면 매번 비슷한
    답, 높으면 다양하지만 들쭉날쭉. 커밋 메시지처럼 정형화된 출력에는 낮은 값이 맞다.
  - `effort`: 모델이 **얼마나 깊게 생각할지**와 토큰 예산. 낮으면 빠르고 싸고,
    높으면 느리고 비싸지만 복잡한 변경을 더 잘 요약한다.
  - `max_tokens`: **출력 길이 상한**. 품질 조절 장치가 아니라 안전장치다.
    너무 낮으면 문장 중간에서 잘린다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 기본 모델. 바꾸려면 --model 을 쓴다.
DEFAULT_MODEL = "claude-opus-5-5"          # Anthropic 직접 호출일 때
DEFAULT_MAX_TOKENS = 1024
DEFAULT_EFFORT = "low"          # 커밋 메시지 요약은 깊은 추론이 필요 없다
DEFAULT_TEMPERATURE = 0.2

# ── 코디세이 공용 API (2026-11-20 추가) ──────────────────────────────────
#
# 코디세이가 교육생에게 월 500만 토큰을 무료로 준다. 엔드포인트가 **Anthropic
# Messages API 규격과 호환**이라, anthropic SDK 를 그대로 쓸 수 있다.
# SDK 가 ANTHROPIC_BASE_URL 환경변수를 자동으로 읽으므로 호출 코드는 손댈 게 없다.
#
#   export ANTHROPIC_BASE_URL="https://copa.codyssey.kr"
#   export ANTHROPIC_API_KEY="(코디세이 API 콘솔에서 발급)"
#
# 다만 **모델 이름이 다르다.** Anthropic 의 claude-opus-5-5 는 여기 없다.
# 그래서 base URL 을 보고 기본 모델을 바꾼다.
CODYSSEY_BASE_HINT = "codyssey"
DEFAULT_MODEL_CODYSSEY = "claude-haiku-4"   # 차감 배수 0.5배 — 가장 적게 깎인다

# 코디세이는 달러가 아니라 **토큰을 차감**한다. 모델마다 배수가 다르다.
CODYSSEY_MULTIPLIERS: dict[str, float] = {
    "claude-haiku-4": 0.5,
    "claude-sonnet-4": 1.0,
}
CODYSSEY_MONTHLY_TOKENS = 5_000_000


def resolve_base_url() -> str | None:
    """ANTHROPIC_BASE_URL 을 읽는다. 없으면 None (= Anthropic 직접 호출)."""
    return os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None


def is_codyssey(base_url: str | None = None) -> bool:
    """코디세이 공용 API 를 쓰고 있는가."""
    if base_url is None:
        base_url = resolve_base_url()
    return bool(base_url) and CODYSSEY_BASE_HINT in base_url.lower()


def default_model() -> str:
    """지금 환경에 맞는 기본 모델.

    코디세이 API 를 쓰는 중이면 거기 있는 모델을, 아니면 Anthropic 모델을 돌려준다.
    이걸 안 하면 코디세이 환경에서 기본값 claude-opus-5-5 로 404 가 난다.
    """
    return DEFAULT_MODEL_CODYSSEY if is_codyssey() else DEFAULT_MODEL

# 1M 토큰당 (입력 / 출력) 달러. 2026-10 기준. Anthropic 직접 호출일 때만 의미가 있다.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
}

# temperature 를 받아주는 모델. 그 밖의 모델은 400 을 낸다.
MODELS_ACCEPTING_TEMPERATURE: frozenset[str] = frozenset(
    {"claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5"}
)

# effort 를 지원하는 모델. 구세대는 지원하지 않는다.
MODELS_ACCEPTING_EFFORT: frozenset[str] = frozenset(
    {
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
        "claude-opus-5",
    }
)

API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "AI_API_KEY")


class LLMError(RuntimeError):
    """호출 실패. 원인을 메시지에 담는다."""


class MissingAPIKey(LLMError):
    pass


@dataclass
class Usage:
    """비용 추적용. 제약 사항이 '호출 횟수를 로그에 출력' 하라고 요구한다."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    notes: list[str] = field(default_factory=list)

    def codyssey_tokens(self, model: str) -> float | None:
        """코디세이에서 실제로 깎이는 토큰 수. 배수를 모르는 모델이면 None."""
        mult = CODYSSEY_MULTIPLIERS.get(model)
        if mult is None:
            return None
        return (self.input_tokens + self.output_tokens) * mult

    def cost_usd(self, model: str) -> float | None:
        price = MODEL_PRICING.get(model)
        if price is None:
            return None
        pin, pout = price
        return self.input_tokens / 1_000_000 * pin + self.output_tokens / 1_000_000 * pout


def resolve_api_key() -> str:
    """환경변수에서만 키를 읽는다. 코드에 하드코딩하지 않는다(제약 사항).

    과제 예시는 `AI_API_KEY` 를 쓰고 Anthropic SDK 표준은 `ANTHROPIC_API_KEY` 다.
    둘 다 받아준다.
    """
    for name in API_KEY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise MissingAPIKey(
        "AI API Key 환경변수가 설정되지 않았습니다.\n"
        '  예) export ANTHROPIC_API_KEY="YOUR_KEY"\n'
        f"  허용되는 변수명: {', '.join(API_KEY_ENV_VARS)}"
    )


@dataclass
class CallConfig:
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    effort: str = DEFAULT_EFFORT
    temperature: float = DEFAULT_TEMPERATURE
    temperature_explicit: bool = False   # 사용자가 직접 지정했는가
    legacy_temperature: bool = False     # 그대로 전송할 것인가


def _build_kwargs(cfg: CallConfig, system: str, user: str, usage: Usage) -> dict:
    """요청 본문을 조립한다. 모델별로 받아주는 파라미터가 다르다."""
    kwargs: dict = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    if cfg.model in MODELS_ACCEPTING_EFFORT:
        kwargs["output_config"] = {"effort": cfg.effort}

    send_temp = cfg.legacy_temperature or (cfg.model in MODELS_ACCEPTING_TEMPERATURE)
    if send_temp:
        kwargs["temperature"] = cfg.temperature
    elif cfg.temperature_explicit:
        usage.notes.append(
            f"--temperature {cfg.temperature} 는 전송하지 않았습니다. "
            f"{cfg.model} 은 샘플링 파라미터를 더 이상 받지 않습니다(400). "
            f"품질은 --effort 로 조절하세요 (현재 {cfg.effort}). "
            "일부러 전송해 400 을 보려면 --legacy-temperature 를 쓰세요."
        )
    return kwargs


def call(system: str, user: str, cfg: CallConfig, usage: Usage) -> str:
    """API 를 1회 호출하고 텍스트를 돌려준다.

    예외는 **구체적인 것부터** 잡는다. 하나로 뭉쳐 잡으면 "재시도하면 되는
    오류(429, 5xx, 네트워크)"와 "고쳐야 하는 오류(400, 401, 404)"를 구분할 수 없다.
    """
    # 키 검사를 패키지 import 보다 **먼저** 한다.
    # 그러지 않으면 패키지가 없는 환경에서 "키가 없다"는 안내가 묻혀버린다
    # (2026-11-07 실측: ImportError 가 먼저 떠서 과제 7쪽의 출력 예시가 재현되지 않았다).
    api_key = resolve_api_key()

    try:
        import anthropic
    except ImportError as exc:
        raise LLMError(
            "anthropic 패키지가 없습니다. `pip install -r requirements.txt` 를 먼저 실행하세요."
        ) from exc

    client = anthropic.Anthropic(api_key=api_key)
    kwargs = _build_kwargs(cfg, system, user, usage)

    try:
        response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        # 어디서 키를 확인해야 하는지는 **어느 엔드포인트를 쓰느냐**에 따라 다르다.
        # 코디세이를 쓰는데 console.anthropic.com 을 안내하면 엉뚱한 곳을 보게 된다.
        where = (
            "코디세이 플랫폼 → API 콘솔 → 내 API 키 에서 확인하세요."
            if is_codyssey()
            else "console.anthropic.com → API Keys 에서 키를 확인하세요."
        )
        raise LLMError(
            "인증 실패 (401). API 키가 올바르지 않거나 만료됐습니다.\n"
            f"  {where}\n"
            f"  (현재 엔드포인트: {resolve_base_url() or 'api.anthropic.com (기본)'})\n"
            f"  원인: {exc}"
        ) from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMError(f"권한 없음 (403). 키에 이 모델 사용 권한이 없습니다.\n  원인: {exc}") from exc
    except anthropic.NotFoundError as exc:
        hint = ""
        if is_codyssey():
            hint = (
                f"\n  힌트: 코디세이 공용 API 에는 Anthropic 모델 이름이 그대로 없습니다. "
                f"{', '.join(sorted(CODYSSEY_MULTIPLIERS))} 중에서 고르세요."
            )
        elif cfg.model in CODYSSEY_MULTIPLIERS:
            hint = (
                f"\n  힌트: '{cfg.model}' 은 코디세이 공용 API 모델입니다. "
                'ANTHROPIC_BASE_URL="https://copa.codyssey.kr" 를 설정했는지 확인하세요.'
            )
        raise LLMError(
            f"모델을 찾을 수 없습니다 (404): {cfg.model}\n"
            "  --model 값을 확인하세요. 사용 가능한 모델은 README 를 참고하세요.\n"
            f"  (현재 엔드포인트: {resolve_base_url() or 'api.anthropic.com (기본)'})"
            f"{hint}\n"
            f"  원인: {exc}"
        ) from exc
    except anthropic.BadRequestError as exc:
        hint = ""
        if "temperature" in str(exc).lower():
            hint = (
                "\n  힌트: 이 모델은 temperature 를 받지 않습니다. "
                "--legacy-temperature 를 빼고 --effort 로 조절하세요."
            )
        raise LLMError(f"요청이 잘못됐습니다 (400).\n  원인: {exc}{hint}") from exc
    except anthropic.RateLimitError as exc:
        retry_after = "60"
        try:
            retry_after = exc.response.headers.get("retry-after", "60")
        except Exception:  # noqa: BLE001 - 헤더가 없을 수도 있다
            pass
        raise LLMError(
            f"요청이 너무 많습니다 (429). {retry_after}초 뒤에 다시 시도하세요.\n  원인: {exc}"
        ) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise LLMError(
                f"서버 오류 ({exc.status_code}). 잠시 뒤 다시 시도하세요.\n  원인: {exc}"
            ) from exc
        raise LLMError(f"API 오류 ({exc.status_code}).\n  원인: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(
            "네트워크 오류. 인터넷 연결 또는 프록시 설정을 확인하세요.\n"
            f"  원인: {exc}"
        ) from exc

    usage.calls += 1
    if getattr(response, "usage", None):
        usage.input_tokens += response.usage.input_tokens or 0
        usage.output_tokens += response.usage.output_tokens or 0

    # 안전 점검 — 거절이나 길이 초과를 조용히 넘기지 않는다.
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        raise LLMError("모델이 이 요청을 거절했습니다(stop_reason=refusal). 변경 내용을 확인하세요.")
    if stop == "max_tokens":
        usage.notes.append(
            f"출력이 max_tokens({cfg.max_tokens})에 걸려 잘렸습니다. --max-tokens 를 늘리세요."
        )

    # 응답 처리 — content 는 블록 목록이다. text 블록만 모은다.
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    text = "\n".join(parts).strip()
    if not text:
        raise LLMError("응답에 텍스트가 없습니다. --max-tokens 를 늘려 다시 시도하세요.")
    return text
