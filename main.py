#!/usr/bin/env python3
"""ai-gitgen — Git 변경 사항으로 커밋 메시지와 PR 초안을 만드는 CLI.

사용법
    python main.py commit      # 커밋 메시지 생성
    python main.py pr          # PR 제목/본문 초안 생성
    python main.py preview     # API 를 부르지 않고 '무엇을 보낼지'만 확인 (무료)

자세한 옵션은 `python main.py commit --help` 를 보세요.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aigitgen import gitctl, llm, prompts, render, sanitize, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-gitgen",
        description="Git 변경 사항으로 커밋 메시지와 PR 초안을 생성합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        # ── API 호출 파라미터 (요구사항 2번: CLI 옵션으로 변경 가능해야 한다)
        g = p.add_argument_group("API 파라미터")
        g.add_argument("--model", default=llm.DEFAULT_MODEL,
                       help=f"사용할 모델 (기본 {llm.DEFAULT_MODEL})")
        g.add_argument("--max-tokens", type=int, default=llm.DEFAULT_MAX_TOKENS,
                       help=f"출력 길이 상한 (기본 {llm.DEFAULT_MAX_TOKENS})")
        g.add_argument("--effort", default=llm.DEFAULT_EFFORT,
                       choices=["low", "medium", "high", "xhigh", "max"],
                       help=f"생각 깊이 / 토큰 예산 (기본 {llm.DEFAULT_EFFORT})")
        g.add_argument("--temperature", type=float, default=None,
                       help="샘플링 무작위성. 최신 모델은 받지 않으므로 무시되고 경고가 나옵니다.")
        g.add_argument("--legacy-temperature", action="store_true",
                       help="--temperature 를 그대로 전송합니다(400 확인용).")

        # ── safe-mode (제약 사항: 아래 중 1개 이상)
        s = p.add_argument_group("safe-mode")
        s.add_argument("--safe-mode", dest="safe_mode", action="store_true", default=True,
                       help="민감정보 마스킹 + diff 전송량 제한 (기본 켜짐)")
        s.add_argument("--no-safe-mode", dest="safe_mode", action="store_false",
                       help="safe-mode 끄기. diff 를 손대지 않고 전송합니다.")
        s.add_argument("--max-files", type=int, default=10,
                       help="전송할 최대 파일 수 (기본 10)")
        s.add_argument("--max-lines", type=int, default=200,
                       help="전송할 최대 diff 줄 수 (기본 200)")

        # ── 기타
        o = p.add_argument_group("기타")
        o.add_argument("--staged", dest="staged", action="store_true", default=None,
                       help="staged(--cached) 변경만 본다")
        o.add_argument("--unstaged", dest="staged", action="store_false",
                       help="unstaged 변경만 본다")
        o.add_argument("--convention", type=Path, default=None,
                       help="팀 컨벤션 파일 경로. 내용을 프롬프트에 덧붙입니다.")
        o.add_argument("--no-retry", action="store_true",
                       help="형식 위반 시 재생성하지 않고 바로 후처리합니다(호출 1회로 고정).")

    for name, help_text in [
        ("commit", "커밋 메시지를 생성합니다"),
        ("pr", "PR 제목/본문 초안을 생성합니다"),
        ("preview", "API 를 호출하지 않고 전송될 내용만 보여줍니다"),
    ]:
        p = sub.add_parser(name, help=help_text)
        add_common(p)

    return parser


def _load_convention(path: Path | None) -> str | None:
    if path is None:
        return None
    if not path.is_file():
        render.warn(f"컨벤션 파일을 찾을 수 없습니다: {path} (무시하고 계속합니다)")
        return None
    return path.read_text(encoding="utf-8")


def _report_sanitize(rep: sanitize.SanitizeReport, safe_mode: bool) -> None:
    if not safe_mode:
        render.warn("safe-mode 가 꺼져 있습니다. diff 가 손대지 않은 상태로 전송됩니다.")
        return
    if rep.masked_total:
        detail = ", ".join(f"{k} {v}건" for k, v in sorted(rep.masked_counts.items()))
        render.info(f"민감정보 마스킹: 총 {rep.masked_total}건 ({detail})")
    else:
        render.info("민감정보 마스킹: 해당 패턴 없음")
    if rep.truncated:
        render.warn(
            f"diff 가 잘렸습니다: {rep.files_total}개 파일 / {rep.lines_total}줄 중 "
            f"{rep.files_sent}개 파일 / {rep.lines_sent}줄만 전송 "
            "(--max-files, --max-lines 로 조절)"
        )


def _generate(
    *,
    kind: str,
    system: str,
    user: str,
    cfg: llm.CallConfig,
    usage: llm.Usage,
    allow_retry: bool,
) -> str:
    """1회 호출 → 검증 → (필요하면 1회 재생성) → 그래도 안 되면 후처리."""
    validator = validate.validate_commit if kind == "commit" else validate.validate_pr
    postprocessor = validate.postprocess_commit if kind == "commit" else validate.postprocess_pr

    render.info(f"AI API 요청 중... (모델 {cfg.model}, effort {cfg.effort})")
    text = llm.call(system, user, cfg, usage)
    result = validator(text)

    if not result.ok and allow_retry:
        render.warn("형식 규칙 위반을 발견했습니다. 1회 재생성합니다.")
        for issue in result.issues:
            render.warn(f"  · {issue.detail}")
        retry = prompts.retry_user(user, text, result.feedback())
        text = llm.call(system, retry, cfg, usage)
        result = validator(text)

    if not result.ok:
        render.warn("재생성 후에도 규칙을 만족하지 않아 후처리로 형식을 맞췄습니다.")
        for issue in result.issues:
            render.warn(f"  · {issue.detail}")
        text = postprocessor(text)

    for w in result.warnings:
        render.warn(w.detail)

    return text


def _usage_footer(usage: llm.Usage, model: str) -> None:
    render.section("호출 정보")
    print(f"  API 호출 횟수 : {usage.calls}회")
    print(f"  입력 토큰     : {usage.input_tokens:,}")
    print(f"  출력 토큰     : {usage.output_tokens:,}")
    cost = usage.cost_usd(model)
    if cost is not None:
        print(f"  예상 비용     : ${cost:.5f} ({model})")
    else:
        print(f"  예상 비용     : (모델 {model} 단가 정보 없음)")
    for note in usage.notes:
        render.warn(note)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ── 1. Git 변경 사항 수집
    try:
        gitctl.ensure_git_repo(".")
        changes = gitctl.collect(".", staged=args.staged)
        branch = gitctl.current_branch(".")
    except gitctl.GitError as exc:
        render.error(str(exc))
        return 1

    if changes.is_empty:
        render.info("변경 사항이 없습니다. 생성하지 않고 종료합니다.")
        return 0

    render.info(f"Git status 수집 완료: {len(changes.files)}개 파일 변경 감지"
                f" ({'staged' if changes.staged else 'unstaged'})")
    render.info(f"Git diff 수집 완료: {changes.diff_line_count}줄")
    if args.command == "pr":
        render.info(f"현재 브랜치: {branch}")

    # ── 2. safe-mode
    diff_for_prompt, rep = sanitize.prepare_diff(
        changes.diff_text,
        safe_mode=args.safe_mode,
        max_files=args.max_files,
        max_lines=args.max_lines,
    )
    _report_sanitize(rep, args.safe_mode)

    convention = _load_convention(args.convention)

    if args.command == "commit":
        system = prompts.COMMIT_SYSTEM
        user = prompts.commit_user(changes, diff_for_prompt, convention)
    else:
        system = prompts.PR_SYSTEM
        user = prompts.pr_user(changes, diff_for_prompt, branch, convention)

    # ── preview: 돈을 쓰지 않고 '무엇을 보낼지' 확인
    if args.command == "preview":
        render.block("SYSTEM PROMPT", system)
        render.block("USER PROMPT (실제 전송 내용)", user)
        render.info("preview 는 API 를 호출하지 않았습니다. 비용 0.")
        return 0

    # ── 3·4. 생성
    cfg = llm.CallConfig(
        model=args.model,
        max_tokens=args.max_tokens,
        effort=args.effort,
        temperature=args.temperature if args.temperature is not None else llm.DEFAULT_TEMPERATURE,
        temperature_explicit=args.temperature is not None,
        legacy_temperature=args.legacy_temperature,
    )
    usage = llm.Usage()

    try:
        text = _generate(
            kind=args.command,
            system=system,
            user=user,
            cfg=cfg,
            usage=usage,
            allow_retry=not args.no_retry,
        )
    except llm.MissingAPIKey as exc:
        render.error(str(exc))
        return 2
    except llm.LLMError as exc:
        render.error(str(exc))
        if usage.calls:
            _usage_footer(usage, args.model)
        return 3

    # ── 5. 출력 구획
    if args.command == "commit":
        render.done("커밋 메시지 생성 완료")
        title, body = validate.split_commit(text)
        render.block("Commit Message", text)
        render.info(f"제목 길이: {len(title)}자 "
                    f"(권장 {validate.COMMIT_TITLE_RECOMMENDED} / 최대 {validate.COMMIT_TITLE_MAX})")
    else:
        render.done("PR 초안 생성 완료")
        title, body = validate.split_pr(text)
        render.block("PR Title", title)
        render.block("PR Body", body)
        render.info(f"제목 길이: {len(title)}자 (최대 {validate.PR_TITLE_MAX})")

    _usage_footer(usage, args.model)
    print()
    render.warn("생성된 문구는 최종 정답이 아닙니다. 검토 후 적용하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
