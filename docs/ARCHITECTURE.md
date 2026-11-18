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
| POST /cards/{id}/cancel | 同步后验证无流水，取消卡片 |

所有金额字符串编码，时间为 UTC 毫秒。界面显示北京时间。自动执行只保留 `ExecutionIntent` 类型和禁用控件，不注册发单路由。

后续接入顺序：Lighter、Robinhood、Omni、Ondo、Alpha、Entropy、Arcus。先逐个平台验证成交、资金费与账户仓位能力，再接入统一账本。Omni 的手工成交及公开费率估算应新增明确的 `estimated` 来源，不写入真实资金费账本。
