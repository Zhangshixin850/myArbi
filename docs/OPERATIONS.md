# myArbi v1.0 使用与部署

这是只读记账应用。请先创建卡片，再在交易所手工交易；应用没有发单、撤单、划转或自动减仓功能。原 README 的需求说明保留不变。

## 支持范围

- Binance 普通账户 USDT 现货多头与 Aster USDT 永续空头。
- Binance USDT 永续与 Aster USDT 永续的反向双腿。
- 一个平台一个配置账户；支持读取单向或双向持仓模式，不修改账户模式。
- 支持 Omni 公开永续行情与手工仓位，可与 Binance/Aster 配对。Omni 使用 USDC，按 1:1 近似汇总并明确标为估算。
- 不支持统一/组合保证金、多资产保证金、币本位、Alpha、Omni swap 和其他平台。原有 Lighter/Ondo 文件保留作后续适配参考，未导入运行服务。
- 为避免无方向资金费被误分配，同一账户同一合约首版最多归属一张活跃卡片，即使是不同方向。扩展多账户时可通过独立账户隔离。

## Ubuntu 启动

完整安装与运行命令见根目录 README 的“Ubuntu + Docker + Tailscale 部署”。当前 Compose 将网页 HTTP 绑定在 `127.0.0.1:8080`，用 Tailscale Serve 提供 tailnet 内 HTTPS；不使用 `SITE_ADDRESS` 或公网 Caddy 证书配置。

```sh
test -e .env || cp .env.example .env
chmod 600 .env
# 配置 APP_PASSWORD 和所需平台凭据
docker compose up -d --build
sudo tailscale serve --bg http://127.0.0.1:8080
sudo tailscale serve status
```

Binance 使用 API key/secret。Aster 使用 **Pro API V3 agent** 的 user（主账户地址）、signer（agent 地址）和 agent private key；不要填写主钱包私钥。账户须满足 Aster 对该接口的使用条件。密钥只从后端环境读取，不写入数据库、前端或日志。应用只发送 GET 请求，但仍应在平台侧使用允许的最小权限。

`.env` 修改后执行 `docker compose up -d --force-recreate backend`。默认每 60 秒同步；前端每 10 秒读取后端缓存。只运行一个 backend 副本和一个 Uvicorn worker，避免重复调度。

前端用 `APP_USER`、`APP_PASSWORD` 登录；凭据仅驻留页面内存，刷新后需重新登录。生产环境必须使用 HTTPS。

## 本地开发

Python 3.10+、Node.js 22+。

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
cp .env.example .env
# 配置 APP_PASSWORD
alembic upgrade head
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

另开终端：

```sh
cd frontend
npm ci
npm run dev
```

Windows 可使用 `.venv/Scripts/python.exe -m ...` 与 `npm.cmd`。不配置交易所凭据也可运行登录页和空面板；Omni 无需凭据，但必须有另一个已配置平台才能创建双腿卡片。

```sh
python -m pytest -q
cd frontend
npm run build
```

## 操作流程及口径

1. 选择两个平台产品、共同币种和方向。创建时同步市场和账户；永续方向需空仓，现货记录已有余额。
2. 创建成功后再手动交易。成交时间在卡片启用后、属于所选合约方向的逐笔成交自动归入。部分成交后撤单仍会计账。
3. 可持续加仓和部分减仓，成本采用移动加权法。无需“进入持仓阶段”或点击开始平仓。
4. 双腿账本数量与账户数量均归零且无核对错误，连续两次同步确认后自动归档。零成交卡片需主动取消；取消前会重新同步。
5. 现货余额转入/转出、基础币其他交易、改变持仓模式或反转仓位会造成核对异常；先到交易所核对，不要通过删除流水掩盖差异。

现货手续费扣基础币时减少归属数量，手续费仍独立计入费用，避免重复计费。第三币种手续费按成交所在分钟 K 线收盘价估值，保留原金额；这是估值而非精确成交汇率。无法获取行情时显示待估值，年化暂停。

已实现净利 = 平仓价差盈亏 + 资金费及明确归属的返佣/清算费用 − 成交手续费。收入接口的 REALIZED_PNL/COMMISSION 仅作原始核对证据，不重复加到净利。未平仓的浮盈另列。

年化是 `已实现净利 / 双腿累计开仓名义价值 × 365天 / 运行时长`，不是保证金回报率。加仓累计增加分母，减仓不缩减；从首笔成交计时，到最后平仓成交结束。短周期年化可能很大，不作预测。

数量以基础币计，不按 USDT 名义价值配平。费率保留平台原始值；周期由最近两次公开结算间隔推算，可能滞后于平台未来调整。日化费率仅作比较。

风险展示：平台强平价格距离、ADL 分位（不可用时为 —）、每个账户总名义仓位/权益、维持保证金/保证金权益。后者是统一占用率，不冒充所有平台定义的 MMR。60 秒轮询无法提供实时强平保护。风险仅在面板及日志中提示，无站外消息推送。

## 同步、异常与保留

- 每笔原始事件由账户、产品、合约、事件类型、原始 ID 唯一去重；原始响应不包含签名或请求头。
- 常规成交重叠回查 5 分钟，资金流水回查 1 天；每天回查最多最近 90 天。平台可查询范围变化时需调整适配器。
- 断网、认证错误或限流暂停该账户 5 分钟，其他账户继续。中途分页失败不推进游标。超过 90 天未同步则标记不完整，需要人工核对。
- 归档后继续每天回查，持续到平仓后 90 天；收到迟到流水会修订收益并记录审计。更久的补账目前需要后续导入工具，不能认为平台历史永久可查。
- 同毫秒历史满 1000 条且无法细分时明确报错，不丢弃记录。不适合高频交易账户。
- REST 无法保证两腿快照同一瞬间采样；交易进行时暂时数量不符会进入待核对，下一次完整同步重新确认。
- 当前无任意改账、历史成交导入或手工强制归档入口；异常保留原始证据。账本和审计永久保存，风险快照默认保留 30 天，可通过 SNAPSHOT_RETENTION_DAYS 调整。

## 备份和恢复

使用 SQLite backup API，不能在运行中只复制主 `.db` 而忽略 WAL。

```sh
docker compose exec backend python scripts/backup.py /app/data/arbi.db /app/backups/arbi-20261118.db
docker compose cp backend:/app/backups/arbi-20261118.db ./arbi-20261118.db
```

文件名必须是尚不存在的新路径。可在服务器 cron 每天调用上述命令并使用当天日期生成文件名；备份应复制到另一台机器。

恢复时停止 backend，保留当前卷作回滚副本，将已验证备份恢复到**新的数据卷**的 `arbi.db`，文件属主设为 UID 10001，然后让 Compose 指向该卷并启动。不要将备份直接覆盖带有旧 WAL/SHM 的运行中数据库。启动前通过 SQLite `PRAGMA integrity_check` 检查，启动时自动执行 Alembic 迁移。

## 官方接口参考

- [Binance USDⓈ-M 接口](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- [Binance Spot REST](https://developers.binance.com/docs/binance-spot-api-docs/rest-api)
- [Aster V3 文档](https://github.com/asterdex/api-docs/blob/master/V3%28Recommended%29/EN/aster-finance-futures-api-v3.md)

Aster 与 Binance 认证独立实现。接入真实账户后应先核对一组小额、手动执行的开平仓及资金费流水；模拟测试通过不代表已完成真实账户对账。

## Omni 手工仓位与估算

`OMNI_ENABLED=true` 默认启用。公共数据只访问官方 `GET /metadata/v2/stats`，过滤永续市场，每轮共用响应，不调用个人账户或交易接口。单期费率用于估算；年化费率保持原单位；结算时间从 Unix 秒转换为 UTC 毫秒。

手工录入按保存时间生效。加仓录入当前数量和加权均价；减仓保持旧均价并录入实际平仓价；清仓填写零并确认实际仓位归零。每次变更都应及时记录，不能用间隔快照还原期间多轮交易。费用按 USDC 手工输入，默认零。请求带幂等标识和预期版本；最近记录可追加修订，原记录与审计不删除。

每个已知结算节点，使用过期阈值内的结算前公开标记价格和单期费率，以及该节点有效的手工数量估算收付。正费率下多头为负、空头为正。资金费估算单独保存，永远不写成真实收入。断网跨期、周期变化和缺失费率会保留不可恢复缺口，不按当前费率补账。

卡片金额保留 USDC 原币，按 `1 USDC≈1 USDT` 近似汇总，另列估算净利、含浮盈估算总计和估算年化；缺口或账户核对错误导致完整收益未知。归档确认的是仓位结束：Omni 由用户手动确认，自动腿仍需连续两次核对。估算缺口不阻塞仓位结束，归档后继续显示收益不完整。Omni 归档后不继续抓公共行情；自动腿保留原有迟到流水回查。

Omni 账户杠杆、保证金、强平价与 ADL 无公开个人数据来源，显示未知。手工仓位的录入延迟和公开费率预测误差会影响估算。v1.0 没有个人 CSV 导入、历史补录或 Omni 私有 API。
