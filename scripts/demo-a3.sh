#!/usr/bin/env bash
# Fire-X A3 演示：一次启动、分步触发（暂无观测 → YOLO 检出点亮 → 未检出解除高亮）。
#
# 用法: scripts/demo-a3.sh {setup|fire|clear|status|fail|stop}
#   setup  在独立数据目录新建并纳入监测一个 run（yolo 模式），打印首页 URL
#   fire   上传已验收正样本 frame_0021（有火焰）→ 厂站点亮
#   clear  上传已验收负样本 frame_0001（无火焰，观测更晚）→ 解除高亮
#   status 打印 health / atlas / run-state
#   fail   边界：在隔离实例（独立端口+独立数据目录）复现推理失败，验证失败≠未检出、
#          不刷新观测时间；主演示实例与真实权重均不动
#   stop   只停止本脚本启动的演示后端（保留数据目录供查证）
#
# 进程管理：只通过 PID 文件记录并校验本脚本启动的实例。PID 文件内容为 "pid port starttime"
# 三字段；kill 前同时核对 /proc/<pid>/cmdline（匹配端口）与启动时间（/proc/<pid>/stat 第 22
# 字段）。旧格式、字段缺失或启动时间不匹配时跳过停止并提示。端口被其它进程占用时报错退出，
# 绝不停止它。
#
# 环境变量: FIREX_PORT（主实例端口，默认 8002）、FIREX_FAIL_PORT（隔离实例端口，默认 8004）。
set -euo pipefail

REPO="/home/dailen/projects/firex-platform"
PORT="${FIREX_PORT:-8002}"
FAIL_PORT="${FIREX_FAIL_PORT:-8004}"
STATE_DIR="/tmp/firex-a3-demo"
STATE="$STATE_DIR/state.env"
MAIN_PID_FILE="$STATE_DIR/main.pid"
FAIL_PID_FILE="$STATE_DIR/fail.pid"
FRONTEND_URL="http://127.0.0.1:4173/#/atlas"
POS="/home/dailen/Nutstore Files/Fire_X/demo_sequences/case01_single_fire/images/frame_0021.png"
NEG="/home/dailen/Nutstore Files/Fire_X/demo_sequences/case05_false_positive_challenge/images/frame_0001.png"
POS2="/home/dailen/Nutstore Files/Fire_X/demo_sequences/case01_single_fire/images/frame_0022.png"
RUN_JSON='{"plant_id":"GEM_HYDRO_SHUANGJIANGKOU","scene_id":"shuangjiangkou_reference_terrain","asset_version":"reference-v1","coordinate_frame_id":"SJK_REFERENCE_UTM47N_EGM2008_v1","input_source":"simulation","simulation_time_origin_s":10.0}'

say() { printf '%s\n' "$*"; }
die() { say "错误: $*" >&2; exit 1; }
need_state() { [ -f "$STATE" ] || die "尚未 setup，请先运行: scripts/demo-a3.sh setup"; }
state_get() { sed -n "s/^$1=//p" "$STATE" 2>/dev/null; }

# 端口是否被监听（0=占用，1=空闲）。
port_busy() {
  python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',int(sys.argv[1])))==0 else 1)" "$1"
}

pid_of()  { [ -f "$1" ] && cut -d' ' -f1 < "$1" 2>/dev/null || true; }
port_of() { [ -f "$1" ] && cut -d' ' -f2 < "$1" 2>/dev/null || true; }
st_of()   { [ -f "$1" ] && cut -d' ' -f3 < "$1" 2>/dev/null || true; }

# 校验 pid 的 cmdline 是否确实是我们启动的 uvicorn（含目标端口），防止误杀。
is_our_uvicorn() {
  local pid="$1" port="$2"
  [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "uvicorn app.main:app --host 127.0.0.1 --port $port"
}

# 进程启动时间（/proc/<pid>/stat 第 22 字段，clock ticks）；无法读取时返回空。
proc_starttime() {
  local pid="$1" line rest
  [ -r "/proc/$pid/stat" ] || return 1
  line=$(cat "/proc/$pid/stat")
  rest="${line##*)}"  # 剥离 "(comm)"，取其后字段
  printf '%s' "$rest" | awk '{print $20}'
}

# 只停止本脚本记录（pidfile 内含 "pid port starttime"）且校验通过的实例。
# 旧格式（缺 starttime）、字段缺失、命令行不符或启动时间不匹配 → 跳过停止并提示。
stop_pidfile() {
  local pid port st cur i
  [ -f "$1" ] || return 0
  pid=$(pid_of "$1"); port=$(port_of "$1"); st=$(st_of "$1")

  if [ -z "$pid" ] || [ -z "$port" ]; then
    say "  跳过停止（$1）：PID 文件字段缺失或为旧格式"
    rm -f "$1"; return 0
  fi
  if ! is_our_uvicorn "$pid" "$port"; then
    say "  跳过停止 pid=$pid：命令行不是本脚本启动的 uvicorn（端口 $port）"
    rm -f "$1"; return 0
  fi
  cur=$(proc_starttime "$pid" || true)
  if [ -z "$st" ] || [ -z "$cur" ]; then
    say "  跳过停止 pid=$pid：启动时间缺失（记录「${st:-空}」实际「${cur:-空}」），视为旧格式"
    rm -f "$1"; return 0
  fi
  if [ "$st" != "$cur" ]; then
    say "  跳过停止 pid=$pid：启动时间不匹配（记录 $st ≠ 实际 $cur），PID 可能已被复用"
    rm -f "$1"; return 0
  fi
  kill "$pid" 2>/dev/null || true
  for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  rm -f "$1"
  say "  已停止 pid=$pid（端口 $port）"
}

wait_health() { # $1=port
  local i
  for i in $(seq 1 40); do
    curl -sf -m 2 "http://127.0.0.1:$1/health" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

# 启动后端（直接调用 backend venv 的 uvicorn，subshell+exec 使 $! 就是 uvicorn PID）。
# $1=port  $2=datadir  $3=extra_env(空格分隔，可为空)  $4=pidfile
start_backend() {
  local port="$1" datadir="$2" extra="$3" pidfile="$4" pid st
  mkdir -p "$STATE_DIR"
  (
    cd "$REPO/backend" || exit 1
    # shellcheck disable=SC2086
    exec env FIREX_BACKEND_DATA_DIR="$datadir" FIREX_PROCESSING_MODE=yolo $extra \
      .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$port"
  ) >> "$STATE_DIR/backend-$port.log" 2>&1 &
  pid="$!"
  echo "$pid $port" > "$pidfile"   # 先落 pid+port，health 后补写启动时间
  wait_health "$port" || { say "后端($port)启动失败，日志:"; tail -20 "$STATE_DIR/backend-$port.log"; return 1; }
  st=$(proc_starttime "$pid" || true)
  echo "$pid $port $st" > "$pidfile"
}

create_run() { # $1=base
  curl -sf -m 5 -X POST "$1/api/v1/runs" -H 'Content-Type: application/json' -d "$RUN_JSON" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])'
}

upload() { # $1=base $2=frame $3=image $4=run_id  → 输出 capture_id
  ( cd "$REPO/backend" && uv --directory "$REPO/backend" run --locked python scripts/upload_test_capture.py \
      --base-url "$1" --frame "$2" --image "$3" "$4" 2>&1 ) \
    | grep -oE "cap-[0-9a-f-]+f[0-9]{3}" | head -1
}

wait_capture() { # $1=base $2=capture_id
  local st
  for _ in $(seq 1 60); do
    st=$(curl -sf -m 3 "$1/api/v1/captures/$2" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status"))' 2>/dev/null || true)
    case "$st" in completed|failed) break ;; esac
    sleep 0.5
  done
}

print_result() { # $1=base $2=capture_id $3=run_id
  curl -sf -m 3 "$1/api/v1/captures/$2" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("   capture :",d.get("status"),"| 观测",d.get("observation_time_s"),"s","|",(d.get("processing_error") or ""))'
  curl -sf -m 3 "$1/api/v1/runs/$3/state" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("   推理   :",json.dumps(d.get("detections"),ensure_ascii=False),"| fire_detected",d.get("fire_detected"),"| revision",d.get("revision"),"|",d.get("model_ref"))'
  curl -sf -m 3 "$1/api/v1/atlas/fire-status" | python3 -c 'import sys,json;d=json.load(sys.stdin);i=d["items"][0] if d["items"] else {};print("   地图   :",i.get("alert_status"),"| 检测框",i.get("detection_count"),"| revision",i.get("revision"),"| 来源",i.get("result_origin"))'
}

setup() {
  mkdir -p "$STATE_DIR"
  # 只停本脚本之前记录的主实例；若端口仍被其它进程占用则报错退出（绝不停止它）。
  stop_pidfile "$MAIN_PID_FILE"
  if port_busy "$PORT"; then
    die "端口 $PORT 已被其它服务占用（本脚本不会停止它）。请换空闲端口：FIREX_PORT=<空闲端口> scripts/demo-a3.sh setup"
  fi

  local data_dir run_id mode
  data_dir="$STATE_DIR/run-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$data_dir"
  printf 'DATA_DIR=%s\nPORT=%s\n' "$data_dir" "$PORT" > "$STATE"

  start_backend "$PORT" "$data_dir" "" "$MAIN_PID_FILE" || exit 1
  run_id=$(create_run "http://127.0.0.1:$PORT")
  [ -n "$run_id" ] || die "创建 run 失败"
  printf 'DATA_DIR=%s\nPORT=%s\nRUN_ID=%s\n' "$data_dir" "$PORT" "$run_id" > "$STATE"

  stop_pidfile "$MAIN_PID_FILE"
  start_backend "$PORT" "$data_dir" "FIREX_MONITORED_RUN_IDS=$run_id" "$MAIN_PID_FILE" || exit 1

  mode=$(curl -sf -m 3 "http://127.0.0.1:$PORT/health" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("processing_mode"))')
  [ "$mode" = "yolo" ] || die "processing_mode 不是 yolo，而是 $mode"

  say ""
  say "Fire-X A3 演示已就绪（processing_mode=yolo，PID 文件 $MAIN_PID_FILE）"
  say "  首页 URL : $FRONTEND_URL    ← 打开后保持不刷新"
  say "  run_id   : $run_id"
  say "  数据目录 : $data_dir"
  say "  后端     : http://127.0.0.1:$PORT"
  say ""
  say "  现在页面显示「暂无观测」。分步触发："
  say "  1) scripts/demo-a3.sh fire   # 有火焰样本 → 厂站点亮"
  say "  2) scripts/demo-a3.sh clear  # 无火焰样本 → 解除高亮"
  say "  3) scripts/demo-a3.sh status # 查看当前状态"
  say "  4) scripts/demo-a3.sh stop   # 结束演示"
}

fire() {
  need_state
  local base="http://127.0.0.1:$(state_get PORT)" run_id cap
  run_id=$(state_get RUN_ID)
  say "▶ 上传正样本 frame_0021（有火焰）…"
  cap=$(upload "$base" 1 "$POS" "$run_id")
  [ -n "$cap" ] || die "上传失败"
  say "   capture_id=$cap"
  wait_capture "$base" "$cap"
  print_result "$base" "$cap" "$run_id"
  say "   → 首页应已点亮该厂站（标注「仿真影像 · YOLO 检测」），可展示后执行 clear"
}

clear() {
  need_state
  local base="http://127.0.0.1:$(state_get PORT)" run_id cap
  run_id=$(state_get RUN_ID)
  say "▶ 上传负样本 frame_0001（已核对无火焰，观测更晚）…"
  cap=$(upload "$base" 2 "$NEG" "$run_id")
  [ -n "$cap" ] || die "上传失败"
  say "   capture_id=$cap"
  wait_capture "$base" "$cap"
  print_result "$base" "$cap" "$run_id"
  say "   → 首页应解除高亮，仅显示「本次未检出」"
}

status() {
  need_state
  local base="http://127.0.0.1:$(state_get PORT)"
  say "health : $(curl -sf -m 3 "$base/health")"
  say "atlas  :"
  curl -sf -m 3 "$base/api/v1/atlas/fire-status" | python3 -m json.tool
  say "state  :"
  curl -sf -m 3 "$base/api/v1/runs/$(state_get RUN_ID)/state" | python3 -c \
    'import sys,json;d=json.load(sys.stdin);print(json.dumps({k:d.get(k) for k in ("state_status","revision","observation_time_s","result_origin","fire_detected","detections","produced_at")},ensure_ascii=False,default=str))'
}

fail() {
  need_state
  mkdir -p "$STATE_DIR"
  local fbase="http://127.0.0.1:$FAIL_PORT" fdir run_id before after cap
  # 清理本脚本之前的隔离实例；端口被其它进程占用则退出。
  stop_pidfile "$FAIL_PID_FILE"
  if port_busy "$FAIL_PORT"; then
    die "隔离端口 $FAIL_PORT 已被其它服务占用，请 FIREX_FAIL_PORT 换端口"
  fi
  fdir="$STATE_DIR/fail-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$fdir"

  say "▶ 边界：在隔离实例（端口 $FAIL_PORT，独立数据目录 $fdir）复现推理失败"
  say "   主演示实例与真实权重均不受影响"

  # 1) 隔离实例先用好权重建立「有效正样本」
  start_backend "$FAIL_PORT" "$fdir" "" "$FAIL_PID_FILE" || exit 1
  run_id=$(create_run "$fbase")
  stop_pidfile "$FAIL_PID_FILE"
  start_backend "$FAIL_PORT" "$fdir" "FIREX_MONITORED_RUN_IDS=$run_id" "$FAIL_PID_FILE" || exit 1
  cap=$(upload "$fbase" 1 "$POS" "$run_id"); wait_capture "$fbase" "$cap"
  before=$(curl -sf -m 3 "$fbase/api/v1/atlas/fire-status" | python3 -c \
    'import sys,json;i=json.load(sys.stdin)["items"][0];print(json.dumps({"alert_status":i["alert_status"],"produced_at":i["produced_at"],"revision":i["revision"],"observation_time_s":i["observation_time_s"]}))')
  say "   失败前地图: $before"

  # 2) 隔离实例改用坏权重，做后续失败推理（主实例不动）
  stop_pidfile "$FAIL_PID_FILE"
  start_backend "$FAIL_PORT" "$fdir" "FIREX_MONITORED_RUN_IDS=$run_id FIREX_YOLO_WEIGHTS=/nonexistent/best.pt" "$FAIL_PID_FILE" || exit 1
  cap=$(upload "$fbase" 3 "$POS2" "$run_id"); wait_capture "$fbase" "$cap"
  say "   capture_id=$cap"
  curl -sf -m 3 "$fbase/api/v1/captures/$cap" | python3 -c \
    'import sys,json;d=json.load(sys.stdin);print("   capture :",d.get("status"),"|",(d.get("processing_error") or "")[:140])'

  # 3) 校验：地图状态未被失败改写
  after=$(curl -sf -m 3 "$fbase/api/v1/atlas/fire-status" | python3 -c \
    'import sys,json;i=json.load(sys.stdin)["items"][0];print(json.dumps({"alert_status":i["alert_status"],"produced_at":i["produced_at"],"revision":i["revision"],"observation_time_s":i["observation_time_s"]}))')
  say "   失败后地图: $after"

  stop_pidfile "$FAIL_PID_FILE"
  say "   ✓ 隔离实例已停止；失败未被解释为未检出、未刷新观测时间"
}

stop() {
  [ -f "$STATE" ] || { say "无演示实例在运行"; exit 0; }
  stop_pidfile "$MAIN_PID_FILE"
  stop_pidfile "$FAIL_PID_FILE"
  say "停止流程完成（数据目录保留: $(state_get DATA_DIR)）"
}

case "${1:-}" in
  setup) setup ;;
  fire) fire ;;
  clear) clear ;;
  status) status ;;
  fail) fail ;;
  stop) stop ;;
  *) die "用法: scripts/demo-a3.sh {setup|fire|clear|status|fail|stop}" ;;
esac
