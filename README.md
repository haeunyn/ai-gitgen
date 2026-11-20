# ai-gitgen

Git 변경 사항을 읽어서 **커밋 메시지**와 **Pull Request 초안**을 만들어 주는 터미널 도구입니다.

`git status` 와 `git diff` 결과를 수집해 Claude API 에 넘기고, 돌아온 텍스트가
길이·형식 규칙을 만족하는지 검증한 뒤 터미널에 출력합니다. 생성된 문구는 초안이고,
적용 여부는 사람이 판단합니다.

> 코디세이 도구학습 미션 **「내가 고친 코드 설명을 AI가 대신 써주는 도우미 만들기」** 결과물입니다.

> 📖 **[동료평가 설명서 — 요구사항별 설명](docs/동료평가_설명서.md)**
> 과제 요구사항을 하나씩 뜯어서, 항목마다 ① 확인할 것 ② 실행할 명령
> ③ 나올 결과 ④ **설명할 내용**을 정리해 두었습니다.

---

## 설치

Python 3.10 이상이 필요합니다. (개발·검증은 3.12.14 에서 했습니다)

```bash
git clone https://github.com/haeunyn/ai-gitgen.git
cd ai-gitgen
pip install -r requirements.txt
```

`requirements.txt` 는 `anthropic` 한 줄입니다. 웹 서버나 프레임워크는 쓰지 않습니다.

---

## 환경변수 (API Key) 설정

**API 키는 환경변수로만 관리합니다. 코드에 적지 않습니다.**

### 방법 1 — 코디세이 공용 API (권장)

코디세이가 교육생에게 **월 500만 토큰**을 제공합니다. 개인 비용이 들지 않습니다.
엔드포인트가 **Anthropic Messages API 규격과 호환**이라 코드를 고칠 필요가 없습니다.

```bash
export ANTHROPIC_BASE_URL="https://copa.codyssey.kr"
export ANTHROPIC_API_KEY="(코디세이 플랫폼 → API 콘솔 → 키 발급)"

python main.py commit        # 기본 모델이 claude-haiku-4 로 자동 전환됩니다
```

`ANTHROPIC_BASE_URL` 은 **anthropic SDK 가 알아서 읽습니다.** 이 도구는 그 값을 보고
**기본 모델을 바꿉니다** — Anthropic 의 `claude-opus-5-5` 는 코디세이에 없기 때문입니다.

| 코디세이 모델 | 차감 배수 | 비고 |
|---|---|---|
| **`claude-haiku-4`** | **0.5배** | 기본값. diff 요약에 충분하고 가장 적게 깎입니다 |
| `claude-sonnet-4` | 1.0배 | 변경이 복잡할 때 |

실행하면 달러 대신 **차감 토큰**을 보여줍니다.

```
  차감 토큰     : 1,272 (배수 0.5배, claude-haiku-4)
  월 할당       : 5,000,000 (코디세이 공용 API)
```

### 방법 2 — Anthropic 직접 호출

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

`AI_API_KEY` 도 받습니다. 둘 다 있으면 `ANTHROPIC_API_KEY` 가 우선입니다.

| 변수명 | 우선순위 |
|---|---|
| `ANTHROPIC_API_KEY` | 1 (Anthropic SDK 표준) |
| `AI_API_KEY` | 2 |

### 셸을 새로 열어도 유지하려면

`~/.zshrc` 에 `export` 를 적는 방법이 흔하지만, **키가 평문으로 홈 디렉토리에 남습니다.**
macOS 라면 키체인에 넣고 필요할 때만 꺼내 쓰는 쪽이 안전합니다.

```bash
# 한 번만: 키체인에 저장
security add-generic-password -a "$USER" -s anthropic-api-key -w

# 쓸 때마다: 환경변수로 꺼내기 (~/.zshrc 에 함수로 넣어두면 편합니다)
export ANTHROPIC_API_KEY=$(security find-generic-password -s anthropic-api-key -w)
```

키를 설정하지 않고 실행하면 이렇게 안내합니다.

```
$ python main.py commit
[ERROR] AI API Key 환경변수가 설정되지 않았습니다.
  예) export ANTHROPIC_API_KEY="YOUR_KEY"
  허용되는 변수명: ANTHROPIC_API_KEY, AI_API_KEY
```

---

## 사용법

**git 이 초기화된 프로젝트 루트에서** 실행합니다.

```bash
python main.py commit                   # 커밋 메시지 생성
python main.py pr                       # PR 제목/본문 초안 생성
python main.py preview                  # API 호출 없이 '무엇을 보낼지'만 확인 (무료)
python main.py preview --for pr         # PR 쪽 프롬프트 확인
```

`commit --help` 로 전체 옵션을 볼 수 있습니다.

### API 파라미터

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model` | `claude-opus-5-5` | 사용할 모델 |
| `--max-tokens` | `1024` | 출력 길이 상한 |
| `--effort` | `low` | 생각 깊이 / 토큰 예산 (`low`~`max`) |
| `--temperature` | — | 샘플링 무작위성. **아래 설명 참고** |
| `--legacy-temperature` | 꺼짐 | `--temperature` 를 그대로 전송 (400 확인용) |

### safe-mode

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--safe-mode` / `--no-safe-mode` | **켜짐** | 민감정보 마스킹 + diff 전송량 제한 |
| `--max-files` | `10` | 전송할 최대 파일 수 |
| `--max-lines` | `200` | 전송할 최대 diff 줄 수 |

### 기타

| 옵션 | 설명 |
|---|---|
| `--staged` / `--unstaged` | 볼 범위 지정. 기본은 staged 가 있으면 staged, 없으면 unstaged |
| `--convention <파일>` | 팀 컨벤션 파일 내용을 프롬프트에 덧붙입니다 |
| `--no-retry` | 형식 위반 시 재생성하지 않고 바로 후처리 (호출 1회로 고정) |

---

## ⚠️ `temperature` 에 대해 — 중요

**현재 Claude 모델들은 `temperature` 를 받으면 400 에러를 돌려줍니다.**
샘플링 파라미터(`temperature` / `top_p` / `top_k`)가 제거되고 그 자리를
`output_config.effort` 가 대신합니다. (2026-11 확인)

| 모델 | `temperature` |
|---|---|
| `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-fable-5-1` | 제거됨 (400) |
| `claude-haiku-5-5` | 기본값 외 400 |
| `claude-haiku-4-5`, `claude-sonnet-4-5` 등 구세대 | 허용 |

이 도구는 `--temperature` 옵션을 제공하되, **모델이 받아주는 경우에만 실제로 전송**합니다.
받지 않는 모델이면 보내지 않고 경고를 출력합니다.

```
[WARN] --temperature 0.9 는 전송하지 않았습니다. claude-opus-5-5 은 샘플링
       파라미터를 더 이상 받지 않습니다(400). 품질은 --effort 로 조절하세요
       (현재 low). 일부러 전송해 400 을 보려면 --legacy-temperature 를 쓰세요.
```

### 세 파라미터는 성격이 다릅니다

| 파라미터 | 무엇을 조절하나 | 이 도구에서 |
|---|---|---|
| `temperature` | 다음 토큰을 고를 때의 **무작위성**. 낮으면 매번 비슷한 답, 높으면 다양하지만 들쭉날쭉 | 커밋 메시지는 정형화된 출력이라 낮은 값이 맞습니다. 다만 최신 모델에선 쓸 수 없습니다 |
| `effort` | 모델이 **얼마나 깊게 생각할지**와 토큰 예산 | 기본 `low`. diff 요약에는 깊은 추론이 필요 없습니다. 변경이 복잡하면 `medium` 이상 |
| `max_tokens` | **출력 길이 상한** | 품질 조절 장치가 아니라 안전장치입니다. 너무 낮으면 문장 중간에서 잘립니다 |

---

## 출력 예시

> 🔄 **아래는 형식 예시입니다.** 실제 API 를 호출해 얻은 출력으로 교체해야 합니다.
> 지어낸 결과를 실측인 것처럼 적지 않으려고 표시해 뒀습니다.

### 커밋 메시지

```
$ python main.py commit
[INFO] Git status 수집 완료: 3개 파일 변경 감지 (staged)
[INFO] Git diff 수집 완료: 128줄
[INFO] 민감정보 마스킹: 해당 패턴 없음
[INFO] AI API 요청 중... (모델 claude-opus-5-5, effort low)
[DONE] 커밋 메시지 생성 완료

--- Commit Message -----------------------------------------------------
feat: diff 기반 커밋 메시지 자동 생성 기능 추가

- aigitgen/gitctl.py 에 status/diff 수집 로직 추가
- aigitgen/llm.py 에 Anthropic API 호출 및 예외 처리 추가
- 커밋 제목 길이 검증(50/72자) 추가
------------------------------------------------------------------------
[INFO] 제목 길이: 34자 (권장 50 / 최대 72)

========================================================================
 호출 정보
========================================================================
  API 호출 횟수 : 1회
  입력 토큰     : 2,431
  출력 토큰     : 112
  예상 비용     : $0.00196 (claude-opus-5-5)

[WARN] 생성된 문구는 최종 정답이 아닙니다. 검토 후 적용하세요.
```

### PR 초안

```
$ python main.py pr
[INFO] Git status 수집 완료: 3개 파일 변경 감지 (staged)
[INFO] Git diff 수집 완료: 128줄
[INFO] 현재 브랜치: feature/commit-pr-generator
[INFO] AI API 요청 중... (모델 claude-opus-5-5, effort low)
[DONE] PR 초안 생성 완료

--- PR Title -----------------------------------------------------------
feat: 커밋/PR 자동 생성 기능 추가
------------------------------------------------------------------------

--- PR Body ------------------------------------------------------------
## Why
- 커밋 메시지와 PR 설명 작성에 시간이 들어 자동 생성 도구가 필요했습니다.
- Git 변경 사항을 근거로 일관된 형식의 요약을 만들어 리뷰 효율을 높이고자 했습니다.

## What
- gitctl.py 에 git status / git diff 수집 로직 추가
- llm.py 에 Anthropic API 호출 및 예외 처리 추가
- validate.py 에 길이·형식 검증과 후처리 추가

## How to Test
- 환경변수 설정: export ANTHROPIC_API_KEY="YOUR_KEY"
- 커밋 메시지 생성: python main.py commit
- PR 초안 생성: python main.py pr
- 테스트 실행: python -m pytest tests/ -q
------------------------------------------------------------------------
[INFO] 제목 길이: 21자 (최대 80)
```

### 변경 사항이 없을 때

```
$ python main.py commit
[INFO] 변경 사항이 없습니다. 생성하지 않고 종료합니다.
```

### 추적되지 않은 새 파일만 있을 때

`git` 은 untracked 파일의 내용을 `git diff` 에 넣지 않습니다. 빈 diff 를 보내면
돈만 쓰고 근거 없는 메시지가 나오므로 여기서 멈춥니다.

```
$ python main.py commit
[INFO] Git status 수집 완료: 1개 파일 변경 감지 (unstaged)
[INFO] Git diff 수집 완료: 0줄
[WARN] 변경된 파일은 있지만 diff 가 비어 있습니다. 추적되지 않은 새 파일(untracked)뿐인 것 같습니다.
[INFO] `git add <파일>` 로 스테이징한 뒤 다시 실행하세요. API 를 호출하지 않았습니다.
```

---

## 민감정보 포함 가능성과 대응

**`git diff` 에는 비밀값이 들어 있을 수 있습니다.** `.env` 수정, 하드코딩된 키,
테스트용 개인정보가 그대로 담깁니다. 그걸 외부 API 로 보내면 **되돌릴 수 없습니다.**
요청은 취소할 수 있어도 이미 전송된 데이터는 지울 수 없습니다.

그래서 **safe-mode 가 기본으로 켜져 있습니다.** 두 가지를 함께 합니다.

### (A) 패턴 마스킹

| 종류 | 예 |
|---|---|
| Anthropic / OpenAI 키 | `sk-ant-...`, `sk-...` |
| AWS | `AKIA...`, `aws_secret_access_key=...` |
| GitHub 토큰 | `ghp_...`, `gho_...` |
| `KEY=VALUE` 꼴 | `DB_PASSWORD="..."`, `API_KEY=...` |
| Bearer 토큰 | `Authorization: Bearer ...` |
| 개인정보 | 이메일, 휴대폰 번호, 주민등록번호 꼴 |
| 사설 키 | `-----BEGIN ... PRIVATE KEY-----` |

규칙은 `aigitgen/sanitize.py` 의 `MASK_RULES` 에 모여 있습니다. 정규식이라 추가하기 쉽습니다.

### (B) 전송량 제한

기본 **최대 10개 파일 / 200줄**까지만 보냅니다. `--max-files`, `--max-lines` 로 바꿉니다.
파일 **경계를 지켜서** 자릅니다. 줄 수만 보고 자르면 diff 가 중간에서 끊겨 AI 가 변경을 오해합니다.

### 순서가 중요합니다

**마스킹 → 제한** 순서로 돕니다. 먼저 자르면 잘려나간 부분의 비밀값은 검사조차 되지 않습니다.
마스킹을 먼저 해야 "보낸 것 중에 비밀값이 없다"를 보장할 수 있습니다.

### 한계 — 솔직하게

**정규식은 '그렇게 생긴 것'만 잡습니다.** 완벽한 탐지는 불가능합니다.

실제로 만든 함정도 있습니다. 처음에 `KEY=VALUE` 규칙을 느슨하게 짰더니
`api_key = resolve_api_key()` 같은 **평범한 코드까지 마스킹**해 버렸습니다
(자기 소스 diff 에서 3건 오탐). 비밀값이 아닌 걸 가리면 AI 가 실제 코드를
못 보고 요약 품질이 떨어집니다 — 안전한 쪽 실수라도 공짜가 아닙니다.
지금은 따옴표로 감싼 리터럴과 토큰 끝까지 이어지는 맨 값만 잡습니다
(`tests/test_sanitize.py` 의 오탐 회귀 테스트가 지킵니다).

**보낼 내용을 미리 확인하는 습관이 가장 확실합니다.**

```bash
python main.py preview        # API 를 호출하지 않고 전송될 내용 전체를 보여줍니다
```

---

## 비용 / 요청 횟수 제한 및 권장 사용법

### 요청 횟수를 1~2회로 제한합니다

`commit` / `pr` 명령은 **API 를 최대 2회**만 호출합니다.

```
1회차 호출 → 형식 검증 → 통과하면 끝 (1회)
                      → 실패하면 '무엇이 틀렸는지'를 알려주고 1회만 재생성 (2회)
2회차 결과 → 형식 검증 → 그래도 실패하면 돈이 안 드는 후처리로 규칙을 강제
```

재생성을 무한히 돌리면 비용이 통제되지 않습니다. 그래서 재생성은 딱 한 번이고,
그 다음은 후처리로 마무리합니다. `--no-retry` 를 주면 **항상 1회**로 고정됩니다.

실행이 끝나면 호출 횟수·토큰·예상 비용을 출력합니다.

```
  API 호출 횟수 : 1회
  입력 토큰     : 2,431
  출력 토큰     : 112
  예상 비용     : $0.00196 (claude-opus-5-5)
```

### 모델별 단가 (1M 토큰당, 2026-10 기준)

| 모델 | 입력 | 출력 | 이 작업에 적합한가 |
|---|---:|---:|---|
| `claude-opus-5-5` (기본) | $4.00 | $20.00 | 복잡한 변경을 잘 요약합니다. 기본값 |
| `claude-sonnet-5-5` | $2.00 | $10.00 | 균형 |
| **`claude-haiku-5-5`** | **$0.10** | **$0.50** | **diff 요약에는 충분합니다. 40배 저렴** |

**비용을 아끼려면 `--model claude-haiku-5-5` 를 쓰세요.**
커밋 메시지 요약은 깊은 추론이 필요한 작업이 아닙니다.

```bash
python main.py commit --model claude-haiku-5-5
```

### 권장 사용법

- **`preview` 를 먼저 돌리세요.** 무료이고, 전송될 내용과 diff 크기를 미리 봅니다.
- **큰 diff 는 쪼개세요.** 입력 토큰이 비용의 대부분입니다. 200줄 제한이 기본인 이유입니다.
- **`--effort low` 를 유지하세요.** 기본값입니다. 올려야 할 만큼 복잡한 변경은 드뭅니다.
- **`--staged` 를 쓰세요.** 커밋할 것만 보내면 입력이 줄어듭니다.
- 하루에 수십 번 돌릴 도구가 아닙니다. 커밋 직전 한 번이면 충분합니다.

---

## 팀 컨벤션 적용 (`--convention`)

커밋 prefix 규칙이나 PR 템플릿이 팀마다 다릅니다. 파일로 적어두고 넘기면 프롬프트에 붙습니다.

```bash
cat > .ai-gitgen-convention.md <<'EOF'
- 커밋 제목은 `<type>(<scope>): <요약>` 형식을 쓴다. 예: feat(auth): 로그인 추가
- type 은 feat, fix, docs, refactor, test, chore 만 쓴다
- PR 본문 마지막에 `## Checklist` 섹션을 넣고 `- [ ] 테스트 추가` 를 포함한다
EOF

python main.py commit --convention .ai-gitgen-convention.md
```

---

## 프로젝트 구조

```
ai-gitgen/
├── main.py                 CLI 진입점 (argparse, 흐름 제어)
├── aigitgen/
│   ├── gitctl.py           git status / diff 수집
│   ├── sanitize.py         safe-mode — 마스킹 + 전송량 제한
│   ├── prompts.py          프롬프트 설계 (system / user / 재생성)
│   ├── llm.py              Anthropic API 호출 + 예외 처리
│   ├── validate.py         길이·형식 검증 + 후처리
│   └── render.py           출력 구획
├── tests/                  42개 (API 호출 없음, 비용 0)
├── requirements.txt
└── README.md
```

프롬프트를 `prompts.py` 한 곳에 모은 이유는, 이 과제의 핵심이 "단순 API 호출"이
아니라 **어떤 입력을 주는가** 이기 때문입니다. 설계 원칙은 그 파일 맨 위에 적어 뒀습니다.

---

## 테스트

```bash
python -m pip install pytest
python -m pytest tests/ -q
```

**API 를 호출하지 않습니다.** 가짜 응답으로 검증·재생성·후처리가 맞물려 도는지,
호출 횟수가 1~2회 제약을 지키는지 확인합니다. 실제 API 테스트는 돈이 들고
결과가 매번 달라 자동화에 맞지 않습니다.

```
42 passed
```

테스트가 실제로 잡아낸 버그가 있습니다.

| 버그 | 증상 |
|---|---|
| 후처리 보장 깨짐 | 제목이 빈 입력에서 후처리 결과가 검증을 통과하지 못했습니다 |
| 마스킹 오탐 | `api_key = resolve_api_key()` 같은 코드를 마스킹했습니다 |
| API 키 안내 묻힘 | `anthropic` 패키지가 없으면 키 미설정 안내가 가려졌습니다 |
| `preview` 분기 | `preview` 가 항상 PR 프롬프트만 보여줬습니다 |

---

## 제약 사항 (과제 명세)

- API 키는 **환경변수로만** 관리하며 코드에 하드코딩하지 않습니다.
- Git 수집은 `git status` / `git diff` 범위로 **제한**합니다.
- 커밋/PR 생성은 **초안 텍스트 출력까지**입니다.
  `git push`, GitHub PR 생성(API 연동) 등 원격 저장소 자동 반영은 **구현하지 않습니다.**
- 1회 실행 시 API 요청은 **1~2회 이내**입니다.
- 생성된 문구는 최종 정답이 아니며, **사용자가 검토 후 적용**합니다.
