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

TIMEOUT_CMD=""
command -v gtimeout >/dev/null 2>&1 && TIMEOUT_CMD="gtimeout $ITER_TIMEOUT"

echo "ralph: prompt=$PROMPT_FILE max_iter=$MAX_ITER model=$MODEL/$EFFORT timeout=${ITER_TIMEOUT}s"

for i in $(seq 1 "$MAX_ITER"); do
  if [ -f .ralph_stop ]; then echo "ralph: stop file — halting"; break; fi
  echo ""
  echo "=== iter $i/$MAX_ITER  $(date '+%H:%M:%S') ==="

  $TIMEOUT_CMD codex exec \
    --sandbox workspace-write \
    --ask-for-approval never \
    -m "$MODEL" \
    -c model_reasoning_effort="\"$EFFORT\"" \
    --output-last-message "logs/last_msg_$i.txt" \
    "$(cat "$PROMPT_FILE")" \
    > "logs/iter_$i.log" 2>&1
  code=$?

  last="$(head -c 300 "logs/last_msg_$i.txt" 2>/dev/null || echo '(no message)')"
  echo "exit=$code"
  echo "last: $last"

  # 에이전트가 커밋을 깜빡했으면 안전 커밋 (하네스 레포 한정; cookbook fork에는 이 스크립트 쓰지 않음)
  if [ -n "$(git status --porcelain)" ]; then
    git add . >/dev/null 2>&1
    git commit -q -m "ralph: safety commit iter $i (exit=$code)" || true
    echo "note: safety commit created"
  fi

  if grep -q "ALL TASKS COMPLETE" "logs/last_msg_$i.txt" 2>/dev/null; then
    echo "ralph: agent reports all tasks complete — halting"
    break
  fi
done
echo ""
echo "ralph: finished at $(date '+%H:%M:%S')"
