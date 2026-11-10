# G5.1 本地备份恢复与日常运行验收

日常入口已接入真实 SIP 流程。实际 XNYS 时间在收盘后 20 分钟至下一开盘前时，依次更新 SIP 和公司行为、冻结观察、生成或复用日报、刷新分类台账。失败保留非零退出码及阶段清单，后续步骤保持 NOT_RUN。

## 实际备份与恢复

- 备份 `afd08316-3075-4fb7-9a8e-31cb492ce8f8` 包含 **1,506 个文件，约 666 MiB**。范围包括项目运行源码与配置、真实来源库及回执、分类台账、冻结记录、策略登记和受管研究运行。
- 恢复写入新目录 `outputs/ops_restore/8822eda1-2e11-4a87-8249-fb9ae4a1fda5/`。每个文件核对 SHA256 和字节数，再验证 14 类台账、349 份来源回执、49,520 条 SIP 原价、40,240 条 Yahoo 探索行情、日报与原冻结哈希和 1 个已冻结策略的因子依赖。
- 使用恢复目录的源码与数据启动独立回环服务，沿用本机已安装的 Python 环境。真实日报、观察归档、分类台账及策略四个接口通过。恢复目录没有 `.env`。
- 归档采用白名单，排除本机凭证、虚拟环境、浏览器缓存、数据库活动日志和未验收模拟账户。旧风格监控的绝对路径快捷指针没有归档，原始报告仍在。可在恢复目录重跑 `style-report` 刷新指针。
- 工作台正式报告列表与下载接口隔离备份及恢复目录。恢复服务以自己的目录为工作根，能够独立使用其中的正式报告。
- 实测正式工作台对两份归档副本返回 HTTP 404，原日报返回 HTTP 200。重新扫描归档 1,506 个文件，哈希均一致，未命中本机 Alpaca 凭证值。

## 实际故障与重试

演练使用归档的美东 2026-11-06 真实缓存，均在实际允许窗口内，通过 PowerShell 日常入口的离线选项运行。测试把一条 SIP 请求索引暂时移到恢复目录内的旁路文件，结束后放回原位并核验哈希。

| 操作 | 实际结果 |
|---|---|
| 缓存索引缺失 | 退出 4。日更报告为 PARTIAL_BLOCKED，冻结与日报均未执行 |
| 放回原索引并重跑 | 退出 0。行情与事件增量写入均为 0，复用同一冻结和日报 |
| 同日再次运行 | 退出 0。观察记录与日报仍未重复，独立尝试日志保留 |
| 从恢复副本重算归档日报 | SIP 摘要、French 观察、冻结哈希及候选状态与原报告一致 |

原工作区的 SIP 数据库、冻结库和台账指针在演练前后哈希一致。证据在 `outputs/ops_acceptance/scheduler-recovery.json`、`restore-http.json` 与三次 PowerShell 日志。

全套回归 **117 通过、1 跳过**，耗时 191.84 秒。跳过项为 Yahoo SPY 的 2026-11-06 缓存缺 OHLCV。最终归档隔离改动后的专项回归 **21 通过**，与全套重叠。JUnit 记录为 `outputs/ops_acceptance/tests.xml` 和 `final-focused-tests.xml`。

## 运行命令

```powershell
# 在项目根目录手动运行。在线更新使用本机 .env。
.\scripts\run_daily.ps1

# 使用完全匹配的现有真实缓存，无缓存则保留退出 4。
.\scripts\run_daily.ps1 -Offline

# 数据维护和后台研究完成后，先刷新台账，再备份。
.\.venv\Scripts\python.exe -m quant_research.cli data-catalog
.\.venv\Scripts\python.exe -m quant_research.cli ops-backup
.\.venv\Scripts\python.exe -m quant_research.cli ops-restore --backup-id afd08316-3075-4fb7-9a8e-31cb492ce8f8

.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/ops_acceptance/tests.xml
```

实际备份路径由命令返回，位于 `outputs/ops_backups/<backup_id>/`。只有含完整 manifest 的备份可用于恢复。恢复每次都写入新目录，验证通过才生成 `restore_verification.json`。恢复并不覆盖运行中的工作区。当前副本仍在本机同一磁盘。

日常执行结果在 `outputs/daily_ops/<run_id>/manifest.json`。发生阻断时先看该次阶段和关联的维护输出，再在允许窗口内重跑。并行调用遇到锁会退出 4。异常终止若留下锁，应先检查对应进程和后台任务状态。

## 文件及验收范围

- `src/quant_research/workflow/ops_backup.py` 与 `workflow/daily_ops.py` 实现归档、恢复和日常编排。
- `src/quant_research/cli.py`、`web.py` 接入命令和归档隔离。
- `scripts/run_daily.ps1`、`scripts/task_scheduler.example.ps1`、`scripts/cron.example` 更新操作入口及调度示例。
- `tests/test_ops_backup.py`、`tests/test_daily_ops.py`、`tests/test_g4.py` 验证白名单、活跃锁、路径拒绝、开盘窗口及报告隔离。

Windows 已实际运行脚本和恢复启动。后续的强制终止演练见 `docs/G5_crash_recovery_acceptance.md`。操作系统的实际定时触发和 Linux 执行仍待单独验收。本机 WSL 查询未提供可运行的 Linux 环境。当前只有 1 个前向观察日，最终策略测试仍封存。
