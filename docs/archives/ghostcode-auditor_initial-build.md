---
date: 2026-02-01
tags: [#ghostcode-auditor, #code-quality, #tree-sitter, #shadow-logic, #mvp]
project: ghostcode-auditor
---

## 해결 문제 (Context)
- AI 생성 코드가 리뷰 없이 쌓이는 "유령 코드(Shadow Logic)" 탐지 에이전트 MVP 구축

## 아키텍처 결정 (Decision Log)

### pr-review-agent 통합 vs 분리
- **결정: 분리 프로젝트**
- 이유: 분석 단위(라인 vs 함수/AST), 데이터 소스(diff vs 전체 repo+blame), 목적이 근본적으로 다름
- 연동: pr-review-agent에서 fire-and-forget HTTP 트리거

### 기술 스택
- **FastAPI(Python)** 선택 — tree-sitter Python 바인딩이 가장 성숙, AST/데이터 처리 생태계 우위
- **tree-sitter-typescript** — TSX/JSX 포함 파싱
- **SQLite** — MVP 충분, 나중에 Postgres 전환 가능
- **LLM 미사용** — 순수 규칙 기반 + AST + git blame

### 3중 방어 파이프라인 설계
```
PR 생성 → pr-review-agent (2초, 패턴매칭) → ghostcode-auditor (30초, AST+blame)
          ↓                                   ↓
          PR 코멘트: 보안/성능                    PR 코멘트: 핫스팟+액션
                     ↓ (매일 크론)
                self-healing-agent (전체 스캔)
```

## 구현 완료 (M1~M5)

### 엔진 모듈 (engine/)
| 모듈 | 역할 |
|------|------|
| ingest.py | repo checkout + 파일 필터 (14개 exclude 패턴) |
| extract.py | tree-sitter AST → Unit(Component/Hook/Function) 추출 |
| evidence.py | git blame → review_evidence 점수 (0~100) |
| scores.py | cognitive_load (React 보정 포함) + shadow 판정 |
| similarity.py | 토큰 shingles → Jaccard 유사도 → 클러스터링 |
| rules.py | YAML 규칙 로더 + 15개 체커 (REACT 5 + TS 4 + CX 6) |
| report.py | JSON 리포트 + PR 코멘트 (Jinja2) |
| pipeline.py | 풀스캔/PR 증분 스캔 오케스트레이터 |
| cache.py | SQLite 캐시 (TTL 기반) |
| db.py | SQLite 스키마 (scans/units/evidence/scores/clusters/cache) |

### 4종 지표
1. **Shadow Logic Density** — review_evidence < 30 AND cognitive_load > 70인 함수 비율
2. **Cognitive Load** — nesting/branch/boolean/hooks/side-effect 가중합 (0~100, React 보정)
3. **Redundancy** — 토큰 shingles Jaccard >= 0.7 클러스터
4. **Refactoring Runway** — shadow 증가속도 vs 팀 처리량 기반 개월 추정

### API (포트 3007)
- `POST /scan/` — 풀스캔
- `POST /pr/` — PR 증분 스캔 + 코멘트
- `GET /report/{scan_id}` — 리포트 조회
- `GET /health` — 헬스체크

### 테스트: 22개 전체 통과

## 에이전트 연동 (이 세션에서 완료)

| 대상 | 변경 |
|------|------|
| pr-review-agent/main.js | ghostcode fire-and-forget 트리거 추가 |
| pr-review-agent/config.js | `repoMap` 매핑 테이블 추가 (환경변수 의존 제거) |
| self-healing-agent/config.js | ghostcode-auditor 스캔 대상 추가 |
| self-healing-agent/scan.sh | ghostcode-auditor 스캔 대상 추가 |
| system-monitor/config.js | ghostcode-auditor 모니터링 등록 (포트 3007) |
| scheduler-agent/schedules.yaml | ghostcode-auditor pm2 등록 (dependsOn: pr-review-agent) |
| projects.md | 프로젝트 목록에 추가 (29번째) |

## 핵심 통찰 (Learning)
- **Problem:** 토큰 정규화에서 단일 문자 식별자(`x`, `a`)가 keyword 경로로 빠져 `_VAR`로 치환되지 않음 → Jaccard 유사도 오류
- **Decision:** `len(tok)==1 and not tok.isalpha()` 조건으로 분기 — 알파벳 단일 문자는 `_VAR`, 기호는 그대로
- **Next Step:** Notion 포트폴리오 동기화 미완료 (다음 세션에서 `notion_portfolio_sync` 실행)
