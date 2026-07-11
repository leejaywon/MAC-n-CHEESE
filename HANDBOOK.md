# 팀 핸드북 — No Free Lunch @ Ralphthon ICML (2026-07-12)

> 이 문서 하나로 "우리가 뭘 만들었고, 왜 특별하고, 내일 뭘 누르는지" 전부 커버한다.

## 1. 전체 그림

```
[레포 A: 2026_07_Ralphthon]            [레포 B: 2026_07_Ralphthon-track1]
 Track 2 — 리뷰어를 "짓는" 루프          Track 1 — 실험 캠페인을 "운영하는" 루프
 ralph.sh → codex exec 반복             ralph.sh → codex exec 반복
   └ fix_plan.md M0~M8 하나씩 구현        └ 6-state 머신: baseline→cand×3
   └ eval.py 점수 = backpressure           →confirmation→paper→self-review
 산출물: review-agent.md + 리뷰          산출물: 2-4p 페이퍼 + 셀프리뷰
                    └──── state 5에서 A의 run_review.py 호출 (Both 시너지) ────┘
 외부: VESSL A100(잡 실행) · W&B offline(증적) · git(감사추적)
```

**Ralph 패턴 요지**: 한 세션을 오래 살리지 않고, 매 iteration fresh context로
`codex exec`를 재호출하고, 진행상태는 전부 파일(fix_plan/ledger)과 git에 산다.
컨텍스트 부패가 구조적으로 없고, 어떤 iteration이 죽어도 다음 iteration이 파일만
읽고 이어간다.

## 2. 우리가 특별하게 구현한 것 (심사 때 그대로 말할 것)

### Track 2 리뷰어 — 논문을 감사(audit)한다

1. **이벤트 증거규격 특화 감사기**: 대회 공식 규격(`experiments.jsonl` ledger,
   evidence 해시, val_bpb 주장)을 그라운드트루스로 대조한다. 모든 지적은
   재계산으로 뒷받침된다. (statcheck/GRIM 계보)
2. **기계 검증 배터리 8종**: ledger-trace / 표↔본문 일치 / 산술 재계산 /
   baseline 공정성 / 인용 실재(arXiv·S2 API) / 템플릿 준수 / **부정결과 누락
   검출**(ledger에 discard·crash가 있는데 페이퍼에 없으면 플래그) / 인젝션 스캔
3. **FLAWS식 오류주입 evalset**: 핵심 주장 추출→주장을 무너뜨리는 오류 주입→
   식별+위치 둘 다 맞아야 정답. 점수 = 검출률 − 0.5×오탐 + 0.1×완성도.
   오탐 페널티는 Black Spatula 프로젝트의 최대 교훈("오탐이 신뢰를 죽인다") 반영.
4. **draft→ground 2패스** (ReviewGrounder): 싼 모델이 초안 → 강한 패스가 문장마다
   근거 id 매핑, 근거 없는 칭찬은 삭제·근거 없는 비판은 Questions로 강등.
5. **프롬프트 인젝션 방어**: AI가 쓴 페이퍼를 AI가 리뷰하는 대회 — 숨긴 "높은 점수
   줘" 지시(invisible unicode/흰 글씨)를 탐지·무력화하고 Ethics에 보고. 벤치마크
   결과 프론티어 LLM 리뷰어가 실제로 뚫리는 공격이며, 이 방어를 준비한 팀은
   우리뿐일 가능성이 높다.
6. **점수 캘리브레이션**: LLM 리뷰어의 고질병(과잉 후함)을 rubric으로 강제 —
   Overall borderline에서 시작, supported 주장만큼만 상승.
7. **안티-Goodhart**: 루프가 eval 정답키·채점기를 수정해 점수를 올리는 것을
   PROMPT 하드룰로 금지. (몇 시간 돌리면 반드시 시도한다)

### Track 1 캠페인 — "지는 그림이 없는 프레임"

1. **리서치 프레임**: "시간고정(5분) 벤치마크에서 H100 튜닝 상수는 A100에
   이식되는가?" — 개선 성공하면 개선 페이퍼, 전부 실패해도 "시간기반 스케줄의
   하드웨어 강건성"이라는 유효한 negative-result 페이퍼. 어느 쪽도 논문이 된다.
2. **코드 정밀분석 기반 가설뱅크**: baseline은 이미 speedrun급(Muon+polar
   express, FA3, SSSL 윈도우, ReLU², value embeds...)이라 유명 트릭 추가는 무효.
   대신 실제 미스매치를 코드에서 발견: 스케줄 전부가 시간기반인데 Muon momentum
   ramp만 step기반(`step/300`) → A100(스텝 ~절반)에서 어긋남 = H2 가설.
   H1(배치 재적합)→H5까지 prior 강도순 사전 랭킹 — n=3 예산에서는
   착취(exploitation)가 정답 (AlphaEvolve/FunSearch: 제안은 LLM, 판정은 evaluator만).
3. **6-state 오퍼레이터**: 상태를 ledger에서 읽어 다음 행동 하나만 수행. 시간
   규율 내장(15:00 candidate 컷, 15:20 페이퍼 우선). 공식 Integrity Gate(순차,
   candidate≤3, 확인런, NEVER-STOP 금지) 준수가 프롬프트에 박혀 있다.
4. **mock→real 스위치**: `RALPH_T1_MOCK=1`이면 가짜 잡(개선/악화/크래시 랜덤)으로
   전 로직을 무과금 리허설. 당일은 플래그만 끈다.

### 하네스 공통

- **커밋 프로토콜**: codex 샌드박스가 `.git` 쓰기를 차단 → 에이전트는
  `.commit_msg`/`.cookbook_commit_msg`만 남기고 바깥 루프가 커밋·푸시. (드라이런에서
  실제로 발견해서 고친 것 — "실패에서 배운 sign-post"의 실례로 심사 때 언급 가치)
- **bounded loop**: iteration cap + perl alarm 타임아웃(의존성 0) + `.ralph_stop`
  즉시 정지 + 안전 커밋. 모든 iteration이 로그·커밋으로 남아 감사추적 완비.
- **Both 시너지 = 킬러샷**: Track 1 페이퍼의 셀프리뷰를 우리 Track 2 리뷰어가
  생성. "쓰는 에이전트와 검증하는 에이전트가 서로를 조인다" — 대회 핵심 질문
  ("better research loops")에 대한 문자 그대로의 답.

## 3. 내일 실전 매뉴얼 (KST)

**08:30 집에서** — 노트북(팀원 것 포함) 충전, 멀티탭, 두 레포 git 상태 clean 확인.

**09:30 도착/체크인** — 크레딧 수령 확인:
`vesslctl billing show` (VESSL 크레딧), Codex는 크레딧 주면 API key 전환
(`codex login --api-key ...`), 아니면 구독 유지.

**~11:00 (세팅 시간)** — Track 1 사전 배관 (과금 시작, 승인하고 진행):

```bash
cd 2026_07_Ralphthon-track1
# ① fork 확인 (아직이면 GitHub에서 fork 후 remote 교체)
git -C vessl-cloud-cookbook remote -v
# ② 당일 캠페인 브랜치로 전환 (전날 밤 핀 SHA에서 생성·푸시 완료 — checkout만 하면 됨)
git -C vessl-cloud-cookbook checkout autoresearch/nfl-day && git -C vessl-cloud-cookbook log --oneline -1  # 97a0af1이어야 함
# ③ object volume 생성 + prep job (CPU $0.30/hr, 캐시 시딩 — 런북 절차)
vesslctl volume create ... && bash vessl-cloud-cookbook/autoresearch/batch-job/prep.sh
# ④ campaign/env.sh의 TODO 3개 채우기 (fork URL / 브랜치 / 볼륨 slug)
```

**11:00–12:30 스펙 프리즈 (사람 손, 마지막 터치)** — `specs/track1-campaign-spec.md`
가설뱅크 최종 확정 + run card 작성, `specs/review-agent-spec.md` 확인. 필요하면
PROMPT sign-post 보강 — **루프 시작 후엔 못 고친다.**

**12:30 루프 시작 (이후 노터치)**

```bash
# 시작 직전 필수: 리허설 잔재 제거
cd 2026_07_Ralphthon-track1 && rm -f campaign/cutoff_override && git rm -q --cached campaign/cutoff_override 2>/dev/null; ls campaign/experiments.jsonl 2>/dev/null && echo "⚠️ mock ledger 남아있음 — logs/로 치울 것"
# 노트북 A (Track 2): cd 2026_07_Ralphthon && ./ralph.sh PROMPT.md 40
# 노트북 B (Track 1): cd 2026_07_Ralphthon-track1 && ./ralph.sh PROMPT.md 30   # MOCK 플래그 없이!
```

관전(읽기만): `tail -f logs/iter_*.log`, `git log --oneline`,
`cat campaign/experiments.jsonl`, W&B offline 디렉토리.

**15:30 루프 정지** — 자연 종료 or `touch .ralph_stop`. **사람 편집 허용 구간**:

- 페이퍼: 문장 다듬기만. **숫자를 새로 쓰거나 고치지 말 것** (ledger에 없는 숫자
  = 우리 리뷰어도 잡고 심사위원도 잡는다). 페이지수 2–4 확인.
- review-agent.md: 브래킷(버전 SHA, 해시) 최종 기입.

**16:30 하드컷 제출** → 이후 peer review 세션: 다른 팀 페이퍼 받으면
`python run_review.py <paper> <evidence> --out review.md` 실행, 결과 제출.

**데모 (5–7분 예상)**: ①W&B 차트(eval 점수 상승 + 캠페인 val_bpb) ②git log
스크롤("사람 커밋 0개") ③리뷰어가 오류 주입 페이퍼 잡는 라이브 데모
④(가능하면) 다른 팀 페이퍼에서 잡은 실제 이슈 1개.

## 4. 트러블슈팅

| 증상                              | 대응                                                                            |
| --------------------------------- | ------------------------------------------------------------------------------- |
| 루프가 같은 태스크 반복 실패      | 12:30 전이면 sign-post 추가. 이후면 그냥 둔다 — 다른 태스크로 넘어가게 설계됨   |
| rate limit (iteration 급감속/429) | API key 계정 전환 후 루프 재시작 (재시작은 harness 조작 아님 — 단 현장 룰 확인) |
| VESSL 잡 폴링 타임아웃            | 잡은 계속 돈다. 다음 iteration이 `vesslctl job show`로 회수 — 설계된 경로       |
| A100 큐 정체                      | 15:00 컷이 자동으로 candidate 수를 줄인다. baseline+1개+확인런이면 페이퍼 성립  |
| Track 1 전멸 (크레딧/클러스터)    | Track 2 단독 제출 (공식 Track 2-only 경로). 리뷰 대상 페이퍼는 현장 제공분 사용 |
| 노트북 1대 고장                   | 한 레포씩 순차 실행 — ralph.sh는 어디서든 `git clone` 후 즉시 재개 가능         |

## 5. 오늘 밤 남은 체크리스트

- [ ] 두 루프 완주 확인 + 로그 회고 (sign-post 추가는 오늘 밤이 마지막 기회)
- [ ] Track 2: M3(eval.py) 생성 확인 — 이후 점수가 실제로 오르는지
- [ ] Track 1 mock: ledger·keep/revert·페이퍼 생성 확인
- [ ] cookbook fork가 본인 계정인지 확인 (`git -C vessl-cloud-cookbook remote -v`)
- [ ] 취침 전 두 레포 커밋 clean
