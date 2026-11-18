# myArbi

跨平台资金费套利记账系统。通过 REST 每分钟同步成交、资金流水和账户仓位，以卡片展示双腿数量、收益及风险。

**首期只读，不会下单、撤单、划转或自动减仓。** 先创建卡片，再在交易所手工交易；取消了固定建仓时段，可持续加仓、部分减仓，双腿归零并完成核对后自动归档。

## 当前支持

- Binance 普通账户 USDT 现货多头 + Aster USDT 永续空头。
- Binance USDT 永续 + Aster USDT 永续，方向相反。
- 逐笔成交去重、移动加权成本、手续费估值、资金费补查、风险提示、历史流水和归档审计。
- 前端 React + TypeScript；后端 FastAPI；数据库 SQLite WAL；部署 Docker Compose + Caddy。

暂不支持组合/多资产保证金、币本位、Alpha、其他平台及自动交易。每个平台当前配置一个账户，同一账户同一合约最多归属一张活跃卡片。

## 安装方式一：Ubuntu + Docker Compose

推荐用于服务器。需要 64 位 Ubuntu、Git、Docker Engine 和 Docker Compose 插件。Docker 内安装前后端依赖，宿主机不需要另装 Python 或 Node.js。

### 1. 安装前置工具

如果尚未安装 Docker，按 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)完成安装；已有 Docker 的服务器无需重复安装。

```sh
sudo apt update
sudo apt install -y git
sudo docker --version
sudo docker compose version
```

以下命令使用 `sudo docker`；如果当前用户已有 Docker 权限，可以省略 `sudo`。

### 2. 下载项目

```sh
git clone https://github.com/Zhangshixin850/myArbi.git
cd myArbi
# 仅在 .env 不存在时创建，避免覆盖已有配置
test -e .env || cp .env.example .env
chmod 600 .env
nano .env
```

### 3. 配置 .env

| 配置项 | 用途 |
|---|---|
| `APP_USER` | 面板用户名，默认 admin |
| `APP_PASSWORD` | 面板密码；必须设置，并替换模板中的示例密码 |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Binance API 凭据 |
| `ASTER_USER` | Aster 主账户地址 |
| `ASTER_SIGNER` | Aster Pro API V3 agent 地址 |
| `ASTER_PRIVATE_KEY` | 对应 agent 私钥，**不是主钱包私钥** |
| `SITE_ADDRESS` | 公网访问域名，例如 arbi.example.com，不加 https:// |
| `POLL_SECONDS` | 交易所同步间隔，默认 60 秒 |
| `STALE_SECONDS` | 数据过期提示阈值，默认 180 秒 |
| `SNAPSHOT_RETENTION_DAYS` | 风险快照保留天数，默认 30 |
| `IMBALANCE_RATIO` | 双腿数量偏差告警比例，默认 0.01 |
| `MAX_LEVERAGE` | 账户杠杆告警阈值，默认 5 |
| `MAX_MARGIN_USAGE` | 维持保证金/权益告警阈值，默认 0.7 |
| `MIN_LIQUIDATION_DISTANCE` | 强平距离告警比例，默认 0.1 |
| `DATABASE_URL` | 本地模式的 SQLite 地址；Compose 固定使用容器数据卷 |

没有平台凭据时仍可登录查看空面板，无法创建完整策略。凭据只进入后端；不要提交真实 `.env`，也不要把 agent 私钥填入前端。

### 4. 启动服务

公网部署前，将域名解析到服务器并开放 TCP 80/443。Caddy 使用 `SITE_ADDRESS` 自动申请 HTTPS 证书。

```sh
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 backend web
```

浏览器打开 **https://你的域名**，使用 `APP_USER` 和 `APP_PASSWORD` 登录。首次启动会自动执行数据库迁移；数据存于 `ledger` 命名卷，重建容器不会清空账本。

默认 `SITE_ADDRESS=localhost` 使用本地证书，不适合公网访问。没有域名、只想在本机试运行时，使用下文的本地开发方式，通过 `http://127.0.0.1:5173` 访问。

### 5. 常用运行命令

```sh
# 查看状态和最近日志
sudo docker compose ps
sudo docker compose logs --tail=100 backend

# 修改 .env 后重新创建后端；修改 SITE_ADDRESS 后也重新创建 web
sudo docker compose up -d --force-recreate backend
sudo docker compose up -d --force-recreate web

# 更新代码并重新构建
git pull --ff-only
sudo docker compose up -d --build

# 停止服务，保留数据卷
sudo docker compose down

# 再次启动
sudo docker compose up -d
```

不要为日常停止服务添加 `down -v`，它会删除数据卷。后端只运行一个副本、一个 Uvicorn worker；前端每 10 秒查询后端缓存，不直接访问交易所。

## 安装方式二：本地开发运行

需要 **Python 3.10+、Node.js 22+、npm 和 Git**。建议 Python 3.12，与 Docker 环境一致。前后端分别在两个终端运行。

### Linux / macOS

终端一，在项目根目录：

```sh
git clone https://github.com/Zhangshixin850/myArbi.git
cd myArbi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
test -e .env || cp .env.example .env
# 编辑 .env，至少设置 APP_PASSWORD 并替换示例密码
nano .env
python -m alembic upgrade head
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

终端二，在项目根目录：

```sh
cd frontend
npm ci
npm run dev
```

### Windows PowerShell

先安装 Python 3.10+ 和 Node.js 22+。使用以下方式无需激活虚拟环境，也无需修改 PowerShell 执行策略：

```powershell
git clone https://github.com/Zhangshixin850/myArbi.git
cd myArbi
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
# 保存配置后：
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

另开终端，在项目根目录运行：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

如果没有 `py` 启动器，请使用已安装 Python 3 的完整路径创建虚拟环境。不要直接使用可能指向 Python 2 的系统 `python`。

### 访问与停止

- 浏览器打开 **http://127.0.0.1:5173**，使用 `.env` 中的面板账户登录。
- Vite 将 `/api` 请求代理到 `127.0.0.1:8000`。
- 后端健康检查：**http://127.0.0.1:8000/healthz**。
- 在前后端终端分别按 `Ctrl+C` 停止。
- 本地默认数据库为 `data/arbi.db`。修改 `.env` 后重启后端。
- 本地 HTTP 仅用于回环地址开发，服务器访问使用 HTTPS。

## 如何使用

1. 配置 Binance 与 Aster 凭据并启动服务。
2. 选择两个平台产品、共同币种和相反方向，创建卡片。对应永续方向必须空仓；现货保存原有余额基线。
3. 在交易所手工建仓。系统按成交时间归集启用卡片后的新成交，并持续核算加减仓、手续费和资金费。
4. 观察数量偏差、强平距离、ADL、账户杠杆和保证金占用率。风险功能仅提示，不自动干预仓位。
5. 手工平仓。双腿账本与账户数量归零，连续两次同步核对通过后自动归档；单腿归零不会结束卡片。
6. 在历史记录中查看成交、资金流水和审计。迟到资金费会在后续补查时修订净利。

**收益口径：** 已实现净利与浮盈分开显示；年化以双腿累计开仓名义价值之和为分母，减仓不缩减分母，不代表保证金收益率。详见[记账与运行说明](docs/OPERATIONS.md)。

## 测试与生产构建

在项目根目录、已安装依赖的 Python 环境中：

```sh
python -m pytest -q
python -m pip check
```

Windows 对应使用 `.\.venv\Scripts\python.exe -m pytest -q` 和 `-m pip check`。

```sh
cd frontend
npm ci
npm run build
```

Windows 使用 `npm.cmd`。生产静态文件生成到 `frontend/dist`；Docker 部署会自动完成构建并由 Caddy 提供页面。单独执行前端构建不会启动后端。

## 备份

使用 SQLite backup API 进行一致性备份，不要在运行中只复制数据库主文件：

```sh
# 把日期改为本次备份的唯一名称
sudo docker compose exec backend python scripts/backup.py /app/data/arbi.db /app/backups/arbi-YYYYMMDD.db
sudo docker compose cp backend:/app/backups/arbi-YYYYMMDD.db ./arbi-YYYYMMDD.db
```

本地环境可运行 `python scripts/backup.py data/arbi.db backups/arbi-YYYYMMDD.db`。目标文件必须尚不存在。恢复步骤见[运维文档](docs/OPERATIONS.md#备份和恢复)。

## 常见问题

| 现象 | 检查方法 |
|---|---|
| 后端提示 Set APP_PASSWORD | 确认根目录 .env 已设置非空 APP_PASSWORD，重启后端 |
| 面板登录失败 | 核对 APP_USER/APP_PASSWORD；模板密码应先替换 |
| 无平台账户或无法创建卡片 | 检查对应平台凭据是否完整，账户/合约是否已被其他卡片占用 |
| 平台认证错误 | 核对 API 权限、服务器时间，以及 Aster 是否使用 Pro API V3 agent |
| 后端提示 no such table | 本地执行 python -m alembic upgrade head |
| npm.ps1 被禁止执行 | 在 PowerShell 使用 npm.cmd，无需改变执行策略 |
| 公网 HTTPS 不可用 | 检查域名解析、SITE_ADDRESS、80/443 端口和 Caddy 日志 |
| 数量不符、费用待估值 | 查看卡片流水与平台记录；不要删除账本或强行归档 |

## 文档与验证状态

- [agent.md：后续维护规则](agent.md)，[AGENTS.md](AGENTS.md) 为自动化工具提供入口。
- [模块与 API](docs/ARCHITECTURE.md)。
- [运维、记账口径与恢复](docs/OPERATIONS.md)。
- [原始需求存档](docs/REQUIREMENTS.md)。
- [验证记录](docs/VALIDATION.md)。

目前 17 项模拟测试、TypeScript 检查、前端构建、数据库迁移与一致性备份检查通过。**尚未完成真实账户对账、Ubuntu Docker 实机启动和浏览器视觉验收**；不得将模拟验证视为实盘验证。

`.env`、数据与备份、依赖目录和构建产物不提交 Git；仓库保留 `.env.example`、锁定依赖和完整源代码。参考界面见 `exam.png`；原有 Lighter/Ondo 脚本仅作后续接入参考。
