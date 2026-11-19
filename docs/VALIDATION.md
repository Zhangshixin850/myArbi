# v1.0 验证（2026-11-19）

- Python 3.14.5 临时隔离环境：43 项 pytest 测试及 pip check 通过。
- Node.js 24.16.0：TypeScript 类型检查与 Vite 生产构建通过。
- Alembic 0001 → 0002 迁移保留旧成交金额、游标和审计，`alembic check` 无模型差异。
- SQLite backup API 备份及 `PRAGMA integrity_check` 成功。
- Linux x86_64/Python 3.12 锁定 wheel 依赖解析通过；已补齐 backport 的 Python 版本条件。
- 已实现 Omni 适配器实测官方公开 v2 行情成功；README prompt 区块保持原样。

测试覆盖原有账务/适配器/接口回归，以及 Omni 费率单位、缓存限流、手工加减仓/清仓/修订、幂等和版本冲突、非法金额、多空估算、零费率、漏采、周期变化、离线清仓、重启、归档、事务原子回滚与旧库升级。

验证限制：

- 未调用真实账户私有 API，未读取 Omni 个人账户；未执行交易、撤单或划转。公开 API 实测不等于个人账户对账。
- 当前机器无 Docker，尚未实际构建并启动 Ubuntu Compose 服务。
- 本会话无可调用浏览器控制工具，未完成截图、移动端布局和交互视觉验收。
- 默认 Vite 配置打包器受沙箱目录限制，构建使用 --configLoader runner；项目脚本未改变。
- 测试库存在 Starlette/httpx 兼容性弃用提示，不影响测试结果。

首次真实账户验收应比对自动腿成交、手续费、资金费及最终净利，并逐笔核对 Omni 手工记录。估算资金费始终独立标识。已知缺陷和修改建议见 [提交前复查报告](REVIEW-v1.0.md)。
