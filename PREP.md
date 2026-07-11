# Ralphthon @ICML — 사전 준비 체크리스트 (7/11 밤)

> 소스: 공식 레포 [team-attention/ralphthon-icml](https://github.com/team-attention/ralphthon-icml) (7/8 공개, Codex 플러그인).
> 로컬 클론: scratchpad에 있음. 이 레포가 내일의 룰북이다.

## 내일 실제 타임라인 (공식)

| 시간 | 내용 |
|---|---|
| 09:30 | 입장/체크인 (Luma) |
| 11:00–12:30 | **Research spec 작성** (사람이 직접, 프리즈) |
| 12:30–15:30 | **Ralph Loop — 3시간, 노터치** (랍스터 룰) |
| 15:30–16:30 | 사람 편집 허용 + 최종 제출 (**16:30 하드컷**) |
| 이후 | peer/self-review → 데모 → 시상, 20:00 종료 |

**루프는 딱 3시간.** 밤샘 아님. 모든 스코프를 여기 맞출 것.

## 트랙 전환 관련 (질문의 답)

공식 workflow.md 원문: **"Participants may enter Track 1, Track 2, or both."**
→ 트랙은 제출물 단위다(등록 락인 없음). Track 1으로 등록했어도 Track 2 제출 가능, "Both"도 공식 경로임.
→ 그래도 Luma "Contact the Host"로 오늘 밤 확인 메시지 보내둘 것 (등록폼상 트랙 배정이 운영에 쓰일 수 있음).
→ 주의: Track 2는 **Track 1 페이퍼(frozen)를 리뷰**하는 구조. 리뷰 대상은 행사에서 공급됨 (16:30 이후 peer review 세션). "Both"면 자기 페이퍼 리뷰.

## 제출물 규격 (공식, 그대로 따를 것)

**Track 1:** ① agent workflow(감사 추적 포함) ② **2–4페이지 워크숍 스타일 short paper** ③ self-review
**Track 2:** ① `review-agent.md` (에이전트 정의, 버전/입력 해시 프리즈) ② ICML 스타일 구조화 리뷰 결과
리뷰 필수 섹션: Summary / Strengths / Weaknesses / Questions / Scores(Soundness·Presentation·Contribution·Overall·Confidence, **점수당 evidence 근거 1개**) / Ethics·Limitations / **Evidence Trace**
템플릿: 공식 레포 `skills/auto-research/assets/`에 전부 있음 — 그대로 복사해서 채우는 구조.

## Track 1 경로 3개 (공식이 정의함)

1. **Training path**: [vessl-cloud-cookbook/autoresearch](https://github.com/vessl-ai/vessl-cloud-cookbook/tree/main/autoresearch) (= karpathy/autoresearch 미러, pinned) — A100 1장에서 `train.py`만 수정, baseline + candidate 3개(순차) + winner 재확인, metric은 `val_bpb` (낮을수록 승). **연구주제 고민이 필요 없음** — 벤치마크가 주제다. 단, W&B + VESSL 온보딩 필수, 3시간 안에 러닝 5회가 들어가야 함 (런타임 리스크 확인 필요).
2. **General path**: 자유 주제, compute 불요. 주제는 **11:00–12:30 스펙 타임에 사람이 프리즈** — "AI가 주제 못 정한다" 문제는 규정상 사람이 해결하는 구조.
3. **Track 2-only**: compute/W&B/VESSL 전부 불요. 가장 가벼움.

## 오늘 밤 준비 목록

### 공통 (트랙 무관, 필수)
- [ ] Codex CLI 설치 + API key 로그인 (`codex exec` 무인モード 확인: `--sandbox workspace-write --ask-for-approval never`)
- [ ] 공식 플러그인 `ralphthon-icml` 설치 + 5개 스킬 인식 확인 (`python3 scripts/validate_plugin.py`)
- [ ] `ralph.sh` 루프 스크립트: iteration당 fresh context, git auto-commit, iteration cap, stall watchdog, 로그 파일
- [ ] PROMPT.md / specs/ / fix_plan.md / AGENT.md 골격 + 토이 태스크로 2–3 iteration 드라이런
- [ ] W&B 계정 + `wandb-onboarding` 스킬의 synthetic offline run 통과 (스폰서 심사 어필 + Training path 필수)
- [ ] 멀티탭/파워스트립, 노트북 충전 (SF 에디션 공지: 콘센트 부족)

### Track 2 준비 (권장 메인)
- [ ] `review-agent.md` 초안: 공식 template 기반 + verification tool 목록 정의
- [ ] 검증 도구 프로토타입 (루프가 3시간 동안 개선할 대상):
  - PDF/MD 파서 → claim 추출 → 본문·표·그림 숫자 일치성 검사
  - 인용 실재 검증 (arXiv / Semantic Scholar API)
  - evidence bundle 대조 → Evidence Trace 자동 생성
  - 점수 캘리브레이션 (LLM 리뷰어는 과하게 후함 — OpenReviewer 논문의 핵심 발견)
- [ ] **개발용 평가셋** (루프의 backpressure):
  - AI 생성 페이퍼 샘플 (Sakana AI Scientist 공개 페이퍼, Agents4Science 페이퍼) — 내일 리뷰 대상과 동일 분포
  - 오류 주입 페이퍼 5–10개 자체 제작 (FLAWS 방식: 결론 무효화하는 오류 심기) → 오류 검출률 = 스칼라 메트릭
  - ICLR OpenReview 실제 리뷰 몇 개 (점수 분포 캘리브레이션용)
- [ ] 루프 목표 정의: "리뷰 에이전트를 만들고, 평가셋 점수를 hill-climb하고, 매 iteration W&B에 기록"

### Track 1 준비 (Both 갈 경우 / Training path 기준)
- [ ] VESSL 계정 + `vesslctl` 설치 + credits 확인 + `resource-spec list --usable-only`로 A100 시세 확인
- [ ] cookbook 핀 커밋으로 개인 fork 생성 + 브랜치 푸시 연습
- [ ] baseline 러닝타임 사전 조사 (3h에 5 run이 안 들어가면 candidate 수 축소 계획)
- [ ] `record_experiment.py` + `experiments.jsonl` 레저 플로우 로컬 테스트
- [ ] 2–4p 페이퍼 LaTeX/MD 템플릿 + 컴파일 체크를 루프 backpressure로 와이어링
- [ ] General path 백업: 값싼 API 실험 가설 2–3개 미리 브레인스토밍 (스펙 타임에 하나 프리즈)

### 금지/주의 (공식 Integrity Gate)
- 결과·인용·런 조작 금지, 저장된 결과로 추적 안 되는 숫자 금지, 부정적 결과 은폐 금지
- `git reset --hard`, `git add -A`, "LOOP FOREVER" 금지 (Training path 명시)
- "전부 미리 만들어가기"의 한계: 하네스·도구·평가셋 사전 제작은 과거 우승팀들도 다 했던 정석. 단 **제출 아티팩트(페이퍼/리뷰)는 당일 루프가 생산**해야 함 — 스펙 프리즈(11:00)와 루프(12:30)가 행사 중에 있는 이유.

## 과거 Ralphthon 프로젝트에서 배운 것

- 과거 에디션(서울 #1·#2, SF, SG)은 전부 **제품 해커톤** (예: GhostView, DigestAnything, houseops IP캠 에이전트, SG standup-agent). 이번 ICML 에디션은 최초의 연구 테마 — 직접 참고할 전례 없음. 대신 공식 플러그인이 규격을 못박아줌.
- 우승팀 공통점: ① 하네스를 오픈소스 수준으로 정성껏 (서울 1등 Ouroboros, 2등 oh-my-claude-code) ② 100% 자율 실행 입증 (git 히스토리) ③ 명확한 스토리. 승부처는 **하네스 설계**다.
- 도구 분포: Codex 5팀 / Claude Code 2팀 (서울 #2). 이번엔 공식 플러그인이 Codex 전제 → Codex 권장.
