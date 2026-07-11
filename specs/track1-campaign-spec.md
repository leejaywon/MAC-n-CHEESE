# Track 1 Campaign Spec — autoresearch on A100 (Team: No Free Lunch)

> 당일 11:00–12:30 스펙 타임에 사람이 이 파일을 최종 확정(프리즈)한다.
> 규칙 원본: `campaign/AUTORESEARCH.md` (공식 오버레이) + `vendor/.../vessl-autoresearch-runbook.md`

## Methodology (prior art를 어떻게 쓰는가)

Budget = baseline + ≤3 sequential candidates + 1 winner confirmation.
n=3에서 탐색(exploration)은 사치다. **검증된 prior의 착취(exploitation)**로 간다:

- **karpathy/autoresearch loop semantics**: one change → measure val_bpb → keep iff
  strictly lower → else revert train.py to last kept commit. (event overlay: 순차,
  candidate ≤3, NEVER-STOP 금지)
- **modded-nanogpt speedrun 교훈**: baseline은 이미 speedrun급 (Muon+polar express,
  FA3, SSSL sliding window, ReLU², value embeds, x0 residual, softcap, zero-init).
  유명 트릭 추가는 무효. 남은 엣지는 **"H100에서 튜닝된 상수들의 A100 재적합"**.
- **AlphaEvolve/FunSearch 패턴**: 변이 제안은 LLM, 판정은 오직 evaluator(val_bpb).
  주장은 숫자가 한다.
- **"Why LLMs Aren't Scientists Yet" 실패모드 방어**: premature success 선언 방지
  → 모든 숫자는 ledger에서만; winner는 confirmation rerun 후에만 승자.

## Research frame (페이퍼의 스토리)

**Q: 시간 고정(5분) 벤치마크에서 H100 튜닝 상수는 A100에 그대로 이식되는가?**
가설: 스텝 수 차이(~2x)로 step-기반 상수들이 미스매치 → 재적합으로 val_bpb 개선.
이 프레임이면 candidate가 전부 실패해도 "negative result: 시간기반 스케줄 설계가
하드웨어 강건성을 준다"라는 유효한 페이퍼가 나온다. **지는 그림이 없다.**

## Hypothesis bank (우선순위 순 — 당일 위에서부터 소진)

| ID | 한 줄 변경 | 근거(prior) | 리스크 |
|---|---|---|---|
| H1 | `DEVICE_BATCH_SIZE` A100 스루풋 최적값으로 (VRAM 80GB 동일, 대역폭 다름 → micro-batch 재적합; tok/sec 극대화) | 순수 스루풋 → 5분 내 토큰 수 증가 | 낮음 |
| H2 | Muon momentum ramp `step/300` → `progress` 기반 (파일의 시간기반 철학과 정합; A100 스텝수 절반이라 ramp가 학습의 2배 구간을 차지하는 버그성 미스매치) | 스케줄-하드웨어 정합성 | 낮음 |
| H3 | `MATRIX_LR` ±20% (스텝 수 감소 → 최적 lr 상향 가설; speedrun에서 lr 재튜닝은 안정적 소폭 개선원) | speedrun lore | 중간 |
| H4 | `window_pattern` "SSSL"→"SSSS" (어텐션 비용↓ → 스텝↑; 품질 트레이드오프 실측) | 스루풋-품질 교환 실험 | 중간 |
| H5 | `WARMDOWN_RATIO` 상향 (짧은 런에서 긴 linear cooldown이 유리하다는 speedrun 관찰) | speedrun lore | 중간 |

규칙: 한 candidate = 한 가설 = train.py 한 곳 수정. keep된 변경 위에 다음 candidate 누적.
crash/OOM → 해당 가설 폐기하고 다음 가설 (재시도는 예산 낭비).

## Timeline (당일, KST)

- 12:30 루프 시작 → cache 준비 확인 → **baseline 제출**
- ~13:10 baseline 완료 → candidate-1 (H1)
- ~15:00 candidate 마감 (몇 개 했든 중단) → **winner confirmation 제출**
- ~15:20 confirmation 회수 → 루프가 ledger에서 페이퍼 생성 (2–4p, 공식 템플릿)
- 15:30 루프 종료 → 사람 편집 → 16:30 제출

시간 규칙: `date`로 현재 시각 확인. 15:00 이후 신규 candidate 금지.
잡 1개 예상 ~10–15분 (A100, startup 포함; H100 실측 8m21s). 폴링 타임아웃이
잡을 죽이지 않음 — 타임아웃 시 `vesslctl job show`로 상태 확인 후 승인된 정리만.

## Evidence & paper

- 모든 잡 결과: `batch-job` 로그 회수 → `campaign/record_experiment.py`로
  `experiments.jsonl` append + W&B offline run (allowlist 필드만).
- 페이퍼의 모든 숫자는 experiments.jsonl에서 인용. 실패/폐기 candidate도 결과
  표에 포함 (negative evidence 누락 금지 — 우리 Track 2 리뷰어가 잡는 항목).
- 셀프리뷰: Track 2 리뷰어(`run_review.py`)를 자기 페이퍼에 실행 → 그 출력이
  self-review 제출물. **"자기 논문을 자기 감사기로 심사" = Both의 킬러 데모.**

## Mock mode (전날 리허설용)

`RALPH_T1_MOCK=1`이면 잡 제출 대신 `campaign/submit-mock.sh`가 30초 후 가짜
val_bpb를 반환. ledger 기록·keep/revert 판단·시간 규칙·페이퍼 생성 로직을
과금 없이 검증한다. 당일은 mock 플래그만 끈다.
