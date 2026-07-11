#!/usr/bin/env bash
# ralph.sh — bounded Ralph loop for Ralphthon @ICML (Team: No Free Lunch)
# usage: ./ralph.sh [PROMPT_FILE] [MAX_ITER]
# env:   RALPH_MODEL (default gpt-5.6-sol), RALPH_EFFORT (default high),
#        RALPH_TIMEOUT seconds per iteration (default 1500)
# stop:  touch .ralph_stop  (또는 max iter 도달, 또는 에이전트가 ALL TASKS COMPLETE 출력)
set -uo pipefail
cd "$(dirname "$0")"

PROMPT_FILE="${1:-PROMPT.md}"
MAX_ITER="${2:-25}"
MODEL="${RALPH_MODEL:-gpt-5.6-sol}"
EFFORT="${RALPH_EFFORT:-high}"
ITER_TIMEOUT="${RALPH_TIMEOUT:-1500}"

[ -f "$PROMPT_FILE" ] || { echo "no $PROMPT_FILE"; exit 1; }
mkdir -p logs
rm -f .ralph_stop

# 의존성 없는 타임아웃: alarm(2)은 exec를 넘어 살아남고, SIGALRM 기본 동작이 프로세스 종료.
# macOS 기본 perl만 사용 — brew/coreutils 불필요. 타임아웃 시 exit code 142(=128+SIGALRM).
run_with_timeout() { perl -e 'alarm shift @ARGV; exec @ARGV' "$ITER_TIMEOUT" "$@"; }

echo "ralph: prompt=$PROMPT_FILE max_iter=$MAX_ITER model=$MODEL/$EFFORT timeout=${ITER_TIMEOUT}s"

FAILS=0
TOKENS_TOTAL=0
for i in $(seq 1 "$MAX_ITER"); do
  if [ -f .ralph_stop ]; then echo "ralph: stop file — halting"; break; fi
  echo ""
  echo "=== iter $i/$MAX_ITER  $(date '+%H:%M:%S') ==="
  rm -f "logs/last_msg_$i.txt"   # stale 메시지 방지 (2026-07-11 쿼터 사고에서 학습)

  run_with_timeout codex exec \
    --sandbox workspace-write \
    -c approval_policy="\"never\"" \
    -m "$MODEL" \
    -c model_reasoning_effort="\"$EFFORT\"" \
    --output-last-message "logs/last_msg_$i.txt" \
    "$(cat "$PROMPT_FILE")" \
    > "logs/iter_$i.log" 2>&1
  code=$?

  last="$(head -c 300 "logs/last_msg_$i.txt" 2>/dev/null || echo '(no message)')"
  echo "exit=$code"
  echo "last: $last"

  # ── 쿼터 관리 (2026-07-11 소진 사고에서 학습) ──────────────────────────
  # 토큰 집계 (가시성만 — 모델은 절대 자동 변경하지 않는다)
  tok="$(grep -A1 'tokens used' "logs/iter_$i.log" 2>/dev/null | grep -oE '[0-9][0-9,]*' | tail -1 | tr -d ,)"
  if [ -n "$tok" ]; then
    TOKENS_TOTAL=$((TOKENS_TOTAL+tok))
    echo "tokens: iter=$tok total=$TOKENS_TOTAL"
  fi
  if grep -q "hit your usage limit" "logs/iter_$i.log" 2>/dev/null; then
    if [ "${RALPH_WAIT_RESET:-0}" = "1" ]; then
      RT="$(grep -oE 'try again at [A-Za-z]+ [0-9]+[a-z]*, [0-9]{4} [0-9]+:[0-9]+ [AP]M' "logs/iter_$i.log" | head -1 | sed -E 's/try again at //; s/([0-9]+)(st|nd|rd|th)/\1/')"
      TARGET="$(date -j -f "%b %d, %Y %l:%M %p" "$RT" +%s 2>/dev/null || true)"
      NOW="$(date +%s)"
      if [ -n "$TARGET" ] && [ "$TARGET" -gt "$NOW" ]; then
        W=$((TARGET-NOW+120))
        echo "quota: usage limit — 리셋($RT)까지 $((W/60))분 대기 후 재개"
        sleep "$W"; FAILS=0; continue
      fi
    fi
    echo "quota: usage limit (RALPH_WAIT_RESET=1이면 자동 대기)"
  fi
  # ────────────────────────────────────────────────────────────────────

  # 커밋은 바깥 루프 담당 (codex 샌드박스가 .git 쓰기를 차단함).
  # 에이전트가 .commit_msg에 남긴 메시지를 사용, 없으면 기본 메시지.
  if [ -n "$(git status --porcelain)" ]; then
    msg="ralph: iter $i (exit=$code)"
    if [ -f .commit_msg ]; then
      msg="$(head -n 1 .commit_msg | head -c 200)"
      rm -f .commit_msg
    fi
    git add . >/dev/null 2>&1
    git commit -q -m "$msg" || true
    echo "committed: $msg"
  fi

  # 완료 판정은 성공한 iteration의 fresh 메시지로만
  if [ "$code" -eq 0 ] && grep -q "ALL TASKS COMPLETE" "logs/last_msg_$i.txt" 2>/dev/null; then
    echo "ralph: agent reports all tasks complete — halting"
    break
  fi

  # 연속 실패 3회 = 하드 오류(쿼터 소진 등) — 헛돌지 말고 정지
  if [ "$code" -ne 0 ]; then
    FAILS=$((FAILS+1))
    tail -2 "logs/iter_$i.log" 2>/dev/null | head -1
    if [ "$FAILS" -ge 3 ]; then
      echo "ralph: $FAILS consecutive failures — halting (check quota/auth)"; break
    fi
    sleep 30
  else
    FAILS=0
  fi
done
echo ""
echo "ralph: finished at $(date '+%H:%M:%S')"
