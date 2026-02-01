# GhostCode Auditor - Implementation Plan

> **프로토콜**: Full (신규 에이전트)
> **대상 언어**: TypeScript/JS + React (MVP 1등 시민)
> **백엔드**: FastAPI (Python)
> **LLM 사용**: 미사용 (규칙 기반 + AST + git blame)
> **연동**: pr-review-agent (webhook 트리거, 별도 코멘트)

---

## 1. 프로젝트 개요

### 1.1 문제 정의

AI 생성 코드가 코드베이스에 쌓이면서 "아무도 이해하지 못하는 복잡한 로직"이 검토 없이 머지됨.
기존 pr-review-agent는 **라인 단위 패턴 매칭**(보안/성능)만 하므로,
**함수 단위 구조 분석 + 검토 증거 추적**은 별도 도구가 필요함.

### 1.2 핵심 가치

"팀이 오늘 당장 의사결정에 쓰는 보고서" — 점수가 아니라 **액션**을 제공.

### 1.3 기존 에이전트와의 관계

```
[GitHub PR Webhook]
       |
       +---> pr-review-agent (기존, 패턴 매칭, 즉시 응답)
       |         "SEC-001: 하드코딩 시크릿" 류
       |
       +---> ghostcode-auditor (신규, AST+blame, 증분 스캔)
                  "이 함수: 인지부하 82, 리뷰 증거 없음, 분리 추천" 류
```

- 별도 프로세스, 별도 포트
- pr-review-agent에서 HTTP 호출로 트리거 (또는 독립 webhook)
- 각자 독립 코멘트

---

## 2. MVP 범위

### 2.1 IN (포함)

- TS/JS/TSX/JSX 파일 분석
- 분석 단위: Component / Hook / Function
- 핵심 지표 4종: Shadow Logic Density, Cognitive Load, Redundancy, Refactoring Runway
- React 전용 감사 규칙 15개 (YAML)
- PR 증분 스캔 (변경 유닛만)
- JSON 리포트 + HTML 정적 리포트
- PR 코멘트 (Top 5 hotspots + 액션)

### 2.2 OUT (MVP 제외)

- AI-Origin Detector (증명 불가능 함정 → 나중에 참고치로만)
- Python/Go/Java 등 다른 언어
- 임베딩 기반 정교 유사도 (2차)
- React 대시보드 UI
- 사용자 인증/멀티테넌트

### 2.3 기본 타깃 (가정)

| 항목 | 기본값 |
|------|--------|
| 파일 수 | 200~500개 |
| LOC | 50k~200k |
| 유닛 수 | 2,000~10,000개 |
| PR 증분 스캔 목표 | 60초 내 코멘트 |
| 초기 풀스캔 | 5~20분 |

---

## 3. 아키텍처

### 3.1 파이프라인 (5단계)

```
(1) Repo Ingest
    - git clone / checkout (특정 커밋/브랜치)
    - 파일 필터 (exclude: node_modules, dist, build, .next, coverage, __tests__)
    - 언어별 확장자 필터 (.ts, .tsx, .js, .jsx)
        |
(2) Evidence Extract
    - git blame → 함수별 작성자/수정자 수, 수정 이력
    - commit metadata → 리팩토링/테스트 시그널
    - (선택) PR 리뷰 흔적
        |
(3) AST/Structure Extract
    - tree-sitter-typescript/javascript로 파싱
    - Unit 추출: Component / Hook / Function
    - 구조 특징: LOC, 중첩깊이, 분기수, early return, try/catch, 훅 패턴
        |
(4) Scoring + Similarity
    - 규칙 기반 점수 (YAML 규칙 적용)
    - 4종 지표 계산
    - 토큰/AST shingles 해시 → 유사도 군집 (1차)
    - 캐시: (file_hash, unit_span, commit_sha)
        |
(5) Report Build
    - JSON 리포트 (스키마 고정)
    - HTML 정적 리포트 (Jinja2 템플릿)
    - PR 코멘트 (Top 5 hotspots + 액션)
```

### 3.2 디렉토리 구조

```
ghostcode-auditor/
├── api/
│   ├── main.py              # FastAPI 엔트리
│   ├── routes/
│   │   ├── scan.py           # POST /scan (풀스캔)
│   │   ├── pr.py             # POST /pr (증분 스캔)
│   │   └── report.py         # GET /report/{scan_id}
│   └── webhook.py            # GitHub webhook 수신 (독립 모드)
├── engine/
│   ├── ingest.py             # repo checkout, 파일 필터
│   ├── evidence.py           # git blame, commit metadata
│   ├── extract.py            # tree-sitter AST → unit 추출
│   ├── scores.py             # 4종 지표 계산
│   ├── similarity.py         # 토큰 shingles → 클러스터
│   └── report.py             # JSON/HTML 생성
├── rules/
│   └── react-ts.yaml         # React/TS 규칙 15개
├── templates/
│   ├── report.html           # Jinja2 HTML 리포트
│   └── pr-comment.md         # PR 코멘트 템플릿
├── cache/                    # 로컬 캐시 (SQLite)
├── tests/
├── requirements.txt
├── .env.example
└── IMPLEMENTATION_PLAN.md
```

### 3.3 기술 스택

| 계층 | 선택 | 이유 |
|------|------|------|
| API | FastAPI | AST/데이터 처리 생태계, async 지원 |
| Parser | tree-sitter + tree-sitter-typescript | TSX/JSX 포함, Python 바인딩 성숙 |
| Blame | git CLI (subprocess) | MVP 충분, 나중에 libgit2 |
| Similarity | 토큰 shingles (hashlib) | 로컬, 비용 0, MVP 충분 |
| 저장 | SQLite | 단일 파일, MVP 충분, 나중에 Postgres |
| 템플릿 | Jinja2 | FastAPI 기본 지원 |
| 캐시 | SQLite 동일 DB 내 테이블 | 단순 |

---

## 4. 데이터 모델

### 4.1 Unit (분석 단위)

```python
@dataclass
class Unit:
    id: str                    # sha256(file_path + name + span)
    file_path: str             # src/components/Auth.tsx
    name: str                  # refreshTokenIfExpired
    kind: str                  # "component" | "hook" | "function"
    span: tuple[int, int]      # (start_line, end_line)
    loc: int                   # lines of code
    nesting_depth: int         # max nesting
    branch_count: int          # if/else/switch/ternary
    early_return_count: int
    try_catch_count: int
    hook_deps: list[str]       # useEffect deps (React)
    has_cleanup: bool          # useEffect cleanup 여부
    render_side_effects: int   # 렌더 중 fetch/storage 호출
```

### 4.2 Evidence (검토 증거)

```python
@dataclass
class Evidence:
    unit_id: str
    distinct_authors: int       # blame 기반 작성자 수
    touched_after_creation: bool
    touch_count_30d: int
    touch_count_90d: int
    commit_signals: list[str]   # "refactor", "test", "fix" 등
    review_evidence_score: int  # 0~100
```

### 4.3 Scores

```python
@dataclass
class UnitScores:
    unit_id: str
    cognitive_load: float       # 0~100
    review_evidence: float      # 0~100
    shadow: bool                # review_evidence < 30 AND cognitive_load > 70
    fragility: float            # 0~100
    redundancy_cluster_id: str | None
```

### 4.4 리포트 JSON 스키마

```json
{
  "scan_id": "uuid",
  "scan_type": "full | pr",
  "repo": { "name": "string", "commit": "sha", "branch": "string" },
  "timestamp": "ISO8601",
  "summary": {
    "total_units": 0,
    "scanned_units": 0,
    "shadow_logic_density": 0.0,
    "avg_cognitive_load": 0.0,
    "redundancy_score": 0.0,
    "refactoring_runway_months": 0
  },
  "hotspots": [
    {
      "path": "src/auth/token.ts",
      "symbol": "refreshTokenIfExpired",
      "kind": "function",
      "span": { "start": 120, "end": 245 },
      "scores": {
        "cognitive_load": 82,
        "review_evidence": 12,
        "fragility": 68,
        "redundancy_cluster_id": "c12"
      },
      "why": [
        "deep nesting (6)",
        "branch count high (18)",
        "low human touch (1 author, never revised)"
      ],
      "actions": [
        "split into 3 functions: parse/validate/refresh",
        "add tests: expired token, clock skew, refresh failure",
        "assign code owner"
      ]
    }
  ],
  "clusters": [
    {
      "id": "c12",
      "members": ["file#funcA", "file#funcB"],
      "suggestion": "extract shared utility: normalizeHeaders()"
    }
  ]
}
```

---

## 5. 핵심 지표 정의

### 5.1 Shadow Logic Density

**"검토 흔적 없는 복잡 로직" 비중**

```
review_evidence (0~100):
  +30: distinct_authors >= 2
  +20: touched_after_creation == true
  +20: touch_count_90d >= 2
  +10: commit_signals에 "refactor"/"test"/"type" 포함
  +20: (PR 리뷰 데이터 있을 때, 선택)

shadow 조건: review_evidence < 30 AND cognitive_load > 70
density = shadow_units / total_units
```

### 5.2 Cognitive Load Score (React 보정 포함)

**함수 단위 인지부하 0~100**

```
base_load = (
    w1 * nesting_depth          # 기본 15
  + w2 * branch_count           # 기본 10
  + w3 * boolean_complexity     # &&/|| 연쇄, 기본 8
  + w4 * callback_depth         # 기본 12
  + w5 * identifier_ambiguity   # data/tmp/result 비율, 기본 10
  + w6 * context_switches       # 도메인 객체 종류 과다, 기본 5
  + w7 * exception_irregularity # try/catch 불일치, 기본 8
  + w8 * side_effect_count      # 기본 7
)

React 보정:
  + useEffect 의존성 불안정 시 가산 (+10~20)
  - 의존성 안정 + cleanup 존재 시 감산 (-5~10)
  + 렌더 중 side-effect 감지 시 가산 (+15~25)

정규화: min(100, base_load * scale_factor)
```

가중치 기본값 (총합이 100에 근접하도록):

| 요소 | 가중치 | 임계값(경고) |
|------|--------|-------------|
| nesting_depth | 15 | >= 4 |
| branch_count | 10 | >= 8 |
| boolean_complexity | 8 | >= 4 chains |
| callback_depth | 12 | >= 3 |
| identifier_ambiguity | 10 | >= 40% |
| context_switches | 5 | >= 5 types |
| exception_irregularity | 8 | 불일치 |
| side_effect_count | 7 | >= 3 |
| useEffect 불안정 | +15 | deps 누락/변동 |
| render side-effect | +20 | fetch/storage in render |

### 5.3 Redundant Pattern Score (2단계)

```
1차 (MVP): AST 토큰 shingles → Jaccard 유사도
  - 함수 토큰열에서 식별자 정규화 (변수명 → _VAR, 문자열 → _STR)
  - 4-gram shingles → MinHash
  - 유사도 >= 0.7 → 같은 클러스터

redundancy = 1 - (unique_clusters / total_units)

2차 (나중): 임베딩 기반 정교 비교 (선택)
```

### 5.4 Refactoring Runway

```
K = 최근 30일 shadow unit 증가량 (신규 shadow)
H = 최근 30일 shadow→human-owned 전환량 (review_evidence 상승 or 복잡도 하락)
runway_months = current_shadow_units / max(K - H, 1)
```

---

## 6. React/TS 감사 규칙 15개 (YAML)

```yaml
language: typescript-react
version: "1.0"

rules:
  # === 렌더/상태/부작용 ===
  - id: REACT-001
    name: render_side_effect
    when: "fetch/localStorage/sessionStorage call in component body (outside useEffect)"
    severity: high
    action: "useEffect로 이동, 의존성 배열 정의"

  - id: REACT-002
    name: useeffect_deps_missing
    when: "useEffect with empty or missing dependency array referencing outer variables"
    severity: high
    action: "deps 명시, useCallback/useMemo 적용"

  - id: REACT-003
    name: setstate_in_loop
    when: "setState called inside loop or chained setState calls > 3"
    severity: medium
    action: "useReducer 패턴으로 전환"

  - id: REACT-004
    name: derived_state
    when: "useState initialized from props or other state without transformation"
    severity: medium
    action: "useMemo 또는 직접 계산으로 대체"

  - id: REACT-005
    name: prop_drilling
    when: "prop passed through >= 3 intermediate components unchanged"
    severity: low
    action: "Context 분리 또는 컴포넌트 구조 변경"

  # === 타입/에러/경계 ===
  - id: TS-001
    name: any_abuse
    when: "explicit 'any' type annotation count > 3 in unit"
    severity: medium
    action: "타입 좁히기, unknown + type guard 사용"

  - id: TS-002
    name: api_call_no_trycatch
    when: "fetch/axios call without surrounding try/catch or .catch()"
    severity: high
    action: "공통 fetch wrapper로 통합, 에러 핸들링 추가"

  - id: TS-003
    name: empty_catch
    when: "catch block with empty body or only console.log"
    severity: high
    action: "에러 로깅/토스트/리트라이 추가"

  - id: TS-004
    name: null_unsafe
    when: "property access chain without optional chaining or null guard (>= 3 deep)"
    severity: medium
    action: "optional chaining (?.) 또는 early return guard"

  # === 복잡도/중복 ===
  - id: CX-001
    name: boolean_overload
    when: "boolean expression with >= 6 operators (&&, ||)"
    severity: medium
    action: "predicate 함수로 추출"

  - id: CX-002
    name: deep_nesting
    when: "nesting_depth >= 5"
    severity: high
    action: "early return 패턴 또는 함수 분리"

  - id: CX-003
    name: inline_handler_unstable
    when: "arrow function defined inline in JSX prop + used in deps"
    severity: medium
    action: "useCallback 적용"

  - id: CX-004
    name: duplicate_logic
    when: "redundancy_cluster member (similarity >= 0.7)"
    severity: medium
    action: "shared utility 추출"

  - id: CX-005
    name: magic_strings
    when: ">= 3 identical string literals in same file"
    severity: low
    action: "constants 모듈 또는 enum으로 추출"

  - id: CX-006
    name: comment_over_naming
    when: "comment-to-code ratio > 0.4 AND identifier_ambiguity > 50%"
    severity: low
    action: "함수/변수 네이밍 개선, 불필요 주석 제거"
```

---

## 7. 캐시 설계

### 7.1 캐시 키

```
unit_cache_key = sha256(file_content_hash + unit_span + parser_version + ruleset_version)
evidence_cache_key = repo_commit_sha + file_path
```

### 7.2 캐시 저장

- SQLite `cache` 테이블
- TTL: 풀스캔 결과 7일, 증분 결과 1일
- 캐시 히트 시 scoring/similarity 건너뜀

### 7.3 증분 스캔 전략

```
1. PR diff에서 변경 파일 목록 추출
2. 변경 파일만 AST 파싱 → 영향받는 unit 식별
3. 해당 unit만 scoring
4. 중복 탐지: 변경 unit + 같은 디렉토리 내 unit으로 범위 제한
5. 캐시 미스 unit만 계산
```

---

## 8. PR 코멘트 형식

```markdown
## GhostCode Audit Report

**Scan**: PR #123 | 12 units analyzed | 3 hotspots found

### Top Hotspots

| # | File | Function | Cognitive Load | Review Evidence | Action |
|---|------|----------|---------------|-----------------|--------|
| 1 | src/auth/token.ts | refreshTokenIfExpired | 82/100 | 12/100 | Split into 3 functions |
| 2 | src/hooks/useData.ts | useDataFetch | 71/100 | 25/100 | Add cleanup to useEffect |
| 3 | src/utils/format.ts | formatResponse | 65/100 | 8/100 | Extract shared normalizer |

### Shadow Logic Density: 23% (⚠️)

3 of 12 changed units have low review evidence + high complexity.

### Redundancy Alert

`formatResponse` and `transformPayload` share 78% token similarity.
→ **Extract**: `normalizeApiResponse()` utility

---
*GhostCode Auditor v0.1 | [Full Report](link)*
```

---

## 9. pr-review-agent 연동

### 9.1 연동 방식 (2가지 중 택 1)

**Option A: pr-review-agent에서 HTTP 호출** (추천)

```javascript
// pr-review-agent/main.js에 추가 (1줄)
// scoring 완료 후, ghostcode-auditor에 비동기 트리거
fetch(`http://localhost:${GHOSTCODE_PORT}/pr`, {
  method: 'POST',
  body: JSON.stringify({ owner, repo, prNumber, headSha })
}).catch(() => {}); // fire-and-forget
```

**Option B: 독립 webhook**
- ghostcode-auditor가 자체 webhook 엔드포인트 운영
- GitHub에 webhook 2개 등록

→ MVP는 **Option A** (기존 인프라 활용, webhook 1개 유지)

### 9.2 포트

| 에이전트 | 포트 |
|----------|------|
| pr-review-agent | 3006 |
| ghostcode-auditor | 3007 |

---

## 10. 마일스톤

### M1: 엔진 코어

- [ ] 프로젝트 초기화 (FastAPI + tree-sitter 설치)
- [ ] ingest.py: repo checkout + 파일 필터
- [ ] extract.py: tree-sitter로 TS/TSX unit 추출
- [ ] Unit 데이터 모델 + SQLite 스키마

### M2: 증거 + 점수

- [ ] evidence.py: git blame → review_evidence 계산
- [ ] scores.py: cognitive_load 계산 (가중치 적용)
- [ ] scores.py: shadow 판정 로직
- [ ] YAML 규칙 로더 + 규칙 매칭 엔진

### M3: 유사도 + 리포트

- [ ] similarity.py: 토큰 shingles → 클러스터링
- [ ] report.py: JSON 리포트 생성
- [ ] report.py: HTML 템플릿 (Jinja2)
- [ ] Refactoring Runway 계산

### M4: API + PR 연동

- [ ] POST /scan (풀스캔)
- [ ] POST /pr (증분 스캔)
- [ ] GET /report/{scan_id}
- [ ] PR 코멘트 생성 (gh CLI)
- [ ] pr-review-agent 연동 (fire-and-forget)

### M5: 캐시 + 최적화

- [ ] SQLite 캐시 테이블
- [ ] 증분 스캔 최적화 (변경 unit만)
- [ ] 중복 탐지 범위 제한 (같은 디렉토리)
- [ ] 테스트 (규칙 15개 + 점수 정확도)

---

## 11. 자가 비판 (Phase 3)

### 이 설계의 취약점

1. **tree-sitter로 React 패턴 정확히 잡기 어려울 수 있음**
   - useEffect deps, prop drilling 등은 AST만으로 한계
   - 완화: 1차는 정규식 보조, 정확도 낮은 규칙은 severity 낮춤

2. **git blame이 rebase/squash에 취약**
   - rebase 후 blame이 리셋되면 review_evidence가 실제보다 낮게 나옴
   - 완화: blame 외에 commit count/frequency도 함께 봄

3. **Runway 지표가 데이터 부족 시 무의미**
   - 최초 스캔에서는 30일 히스토리가 없음
   - 완화: 첫 스캔 시 "데이터 부족" 표시, 2회차부터 계산

4. **중복 탐지 오탐 (보일러플레이트)**
   - React 컴포넌트는 구조가 비슷한 게 정상
   - 완화: 컴포넌트 간 유사도 임계값을 높임 (0.85), 유틸 간은 0.7 유지

5. **성능: 풀스캔 시 tree-sitter 파싱 시간**
   - 500개 파일 기준 예상 수 분
   - 완화: 캐시 + 병렬 파싱 (ProcessPoolExecutor)

---

## 12. 환경변수

```bash
# .env.example
PORT=3007
GITHUB_TOKEN=         # gh CLI 인증 (기존 환경변수 재사용)
WEBHOOK_SECRET=       # GitHub webhook secret
CACHE_TTL_DAYS=7
MAX_SCAN_FILES=1000
LOG_LEVEL=info
```

---

## 13. 의존성

```
# requirements.txt
fastapi>=0.110
uvicorn>=0.27
tree-sitter>=0.21
tree-sitter-typescript>=0.21
tree-sitter-javascript>=0.21
jinja2>=3.1
pyyaml>=6.0
```

외부 도구: `git`, `gh` (CLI)

---

**승인 후 M1부터 50줄 단위로 구현 시작합니다.**
