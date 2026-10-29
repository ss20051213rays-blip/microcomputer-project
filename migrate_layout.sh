#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# migrate_layout.sh — Stage 1 目录机械迁移（零行为变更，保留 git 历史）
#
#   用法:
#     bash migrate_layout.sh --dry-run    # 只打印动作，不改动
#     bash migrate_layout.sh              # 执行迁移 + 自动提交
#     bash migrate_layout.sh --no-commit  # 执行迁移，不提交（自行检查后再提交）
#
#   前置: git 工作区干净；在仓库内任意位置执行均可。
# ---------------------------------------------------------------------------
set -euo pipefail

DRY_RUN=0
DO_COMMIT=1
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --no-commit) DO_COMMIT=0 ;;
    -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[FATAL] 当前目录不在 git 仓库内" >&2; exit 1; }
cd "$ROOT"

echo "仓库根: $ROOT"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "[FATAL] 存在未提交的已跟踪改动，请先 commit 或 stash：" >&2
  git status --short --untracked-files=no >&2
  exit 1
fi
if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "[WARN] 存在未跟踪文件（迁移不会动它们）："
  git ls-files --others --exclude-standard | sed 's/^/        /'
fi

# ── 1. 创建目录骨架 ────────────────────────────────────────────────────────
DIRS=(
  src/pantilt/core
  src/pantilt/domain
  src/pantilt/perception
  src/pantilt/actuation
  src/pantilt/runtime
  scripts/hw
  scripts/eval
  tests
  docs
  assets/audio
  logs
)
for d in "${DIRS[@]}"; do
  [[ $DRY_RUN -eq 1 ]] && echo "mkdir -p $d" || mkdir -p "$d"
done

# ── 2. git mv 迁移 ─────────────────────────────────────────────────────────
MOVES=(
  "src/app.py|src/pantilt/app.py"
  "src/config.py|src/pantilt/core/config.py"
  "src/controller.py|src/pantilt/domain/controller.py"
  "src/audio.py|src/pantilt/perception/audio.py"
  "src/vision.py|src/pantilt/perception/vision.py"
  "src/servo.py|src/pantilt/actuation/servo.py"
  "scripts/camera_preview.py|scripts/hw/camera_preview.py"
  "scripts/record_audio.py|scripts/hw/record_audio.py"
  "scripts/servo_sweep.py|scripts/hw/servo_sweep.py"
  "scripts/healthcheck.py|scripts/hw/healthcheck.py"
  "scripts/evaluate_audio.py|scripts/eval/evaluate_audio.py"
  "scripts/test_aruco.py|scripts/hw/aruco_probe.py"
  "scripts/test_face.py|scripts/hw/face_probe.py"
  "scripts/test_sed.py|scripts/hw/sed_probe.py"
  "scripts/test_bus_servo.py|scripts/hw/bus_servo_probe.py"
  "scripts/test_follow_logic.py|tests/test_controller.py"
  "scripts/test_fsm.py|tests/test_state_machine.py"
  "scripts/test_2dof_fsm.py|tests/test_2dof_loop.py"
  "视听融合声源定位与目标跟踪云台-开发计划.md|docs/视听融合声源定位与目标跟踪云台-开发计划.md"
  "人工待办与硬件验证.md|docs/人工待办与硬件验证.md"
  "项目日志.md|docs/项目日志.md"
)

mv_file() {
  local old="$1" new="$2"
  if [[ ! -e "$old" ]]; then echo "  SKIP(不存在) $old"; return 0; fi
  if [[ -e "$new" ]]; then echo "  SKIP(目标已存在) $new"; return 0; fi
  if [[ $DRY_RUN -eq 1 ]]; then echo "  git mv $old -> $new"; return 0; fi
  if git ls-files --error-unmatch "$old" >/dev/null 2>&1; then
    git mv "$old" "$new"
  else
    mv "$old" "$new"
  fi
}

for pair in "${MOVES[@]}"; do
  mv_file "${pair%%|*}" "${pair##*|}"
done

# 旧占位文件
for keep in src/.gitkeep scripts/.gitkeep; do
  [[ -f "$keep" ]] || continue
  if [[ $DRY_RUN -eq 1 ]]; then echo "  git rm $keep"; else git rm -q "$keep"; fi
done

# ── 3. 生成包骨架文件 ─────────────────────────────────────────────────────
if [[ $DRY_RUN -eq 0 ]]; then
  write_if_absent() {
    local path="$1"; shift
    [[ -e "$path" ]] && { echo "  KEEP $path"; return 0; }
    cat > "$path"
    echo "  CREATE $path"
  }

  for pkg in pantilt pantilt/core pantilt/domain pantilt/perception pantilt/actuation pantilt/runtime; do
    write_if_absent "src/$pkg/__init__.py" <<EOF
"""$(basename "$pkg") 子包。"""
EOF
  done

  write_if_absent "src/pantilt/__main__.py" <<'EOF'
"""python -m pantilt 入口。"""
from pantilt.app import main

if __name__ == "__main__":
    main()
EOF

  write_if_absent "src/pantilt/core/paths.py" <<'EOF'
"""项目路径唯一来源：禁止在其它模块手写 '..' 相对路径。"""
from pathlib import Path

# src/pantilt/core/paths.py -> 上溯 4 级得到仓库根
PROJECT_ROOT = Path(__file__).resolve().parents[3]

CONFIG_DIR = PROJECT_ROOT / "configs"
DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
ASSETS_DIR = PROJECT_ROOT / "assets"
EOF

  # 占位文件写入非空标记，避免 git 把空 .gitkeep 误判为重命名
  printf '# 目录占位，保持空目录纳入版本控制\n' > assets/audio/.gitkeep
  printf '# 运行日志输出目录\n' > logs/.gitkeep
fi

# ── 4. import / 路径批量重写 ──────────────────────────────────────────────
if [[ $DRY_RUN -eq 1 ]]; then
  echo "  [dry-run] 跳过 import 重写"
else
  python3 - <<'PY'
import pathlib, re, sys

root = pathlib.Path.cwd()

IMPORT_MAP = [
    ("from src.config import",     "from pantilt.core.config import"),
    ("from src.controller import", "from pantilt.domain.controller import"),
    ("from src.audio import",      "from pantilt.perception.audio import"),
    ("from src.vision import",     "from pantilt.perception.vision import"),
    ("from src.servo import",      "from pantilt.actuation.servo import"),
    ("from src.app import",        "from pantilt.app import"),
]

DOC_MAP = {
    "scripts/test_2dof_fsm.py":    "tests/test_2dof_loop.py",
    "scripts/test_follow_logic.py":"tests/test_controller.py",
    "scripts/test_fsm.py":         "tests/test_state_machine.py",
    "scripts/test_bus_servo.py":   "scripts/hw/bus_servo_probe.py",
    "scripts/test_aruco.py":       "scripts/hw/aruco_probe.py",
    "scripts/test_face.py":        "scripts/hw/face_probe.py",
    "scripts/test_sed.py":         "scripts/hw/sed_probe.py",
    "scripts/camera_preview.py":   "scripts/hw/camera_preview.py",
    "scripts/record_audio.py":     "scripts/hw/record_audio.py",
    "scripts/servo_sweep.py":      "scripts/hw/servo_sweep.py",
    "scripts/healthcheck.py":      "scripts/hw/healthcheck.py",
    "scripts/evaluate_audio.py":   "scripts/eval/evaluate_audio.py",
    "src/controller.py":           "src/pantilt/domain/controller.py",
    "src/audio.py":                "src/pantilt/perception/audio.py",
    "src/vision.py":               "src/pantilt/perception/vision.py",
    "src/servo.py":                "src/pantilt/actuation/servo.py",
    "src/config.py":               "src/pantilt/core/config.py",
    "src/app.py":                  "src/pantilt/app.py",
    "src/speaker.py":              "src/pantilt/media/speaker.py",
    "src/display.py":              "src/pantilt/media/display.py",
}
DOC_MAP_ORDERED = sorted(DOC_MAP.items(), key=lambda kv: -len(kv[0]))

DIRNAME_RE = re.compile(r"""(dirname\(__file__\)\s*,\s*)(['"])\.\.\2""")


def relocate(dirname_line: str, depth: int) -> str:
    """把 os.path.dirname(__file__), '..' 补齐到仓库根（depth 级）。"""
    extra = ", ".join(["'..'"] * depth)
    return DIRNAME_RE.sub(lambda m: f"{m.group(1)}{extra}", dirname_line, count=1)


changed = []

for path in sorted(list(root.glob("src/**/*.py")) + list(root.glob("scripts/**/*.py"))
                   + list(root.glob("tests/**/*.py"))):
    depth = len(path.parent.relative_to(root).parts)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out, touched = [], False

    for line in lines:
        new = line
        if "sys.path.append" in new and "dirname(__file__)" in new:
            parts = ", ".join(["'..'"] * depth + ["'src'"])
            indent = new[: len(new) - len(new.lstrip())]
            new = (f"{indent}sys.path.append(os.path.abspath("
                   f"os.path.join(os.path.dirname(__file__), {parts})))\n")
        elif "dirname(__file__)" in new and depth > 1:
            new = relocate(new, depth)
        for old, repl in IMPORT_MAP:
            new = new.replace(old, repl)
        if new != line:
            touched = True
        out.append(new)

    if touched:
        path.write_text("".join(out), encoding="utf-8")
        changed.append(str(path.relative_to(root)))

# 文档路径
for md in [root / "README.md"] + sorted(root.glob("docs/*.md")):
    if not md.exists():
        continue
    text = original = md.read_text(encoding="utf-8")
    for old, new in DOC_MAP_ORDERED:
        text = text.replace(old, new)
    if md.name == "README.md":
        for name in ("视听融合声源定位与目标跟踪云台-开发计划.md",
                     "人工待办与硬件验证.md", "项目日志.md"):
            text = text.replace(f"]({name})", f"](docs/{name})")
        text = text.replace("python -m src.app", "python -m pantilt")
    if text != original:
        md.write_text(text, encoding="utf-8")
        changed.append(str(md.relative_to(root)))

print(f"  重写 {len(changed)} 个文件")
for c in changed:
    print(f"    - {c}")
PY
fi

# ── 5. 语法闸门 ───────────────────────────────────────────────────────────
if [[ $DRY_RUN -eq 0 ]]; then
  if ! python3 -m compileall -q src scripts tests >/dev/null; then
    echo "[FATAL] 语法编译失败，已中止（未提交）。请 git checkout -- . 回滚。" >&2
    exit 1
  fi
  echo "  compileall 通过"
  find . -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
fi

# ── 6. 提交 ───────────────────────────────────────────────────────────────
if [[ $DRY_RUN -eq 0 && $DO_COMMIT -eq 1 ]]; then
  git add -A
  git commit -q -m "refactor(layout): Stage1 机械迁移至 src/pantilt + scripts/hw + tests"
  echo "  已提交: $(git log --oneline -1)"
fi

cat <<'EOF'

────────────── Stage1 完成，下一步（Stage2 手工） ──────────────
1. 新增 pyproject.toml（package-dir = src，入口 pantilt = pantilt.app:main）
2. pip install -e ".[dev]" 后删除 11 处 sys.path 补丁
3. 用 core/paths.py 收敛 10 处重复配置路径
4. 抽 core/types.py（SystemState / AudioEvent / VisionObservation）
5. 拆 app.py：state_machine.py / laser.py / console.py；run_simulation_test 移入 tests/
6. 树莓派 venv 内验证：
     python -m pantilt --simulate
     pytest -q
     python scripts/hw/healthcheck.py
回滚： git reset --hard pre-refactor
EOF
