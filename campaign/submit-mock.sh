#!/usr/bin/env bash
# submit-mock.sh — 리허설용 가짜 VESSL job. 실제 과금/제출 없이 캠페인 루프의
# 판단 로직(keep/revert, ledger, 시간 규칙)을 검증한다.
# usage: bash campaign/submit-mock.sh <trial-name>
# 출력: 실제 잡 로그 흉내 + 마지막 줄 "val_bpb: <float>"
set -euo pipefail
TRIAL="${1:-unnamed}"
WAIT="${MOCK_WAIT:-20}"

echo "[mock] job created: autoresearch-${TRIAL} (resourcespec-a100x1 @ cluster-betelgeuse)"
echo "[mock] state: queued"
sleep 2
echo "[mock] state: running (simulating ${WAIT}s training)"
sleep "$WAIT"

# 가짜 val_bpb: baseline은 1.0107 근처 고정, 나머지는 랜덤하게 개선/악화/충돌
case "$TRIAL" in
  baseline*) V="1.010812" ;;
  *confirm*) V="${MOCK_CONFIRM_BPB:-1.006912}" ;;
  *)
    R=$((RANDOM % 10))
    if [ "$R" -lt 1 ]; then
      echo "[mock] RuntimeError: CUDA out of memory (simulated crash)"
      echo "[mock] state: failed"
      exit 1
    elif [ "$R" -lt 5 ]; then
      V="1.00$((RANDOM % 900 + 100))"   # 개선 (1.0010~1.0099)
    else
      V="1.01$((RANDOM % 900 + 100))"   # 악화 (1.0110~1.0199)
    fi ;;
esac

echo "[mock] step 04980 (100.0%) | loss: 0.$((RANDOM % 90000 + 10000)) | mfu: 38.2% | remaining: 0s"
echo "[mock] Total training time: 300s"
echo "[mock] state: succeeded"
echo "val_bpb: ${V}"
