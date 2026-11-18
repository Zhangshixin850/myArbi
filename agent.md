# myArbi 维护指南

## 项目目标

为跨平台资金费套利提供只读记账、仓位核对和风险提示。当前支持 Binance USDT 现货/永续与 Aster Pro API V3 USDT 永续；不下单、不撤单、不划转，不自动减仓。

先阅读 `README.MD`、`docs/ARCHITECTURE.md` 和 `docs/OPERATIONS.md`。`docs/REQUIREMENTS.md` 是需求存档，不代表功能均已实现。修改前检查工作区差异并保留用户已有改动。

## 模块位置

| 路径 | 职责 |
|---|---|
| backend/config.py | .env 配置与风险阈值 |
| backend/adapters.py | REST GET、签名、分页、限流和数据标准化 |
| backend/ledger.py | Decimal 成本、已实现盈亏、手续费、资金费和年化 |
| backend/service.py | 卡片归属、同步游标、幂等入账、核对和归档 |
| backend/models.py、backend/db.py | SQLite WAL 模型与连接 |
| backend/main.py | FastAPI、HTTP Basic 认证和接口类型 |
| frontend/src/ | React/TypeScript 卡片面板 |
| migrations/ | Alembic 迁移；已发布迁移不应重写 |
| tests/ | 账务、适配器和服务/API 回归测试 |
| scripts/backup.py | SQLite 一致性备份 |

代码保持扁平、清晰，注释解释必要的业务规则；不要引入无必要的服务层、仓储层或微型包装函数。首期使用单进程异步任务，不引入 Redis/Celery。

## 必须保持的账务规则

- 使用逐笔成交记账；订单部分成交后撤单也必须入账。只有卡片启用后的匹配成交归属该卡片。
- 永续对应方向从空仓开始；现货只归属启用后的增量，保存原余额基线。
- 无 30 分钟建仓期或独立持仓阶段；持续加仓、部分减仓均归入同一卡片。
- 同账户同合约首期最多一张活跃卡片，防止资金费方向无法拆分；归属冲突由数据库约束及创建事务共同保护。
- 金额、数量使用 Decimal；数据库与 API 保留十进制字符串。时间为 UTC 毫秒，界面使用北京时间。
- 原始事件唯一键去重，分页完整后将事件与游标在同一事务中提交；失败不得推进游标。
- 成本采用移动加权法；现货基础币手续费影响可平数量，但不得重复计费。
- 不得把收入接口的 REALIZED_PNL/COMMISSION 再次加入已经由成交计算的净利。Aster 佣金用对应现金流水核对符号。
- 收益分开显示已实现净利与浮盈；返佣/清算费用不要显示成资金费。缺失估值和无法归属的流水必须明确暴露。
- 年化分母为双腿累计开仓名义价值之和，减仓不减少分母。不是保证金收益率。
- 已有双腿成交、账本与账户数量均归零且无错误，连续两次同步确认后才能归档；单腿平仓不归档。
- 归档后迟到资金费可以修订收益，必须保留审计。不可用风险指标显示未知，不冒充零风险。

## 配置与运行约束

- 真实凭据只放服务器 `.env`；不要输出到日志、异常、前端、测试样本或 Git。Aster 使用 agent 私钥，不使用主钱包私钥。
- 不提交 `.env`、数据库/WAL/SHM、备份、虚拟环境、node_modules、构建产物或日志。`.env.example` 只包含空值和示例。
- 后端只允许只读平台请求。将来实现自动交易须作为独立功能，不能借维护记账功能悄悄启用。
- 保持单个 backend 副本和单个 Uvicorn worker，避免重复同步。首期前后端均使用 REST 轮询。
- 修改模型时新增 Alembic 迁移；先在临时数据库验证迁移，不能直接重建用户账本。
- 备份使用 SQLite backup API；恢复需停止后端并避免旧 WAL/SHM 污染。
- 本地原有 lighter_exchange.py、ondo_exchange.py 仅作后续平台参考，不属于已接入平台。

## 验证与交付

安装锁定依赖：`python -m pip install -r requirements.lock`；前端使用 `npm ci`。

```sh
python -m pytest -q
python -m pip check
# 使用临时 DATABASE_URL，避免更改真实账本
python -m alembic upgrade head
python -m alembic check
cd frontend
npm run build
```

Windows 无需激活环境：使用 `.venv/Scripts/python.exe` 和 `npm.cmd`。不要调用可能指向 Python 2 的系统默认 `python`。

账务修改需覆盖重复/乱序成交、分页边界、部分平仓、基础币费用、缺失估值、重启恢复、归档与迟到流水；适配器修改需核对官方文档和签名/分页测试。不要用测试或演示触发真实交易。

变更用户流程、配置或接口时同步更新 README 及相关文档。交付说明区分已通过的模拟测试、真实账户验证、Docker 验证和浏览器视觉验证，未完成项如实说明。
