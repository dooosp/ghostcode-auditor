---
date: 2026-02-02
tags: [#ghostcode-auditor, #invest-quant, #code-audit, #agent-factory]
project: ghostcode-auditor, invest-quant, agent-factory
---

## 해결 문제 (Context)
- agent-factory로 Classic(50개) + BSA(40개) 아이디어 생성 완료
- ghostcode-auditor로 invest-quant 프로젝트 코드 품질 감사 수행

## 세션 작업 내역

### 1. 프로젝트 목록 관리
- projects.md에 agent-factory 추가 (33번째)
- CLAUDE.md 프로젝트 카운트: 30 → 32 → 33개 갱신

### 2. agent-factory 아이디어 생성
| 모드 | 출력 파일 | 개수 |
|------|----------|------|
| Classic v3 | `~/agent-factory/output/ideas-2026-02-02-v3.md` | 50개 |
| BSA v3 | `~/agent-factory/output/ideas-2026-02-02-bsa-v3.md` | 40개 |

- Classic: docker, homelab, algotrading, javascript, Notion, LocalLLaMA, indiehackers, node, popular (197 posts)
- BSA: selfhosted, MachineLearning, UI_Design, productivity, reinforcementlearning, personalfinance, datascience, StableDiffusion, ChatGPT, webdev, popular (234 posts)

### 3. invest-quant Ghostcode 감사 결과

| 지표 | 값 |
|------|-----|
| 스캔 유닛 | 97개 |
| Shadow Logic 밀도 | 0.34 (주의) |
| 평균 인지 부하 | 59.6/100 |
| 중복도 | 19.6% (양호) |
| 리팩토링 런웨이 | 8개월 |

**최대 핫스팟**: `strategy-engine.js` — `generateSignals` 분기 48개, `runBacktest` 중첩 5단계
**중복 클러스터**: 8건 (round, SMA, validate, score, python-bridge, safe, auto-trader-client)

## 핵심 통찰 (Learning & Decision)
- **Problem:** invest-quant의 strategy-engine.js가 인지 부하 최대치, 특히 generateSignals(분기 48개)
- **Decision:** 런웨이 8개월이므로 즉시 리팩토링 불필요. 기능 변경 시 함께 정리하는 전략 채택
- **Next Step:** strategy-engine.js 수정 시 generateSignals 함수 분리 우선. round()/SMA 중복 클러스터는 여유 시 통합
