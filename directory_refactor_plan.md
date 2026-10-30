# 目录重构方案

本文基于仓库现状，而不是模板中的技术栈示例：这是一个 **Python 3.9+、`src/` 布局的 Raspberry Pi 视听融合云台项目**，包含状态机、音视频处理、硬件控制和调试脚本，规模属于小型模块化单体。

## 1. 痛点诊断

目前的结构已经有 `domain`、`actuation`、`perception` 等模块，整体方向是合理的，不需要推倒重来。主要可以改善的是模块边界和运行入口：

1. **`core` 混合了不同职责**  
   `core/types.py` 是领域类型，而 `config.py`、`paths.py`、`logging_setup.py` 属于基础设施。它们放在一起，会让“核心业务”与“项目运行支持”边界不清晰。

2. **应用入口承担了过多职责**  
   `src/pantilt/app.py` 同时包含命令行解析、组件装配、系统生命周期和主循环。随着功能增加，这些职责容易互相牵连。

3. **生产代码依赖测试模块**  
   `app.py` 的 `--simulate` 分支导入 `tests.test_state_machine`。这使运行入口依赖测试代码，也让模拟验收逻辑难以独立复用。

4. **仓库路径与安装包路径存在耦合**  
   `paths.py` 通过源码位置推导仓库根目录，并从根目录读取 `configs/default.yaml`。这适合仓库内或 editable 安装，但通过 wheel 安装时，配置文件未必存在于预期位置。

5. **已有的合理分组不应为了重构而搬动**  
   `scripts/hw`、`scripts/eval`、`configs`、`assets`、`data`、`logs` 目前职责清楚，建议保留。

## 2. 目标目录蓝图

建议采用轻量的分层模块化结构：**领域逻辑 → 应用流程 → 适配器**，由组合入口连接具体实现。对当前项目不必马上引入复杂的依赖注入框架或完整端口体系。

```text
.
├── .gitignore
├── .workbuddy/
│   └── memory/
│       └── 2026-10-29.md
├── README.md
├── directory_refactor_plan.md
├── pyproject.toml
├── assets/
│   └── audio/
│       └── .gitkeep
├── configs/
│   └── default.yaml
├── data/
│   └── .gitkeep
├── docs/
│   ├── 人工待办与硬件验证.md
│   ├── 视听融合声源定位与目标跟踪云台-开发计划.md
│   └── 项目日志.md
├── logs/
│   └── .gitkeep
├── scripts/
│   ├── eval/
│   │   └── evaluate_audio.py
│   └── hw/
│       ├── aruco_probe.py
│       ├── bus_servo_probe.py
│       ├── camera_preview.py
│       ├── face_probe.py
│       ├── healthcheck.py
│       ├── record_audio.py
│       ├── sed_probe.py
│       └── servo_sweep.py
├── src/
│   └── pantilt/
│       ├── __init__.py
│       ├── __main__.py
│       ├── bootstrap.py               # 新增：组装具体应用组件
│       ├── cli.py                     # 新增：命令行入口
│       ├── application/
│       │   ├── __init__.py
│       │   ├── tracker.py             # 应用生命周期与控制流程
│       │   └── simulation.py          # 从测试文件提取的模拟验收逻辑
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── controller.py
│       │   ├── state_machine.py
│       │   └── types.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── actuation/
│       │   │   ├── __init__.py
│       │   │   ├── laser.py
│       │   │   └── servo.py
│       │   ├── perception/
│       │   │   ├── __init__.py
│       │   │   ├── audio.py
│       │   │   └── vision.py
│       │   └── runtime/
│       │       ├── __init__.py
│       │       └── console.py
│       └── infrastructure/
│           ├── __init__.py
│           ├── config.py
│           ├── logging_setup.py
│           └── paths.py
└── tests/
    ├── conftest.py
    ├── test_2dof_loop.py
    ├── test_controller.py
    └── test_state_machine.py
```

`__pycache__`、`.pytest_cache`、`*.egg-info` 是生成文件，不属于需要迁移的源码目录；应继续由 `.gitignore` 排除。

### 核心目录职责

| 目录 | 应放入 | 不应放入 |
|---|---|---|
| `domain/` | 状态机、控制算法、领域数据类型 | YAML 读取、日志初始化、相机/舵机等硬件代码 |
| `application/` | 系统用例、跟踪流程、模拟验收逻辑 | `argparse`、具体硬件驱动、路径解析 |
| `adapters/actuation/` | 舵机、激光等执行设备实现 | 状态机规则、CLI 参数解析 |
| `adapters/perception/` | 音频采集与分析、相机与视觉实现 | 通用配置加载、业务状态转换 |
| `adapters/runtime/` | 控制台监听等运行时交互 | 领域策略、硬件设备实现 |
| `infrastructure/` | 配置、日志、路径等通用运行支持 | 视觉算法、控制决策 |
| `bootstrap.py`、`cli.py` | 组件组装、命令行参数和程序启动 | 领域规则实现 |
| `scripts/` | 硬件探测、评估等独立工具 | 被应用主流程依赖的业务逻辑 |
| `configs/` | 默认及部署配置 | Python 模块 |
| `data/`、`logs/` | 运行期数据和日志 | 测试用例、源码 |
| `tests/` | 单元及集成测试 | 被生产代码导入的实现模块 |

代码和目录名建议统一采用 **snake_case**。现有中文文档是面向使用者的标题，可以保留；不建议为了命名风格重构而强制改名。当前测试文件数量较少，继续平铺在 `tests/` 即可，暂不需要增加 `unit/`、`integration/` 等层级。

## 3. 文件映射对照表

| 旧路径 | 新路径 | 备注 |
|---|---|---|
| `src/pantilt/core/types.py` | `src/pantilt/domain/types.py` | 领域类型归入领域层 |
| `src/pantilt/core/`（扣除已移出的 `types.py`） | `src/pantilt/infrastructure/` | 配置、路径、日志归入基础设施 |
| `src/pantilt/domain/controller.py` | 保持不变 | 已处于合适位置 |
| `src/pantilt/domain/state_machine.py` | 保持不变 | 已处于合适位置 |
| `src/pantilt/actuation/` | `src/pantilt/adapters/actuation/` | 执行设备适配器 |
| `src/pantilt/perception/` | `src/pantilt/adapters/perception/` | 感知设备与算法适配器 |
| `src/pantilt/runtime/` | `src/pantilt/adapters/runtime/` | 控制台等运行时适配器 |
| `src/pantilt/app.py` 中的应用流程 | `src/pantilt/application/tracker.py` | 保留应用生命周期与控制流程 |
| `src/pantilt/app.py` 中的 CLI 逻辑 | 新建 `src/pantilt/cli.py` | 拆出参数解析与退出逻辑 |
| `src/pantilt/app.py` 中的组件装配 | 新建 `src/pantilt/bootstrap.py` | 组合根负责创建具体组件 |
| `tests/test_state_machine.py::run_simulation_test` | `src/pantilt/application/simulation.py` | 生产入口不再导入 `tests` |
| `scripts/hw/`、`scripts/eval/` | 保持不变 | 现有分组清晰 |
| `configs/`、`assets/`、`data/`、`logs/` | 保持不变 | 保留为仓库级资源目录 |
| `tests/` | 保持不变 | 当前规模无需再分层 |

迁移时应同步更新包内的 `__init__.py` 导出，以及所有 `pantilt.core`、`pantilt.actuation`、`pantilt.perception`、`pantilt.runtime` 的导入路径。

## 4. 安全迁移脚本与步骤

下面的脚本只负责移动文件；它会检查将被移动的源码是否已有改动，并检查目标路径是否已存在。**导入路径和入口配置需要在移动后手动更新**，避免用宽泛的文本替换误改源码。

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# 如果将要移动的源码已有改动，先处理这些改动再执行迁移。
if ! git diff --quiet -- \
  src/pantilt/app.py \
  src/pantilt/core \
  src/pantilt/actuation \
  src/pantilt/perception \
  src/pantilt/runtime ||
   ! git diff --cached --quiet -- \
  src/pantilt/app.py \
  src/pantilt/core \
  src/pantilt/actuation \
  src/pantilt/perception \
  src/pantilt/runtime; then
  echo "待迁移源码存在未提交改动，请先提交或另行保存。" >&2
  exit 1
fi

# 避免覆盖已存在的目标文件或用户目录。
for target in \
  src/pantilt/domain/types.py \
  src/pantilt/infrastructure \
  src/pantilt/adapters \
  src/pantilt/application; do
  if [[ -e "$target" ]]; then
    echo "目标路径已存在，停止迁移：$target" >&2
    exit 1
  fi
done

mkdir -p \
  src/pantilt/application \
  src/pantilt/adapters \
  src/pantilt/domain

# 先移出领域类型，再整体移动 core。
git mv src/pantilt/core/types.py src/pantilt/domain/types.py
git mv src/pantilt/core src/pantilt/infrastructure

git mv src/pantilt/actuation src/pantilt/adapters/actuation
git mv src/pantilt/perception src/pantilt/adapters/perception
git mv src/pantilt/runtime src/pantilt/adapters/runtime
git mv src/pantilt/app.py src/pantilt/application/tracker.py
```

### 迁移后需同步修改

1. **导入路径**
   - `pantilt.core.types` → `pantilt.domain.types`
   - `pantilt.core.config`、`pantilt.core.paths`、`pantilt.core.logging_setup` → `pantilt.infrastructure.*`
   - `pantilt.actuation.*` → `pantilt.adapters.actuation.*`
   - `pantilt.perception.*` → `pantilt.adapters.perception.*`
   - `pantilt.runtime.*` → `pantilt.adapters.runtime.*`

2. **命令行入口**
   - `pyproject.toml` 中将 `pantilt = "pantilt.app:main"` 改为 `pantilt = "pantilt.cli:main"`。
   - `src/pantilt/__main__.py` 改为调用 `pantilt.cli.main`。
   - 在 `cli.py` 中解析参数；将组件创建委托给 `bootstrap.py`。
   - 将 `--simulate` 使用的 `run_simulation_test` 从测试文件提取到 `application/simulation.py`，然后更新 CLI 和测试的导入。

3. **包初始化文件**
   - 更新 `src/pantilt/__init__.py` 对应用类和领域类型的导出。
   - 检查移动后的 `infrastructure/__init__.py`、`adapters/*/__init__.py` 是否仍引用旧包路径。

4. **配置与路径**
   - `configs/default.yaml`、`data/`、`logs/`、`assets/` 可先保持原位；相应配置中的 `logs`、`assets/audio` 路径无需随 Python 包迁移而改名。
   - `paths.py` 搬到同级深度的 `infrastructure/` 后，`Path(__file__).resolve().parents[3]` 仍指向仓库根目录。
   - 但该路径策略依赖仓库布局：若未来通过 wheel 独立部署，应明确使用外部 `--config` 路径或环境变量；若要随 wheel 提供默认配置，则需将配置作为 package resource 并配置打包规则。

5. **文档与测试**
   - 更新 `README.md` 中引用旧源码路径的说明；`scripts/hw` 下的命令路径保持不变。
   - 运行 `pytest`、`python -m pantilt --simulate`、`python -m pantilt --help`，并验证 `pip install -e .` 后的 `pantilt` 命令。
   - Python 项目不涉及前端常见的 `@/` 路径别名；当前 `pyproject.toml` 的 `src` 包发现和 pytest 路径配置通常无需修改。

`git mv` 会将重命名作为 Git 可识别的移动暂存；Git 实际上是根据文件相似度识别历史，而不是保存独立的“重命名记录”。
