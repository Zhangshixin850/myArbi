v1.0 
prompt:
1.创建时，永续所选方向必须空仓；现货记录原有余额，后续只核算增量。
2. 年化按累计开仓名义价值计算。
3.双腿平衡则按基础币数量比较，默认偏差超过 1% 提示风险。
4.将部署的方法写到readme文件中，不要修改prompt部分。修改完成后提交至github，标签为v1.0
5.将omni平台加入项目，公共信息使用公开api，我自己的仓位数量、开仓均价则手动输入卡片
使用方法：

# myArbi v1.0

跨平台资金费套利记账与仓位核对。Binance/Aster 从只读 API 自动归集成交及资金流水；Omni 从公开 API 刷新行情和费率，仓位由你手工填写。

**交易在平台手工执行。应用只记账和提示风险，不下单、不撤单、不划转、不自动减仓。**

## 支持范围与口径

- Binance 普通账户 USDT 现货多头、USDT 永续；Aster Pro API V3 USDT 永续。
- Omni 的同币种永续可与上述任一平台配对，方向相反。只接入公开 v2 永续市场，不接入 swap 或私有交易接口。
- 一个配置账户对应一个平台，同一账户同一合约最多一张活跃卡片。
- 成本使用移动加权法。双腿平衡按基础币数量比较，默认偏差超过 1% 告警。
- 年化以双腿累计开仓名义价值之和为分母，加仓增加分母，减仓不减少分母；从首笔记录计时，归档后固定至最后平仓记录。
- Omni 金额保留 USDC 原额；按 **1 USDC≈1 USDT** 近似汇总。含 Omni 的净利、总收益和年化标记为估算，与纯自动卡片的账本收益分开显示。

## Ubuntu + Docker + Tailscale 部署

需要 64 位 Ubuntu、Git、Docker Engine、Compose 插件和 Tailscale。Docker 内安装运行依赖，服务器无需另装 Python 或 Node.js。

### 1. 准备工具和代码

尚未安装 Docker 时，按 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)安装 Engine 与 Compose 插件。

```sh
sudo apt update
sudo apt install -y git
sudo docker --version
sudo docker compose version
git clone https://github.com/Zhangshixin850/myArbi.git
cd myArbi
test -e .env || cp .env.example .env
chmod 600 .env
nano .env
```

本次版本标签为 `v1.0`。发布后可执行 `git checkout v1.0` 固定版本；固定标签的 checkout 不使用 `git pull` 更新。

### 2. 配置 .env

| 配置 | 用途 |
|---|---|
| `APP_USER` | 面板用户名，默认 `admin` |
| `APP_PASSWORD` | 必须替换为你生成的长随机密码，不能保留模板示例 |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Binance 普通账户只读 API 凭据 |
| `ASTER_USER` / `ASTER_SIGNER` / `ASTER_PRIVATE_KEY` | Aster 主账户地址、Pro API V3 agent 地址、对应 agent 私钥 |
| `OMNI_ENABLED` | 默认 `true`，启用 Omni 公共行情和手工仓位，无需 API key |
| `POLL_SECONDS` / `STALE_SECONDS` | 同步等待间隔，默认 60 秒；数据过期阈值，默认 180 秒 |
| `SNAPSHOT_RETENTION_DAYS` | 风险快照保留天数，默认 30 |
| `IMBALANCE_RATIO` | 双腿数量偏差阈值，默认 `0.01` |
| `MAX_LEVERAGE` / `MAX_MARGIN_USAGE` | 账户杠杆和维持保证金/权益告警阈值，默认 `5`、`0.7` |
| `MIN_LIQUIDATION_DISTANCE` | 强平距离阈值，默认 `0.1` |
| `DATABASE_URL` | 本地开发的 SQLite 地址；Compose 固定使用数据卷内数据库 |

Omni 配对至少需要一个已配置的 Binance 或 Aster 平台。未配置自动平台时可以登录，但不能创建双腿卡片。

**Aster 只填写 agent 私钥，不能填写主钱包私钥。** 凭据仅放服务器 `.env`，不要提交 Git 或填到前端。Binance 使用平台允许的最小只读权限。

### 3. 启动并开放私有 HTTPS

按 [Tailscale 官方说明](https://tailscale.com/download/linux)安装并登录；其他访问设备加入同一 tailnet。

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 backend web
sudo tailscale serve --bg http://127.0.0.1:8080
sudo tailscale serve status
```

用 `tailscale serve status` 显示的 HTTPS 地址访问，并用 `APP_USER`、`APP_PASSWORD` 登录。后端首次启动自动执行 Alembic 迁移；SQLite 账本存于 `ledger` 命名卷。

当前 Compose 仅绑定 `127.0.0.1:8080`，由 Tailscale Serve 提供私有 HTTPS；无需公网域名或开放公网网页端口。不要启用 Funnel。当前配置不使用 `SITE_ADDRESS`，Caddy 在容器内提供 HTTP 和反向代理。

保持一个 backend 副本和一个 Uvicorn worker。页面每 10 秒读取后端，后台每轮同步完成后等待 `POLL_SECONDS` 再同步。

## 卡片如何使用

### 自动 API 双腿

1. 先创建同币种、跨平台、相反方向的卡片。对应永续方向保持空仓；现货记录原余额基线。
2. 创建成功后再手工交易。启用之后匹配合约方向的逐笔成交自动归入，包括部分成交后撤单的成交部分。
3. 加仓、部分减仓持续计入同一卡片。转账、其他同基础币交易、反转持仓可能触发数量核对异常。
4. 双腿都成交过、账本与账户对应数量均归零且无错误，连续两次同步核对后自动归档。

### 含 Omni 的双腿

1. 创建卡片时选择 Omni 永续与一个自动平台，同币种、相反方向。Omni 的空仓前提需要你自行核实。
2. 手工交易后，点击 Omni 腿的“更新仓位 / 修订”，填写**当前数量与开仓均价**。未录入显示“待录入”，不视为实际空仓。
3. 每次加仓后更新数量和加权均价；每次减仓填写剩余数量、保持原均价，并填写本次实际平仓均价。可填本次费用，默认零，均以 USDC 计。
4. 清仓时填写数量 `0`、实际平仓价，并勾选已核实实际仓位为零。自动腿连续两次核对归零后自动归档，审计注明 Omni 为手工确认。
5. 最近一次录入有误时，勾选“修订最近一次录入”。新修订替代该记录参与重算，原记录仍保留。已归档卡片不能任意改账。

手工记录按保存时间生效，本版没有历史补录。**每次加减仓都应及时录入**；两次录入之间若发生多轮交易，单靠最终数量和均价无法还原期间盈亏。

Omni 的标记价格、单期费率、日化费率、周期和下次结算时间从 [官方公开 v2 API](https://docs.variational.io/technical-documentation/api)获取。资金费按结算节点、手工数量及已保存的结算前行情估算；**不等于你的个人实际到账流水**。公开接口旧版的 `funding_rate` 是年化值，不能作为单期费率计算金额。

资金费估算仅覆盖开始录入之后且有有效采样的节点。断网、过期快照或漏采区间会显示缺失，暂停完整估算净利及年化，不用当前费率补造历史。仓位已结束时允许归档，但收益缺口会保留。Omni 账户杠杆、保证金、强平价和 ADL 不可获取，显示未知。

## 日常运行、升级和备份

```sh
sudo docker compose ps
sudo docker compose logs --tail=100 backend
# 修改 .env 后重新创建后端
sudo docker compose up -d --force-recreate backend
# 停止 / 启动，保留数据卷
sudo docker compose down
sudo docker compose up -d
```

**不要执行 `docker compose down -v`，它会删除账本数据卷。**

升级前先使用 SQLite backup API 备份，不能在运行中只复制 `.db` 而忽略 WAL。把下面日期替换为本次唯一文件名，目标文件必须尚不存在：

```sh
sudo docker compose exec backend python scripts/backup.py /app/data/arbi.db /app/backups/arbi-YYYYMMDD.db
sudo docker compose cp backend:/app/backups/arbi-YYYYMMDD.db ./arbi-YYYYMMDD.db
# 跟踪 main 的工作区更新
git pull --ff-only
sudo docker compose up -d --build
sudo docker compose logs --tail=100 backend
```

固定标签的工作区使用 `git fetch --tags` 后 `git checkout 新版本标签`，再构建启动。迁移只向前升级，不重建已有账本。备份应另存到服务器之外。恢复前停止 backend，使用新数据卷并检查完整性，详见 [运维说明](docs/OPERATIONS.md#备份和恢复)。

## 本地开发运行

需要 Python 3.10+（建议 3.12）、Node.js 22+ 和 npm。前后端分别在两个终端运行。只在回环地址使用开发 HTTP。

Linux/macOS 项目根目录：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
test -e .env || cp .env.example .env
# 编辑 .env，设置 APP_PASSWORD 和所需平台凭据
python -m alembic upgrade head
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Windows PowerShell 无需激活环境：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

另开终端：

```sh
cd frontend
npm ci
npm run dev
```

Windows 使用 `npm.cmd ci`、`npm.cmd run dev`。打开 `http://127.0.0.1:5173`，Vite 将 `/api` 转发至后端。健康检查为 `http://127.0.0.1:8000/healthz`。两个终端分别按 `Ctrl+C` 停止；本地账本默认 `data/arbi.db`。

## 验证与排错

```sh
python -m pytest -q
python -m pip check
# 使用临时 DATABASE_URL 验证迁移，避免操作真实账本
python -m alembic upgrade head
python -m alembic check
cd frontend
npm ci
npm run build
```

Windows 对应使用 `.venv/Scripts/python.exe` 和 `npm.cmd`。单独构建前端不会启动后端。

| 现象 | 处理 |
|---|---|
| 后端提示 Set APP_PASSWORD | 设置根目录 `.env` 的非空面板密码并重启 |
| 只有 Omni、创建按钮禁用 | 补齐至少一个 Binance 或 Aster 账户配置 |
| 手工提交提示刷新 | 其他页面已修改仓位；关闭编辑器、刷新后重开 |
| Omni 资金费有缺口 | 查看估算漏采流水；公开 API 无历史补账能力，不能将缺失当零 |
| 数量不符或费用待估值 | 对照平台成交及转账，不删除流水掩盖差异 |
| npm.ps1 被禁止执行 | 使用 `npm.cmd`，无需改变执行策略 |
| 复制来的 .venv 提示 No Python | 使用本机 Python 重新创建虚拟环境，不沿用其他机器的环境 |

详细变更、已知问题和验证限制见 [v1.0 复查报告](docs/REVIEW-v1.0.md)、[验证记录](docs/VALIDATION.md)和[架构与 API](docs/ARCHITECTURE.md)。真实账户对账、Docker 实机验证和浏览器视觉验证分别记录，不以模拟测试代替。
