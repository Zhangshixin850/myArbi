# 实现边界

FastAPI 模块化单体，SQLite WAL 为唯一账本存储。React 经 REST 读取缓存，所有交易所访问只使用 REST GET。

`config.py` 加载服务器设置；`adapters.py` 负责协议与标准化；`service.py` 负责归属、游标事务和核对；`ledger.py` 用 Decimal 重放成交；`models.py` 定义账本、基线、快照、游标和审计；`main.py` 暴露认证后的 API。

创建流程在进程锁内检查账户基线，并在数据库事务内建立卡片与双腿独占索引。事件在分页完整结束后，与游标一起提交。派生收益可从保存的事件重算；归档不删除账本。

活跃 → 待核对 → 已归档。待核对也可能由错误触发，不代表已平仓。无成交卡片可取消，所有成交卡片必须通过数量核对后归档。任何接口都不会发单。

API `/api/v1`：

| 路径 | 用途 |
|---|---|
| GET /accounts | 配置账户及 execution_enabled=false |
| GET /markets?account=&product= | 可选 USDT 市场 |
| GET /cards | 卡片、核算汇总、风险及同步状态 |
| POST /cards | 两条 legs：account/product/symbol/direction |
| GET /cards/{id}/events?offset=&limit= | 分页成交及资金流水 |
| GET /cards/{id}/audit | 最近 200 条核对记录 |
| POST /cards/{id}/legs/{leg_id}/manual-position | Omni 手工仓位、最近记录修订、幂等与版本检查 |
| POST /cards/{id}/cancel | 同步后验证无流水，取消卡片 |

所有金额字符串编码，时间为 UTC 毫秒。界面显示北京时间。自动执行只保留 `ExecutionIntent` 类型和禁用控件，不注册发单路由。

后续接入顺序：Lighter、Robinhood、Ondo、Alpha、Entropy、Arcus。先逐个平台验证成交、资金费与账户仓位能力，再接入统一账本。Omni 已接入公开 v2 永续行情和手工仓位，手工记录标为 `manual`，公开资金费估算标为 `estimated`，不写入真实资金费账本。

## Omni 数据流

Leg 新增 `source`、`quote_asset` 和 `manual_revision`；Event 新增 `source`。0002 迁移将旧记录默认为 `exchange`、USDT，保留金额、基线、游标及审计。

手工接口字段：`request_id`（UUID）、`expected_revision`、`qty`、`average`、`close_price`、`fee`（默认十进制字符串零）、`confirm_closed`、`replace_last`。金额数量必须为有限非负十进制字符串。减仓要求正平仓价和不变的剩余均价；清仓还需确认。归档后不接受新变更，原请求的幂等重试仍可读取成功结果。

`manual_position` 事件保存录入及修订关系，通过重放推导累计开仓、价差盈亏和费用。最近记录修订保持原生效时间，原事件不删除。`estimated_funding` 保存结算节点和公开估算依据，重算时使用该节点有效手工数量；流水 API 返回修订后的估算金额。`estimated_funding_gap` 保存漏采区间。事件、估算游标和检查点同事务提交。

公共行情检查点保存在腿快照中，估算依据另存事件原始证据，不受风险快照 30 天清理影响。时间统一 UTC 毫秒。卡片增加 `estimated`、`estimated_net`、`estimated_total`、`estimated_annual`、`funding_complete`；腿增加手工版本、更新时间、确认状态和估算资金费。原 `net` 不包含估算资金费，前端对混合卡片使用估算字段，纯自动卡片保持原口径。
