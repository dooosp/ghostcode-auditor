---
date: 2026-02-02
tags: [#CLAUDE-md, #token-guardian, #context-management, #invest-quant, #ghostcode-auditor, #agent-factory]
project: CLAUDE.md (글로벌 설정)
---

## 해결 문제 (Context)
- 긴 세션 진행 시 context 소진 → auto-compact → 맥락 손실 위험 인지
- 사전 경고 메커니즘 부재

## 세션 작업 내역

### 1. invest-quant Ghostcode 감사
- ghostcode-auditor 서버 환경 구축 (venv 재생성 + 의존성 설치)
- invest-quant 풀스캔 결과:

| 지표 | 값 | 판정 |
|------|-----|------|
| Shadow Logic 밀도 | 0.34 | 주의 |
| 평균 인지 부하 | 59.6/100 | 중간-높음 |
| 중복도 | 19.6% | 양호 |
| 리팩토링 런웨이 | 8개월 | 여유 |

- 최대 핫스팟: `strategy-engine.js` — `generateSignals` (분기 48개)
- 판단: 즉시 리팩토링 불필요, 기능 변경 시 함께 정리

### 2. Context 수명 관리 규칙 추가
- CLAUDE.md Token Guardian 프로토콜에 새 섹션 추가:
```markdown
## Context 수명 관리 (자동)
- 도구 호출 20회 이상 또는 대화가 길어졌다고 판단되면:
  1. Gold Digger로 중간 아카이브 제안
  2. "새 세션 전환 권장" 안내
- 주제가 변경되면 즉시 세션 전환 권고
```

## 핵심 통찰 (Learning & Decision)
- **Problem:** context가 소진되면 환각이 아닌 "맥락 손실 → 부정확한 추측" 위험 발생
- **Decision:** 에이전트 신규 개발 대신 CLAUDE.md 규칙 3줄 추가로 해결 (context left는 CLI 내부 상태라 외부 에이전트 접근 불가)
- **Next Step:** 다음 세션부터 자동 적용됨. 효과 확인 후 임계값(20회) 조정 가능
