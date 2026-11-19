#!/usr/bin/env bash
# Restart the existing Shuangjiangkou run after a local reboot.
set -euo pipefail

fail() { printf 'Fire-X: %s\n' "$*" >&2; exit 1; }
mode="${1:---local}"
case "$mode" in
  --local|--lan) ;;
  *) fail '用法: bash start-sjk-local.sh [--local|--lan]' ;;
esac

repo="${FIREX_REPO_DIR:-$HOME/projects/firex-platform}"
cd -- "$repo" || fail "找不到仓库：$repo"
repo="$(pwd -P)"
run_id="${FIREX_RUN_ID:-7309fb93-6db0-4f7e-89e5-f98757759bab}"
backend_python="$repo/backend/.venv/bin/python"
yolo_python="${FIREX_YOLO_PYTHON:-$HOME/vggt/vggt-env/bin/python}"
yolo_weights="${FIREX_YOLO_WEIGHTS:-$HOME/vggt/runs/detect/train_full_v1/weights/best.pt}"
vite="$repo/frontend/node_modules/.bin/vite"
for binary in "$backend_python" "$yolo_python" "$vite"; do
  [[ -x "$binary" ]] || fail "缺少可执行文件：$binary"
done
[[ -r "$yolo_weights" ]] || fail "找不到 YOLO 权重：$yolo_weights"

host="${FIREX_BIND_HOST:-127.0.0.1}"
if [[ "$mode" == --lan && -z "${FIREX_BIND_HOST:-}" ]]; then
  host="$(ip -o -4 addr show up scope global | awk '
    $2 ~ /^(en|eth)/ {split($4, a, "/"); if (wired=="") wired=a[1]}
    $2 ~ /^(wl)/ {split($4, a, "/"); if (wifi=="") wifi=a[1]}
    END {print (wired?wired:wifi)}
  ')" || fail '找不到本机网卡地址。'
  [[ -n "$host" ]] || fail '有线和 Wi-Fi 都没有 IPv4；仅本机查看可不带 --lan。'
fi

# Locate the database in read-only mode. Never create a blank run or pick an
# arbitrary copy if the same run was backed up into several worktrees.
data="$(python3 - "$repo" "$run_id" "${FIREX_BACKEND_DATA_DIR:-}" "$host" <<'PY'
import ipaddress
import socket
import sqlite3
import sys
from pathlib import Path

repo, run_id, override, host = sys.argv[1:]
repo = Path(repo)
binding = ("GEM_HYDRO_SHUANGJIANGKOU", "sjk_hydropower_sim_v0_1", "hydro-sim-v0.1-local",
           "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1")

def matches(db):
    if not db.is_file():
        return False
    try:
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            return conn.execute(
                "SELECT plant_id, scene_id, asset_version, coordinate_frame_id FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone() == binding
    except sqlite3.Error:
        return False

roots = {repo / "runtime-data", repo.parent / "firex-platform" / "runtime-data",
         repo.parent / "firex-platform-develop" / "runtime-data"}
if override:
    chosen = Path(override).expanduser().resolve() / "runs.sqlite3"
    if not matches(chosen):
        sys.exit(f"指定的数据库中找不到原双江口 run：{chosen}")
else:
    preferred = {p.resolve() for root in roots
                 if matches(p := root / "e3-unity-lan-20261110-220003" / "runs.sqlite3")}
    found = preferred or {p.resolve() for root in roots for p in root.rglob("runs.sqlite3") if matches(p)}
    if len(found) != 1:
        locations = "\n".join(str(p) for p in sorted(found))
        sys.exit(f"无法唯一定位原双江口 run {run_id}。请用 FIREX_BACKEND_DATA_DIR 指定数据目录。\n{locations}")
    chosen = next(iter(found))

try:
    addr = ipaddress.IPv4Address(host)
    if addr.is_unspecified:
        raise ValueError("请使用本机 IPv4，不能绑定 0.0.0.0")
    for ip, port in ((host, 8010), ("127.0.0.1", 4173)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((ip, port))
except (OSError, ValueError) as error:
    sys.exit(f"启动地址不可用：{error}。先查 ss -4 -ltn，脚本不会停止其他服务。")
print(chosen.parent)
PY
)" || exit 1

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

origin="http://$host:8010"
ui='http://127.0.0.1:4173'
printf 'DATA_DIR=%s\nRUN_ID=%s\n' "$data" "$run_id"
(
  cd backend
  exec env FIREX_BACKEND_DATA_DIR="$data" FIREX_MONITORED_RUN_IDS="$run_id" FIREX_PROCESSING_MODE=yolo \
    FIREX_YOLO_PYTHON="$yolo_python" FIREX_YOLO_WEIGHTS="$yolo_weights" \
    FIREX_YOLO_IMGSZ=1280 FIREX_YOLO_CONF=0.25 \
    "$backend_python" -m uvicorn app.main:app --host "$host" --port 8010
) &
pids+=("$!")

await_url() {
  local addr="$1" pid="$2" attempt
  for ((attempt=0; attempt<55; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 2 "$addr" 2>/dev/null; then return 0; fi
    kill -0 "$pid" 2>/dev/null || fail "服务在就绪前退出：$addr"
    sleep 0.2
  done
  fail "服务未就绪：$addr"
}

await_url "$origin/health" "${pids[0]}" | python3 -c '
import json, sys
r = json.load(sys.stdin)
if (r.get("status"), r.get("service"), r.get("processing_mode")) != ("ok", "firex-backend", "yolo"):
    sys.exit(f"后端模式不匹配：{r}")
'
(
  cd frontend
  exec env VITE_BACKEND_ORIGIN="$origin" VITE_FIREX_API_ORIGIN='' VITE_USE_POLLING=true \
    "$vite" --host 127.0.0.1 --port 4173 --strictPort
) &
pids+=("$!")

await_url "$ui/health" "${pids[1]}" >/dev/null
curl --noproxy '*' -fsS --max-time 5 "$ui/api/v1/runs/$run_id/state" | python3 -c '
import json, sys
r = json.load(sys.stdin)
if r.get("run_id") != sys.argv[1]:
    sys.exit("前端代理没有指向原 run")
print("原 run 已连接（revision=%s）" % r.get("revision"))
' "$run_id"
curl --noproxy '*' -fsS --max-time 5 "$ui/api/v1/atlas/fire-status" | python3 -c '
import json, sys
r = json.load(sys.stdin)
if sys.argv[1] not in r.get("monitored_run_ids", ()):
    sys.exit("首页未监听原 run")
' "$run_id"
printf '\nBASE_URL=%s\n首页：%s/#/atlas\n三维：%s/#/scene/sjk_hydropower_sim_v0_1?run_id=%s\n保持本终端打开；Ctrl+C 停止本次启动的两个服务。\n' \
  "$origin" "$ui" "$ui" "$run_id"
wait -n "${pids[@]}"
