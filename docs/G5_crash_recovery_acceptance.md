# G5.2 进程强制中止与恢复

日常编排和数据维护使用两把由操作系统持有的锁。锁的持有状态由操作系统判断。锁旁的标记保存运行 ID、PID 与本次持有者标识，用于核对日志。进程退出后，操作系统释放锁，下一次实际运行才检查并接管遗留标记。存在活动持有者、旧格式或未知标记时拒绝接管。

恢复将上次仍在运行的阶段记为 INTERRUPTED。已完成的阶段和已写入的交易日记录按原样保留。新运行重放日常维护，核验并复用已提交的冻结。只有确切缺少日报时才生成报告。读取报告遇到哈希错误时仍阻断。

## 实际演练

Windows 使用经核验的恢复目录 `outputs/ops_restore/a73afe53-bff9-453b-87d8-c1192af0d84d`，加载当前工作区代码。两次均在美东 2026-11-06 收盘后至下一开盘的实际窗口内运行，只读取真实离线缓存。测试脚本只暂停本次启动并核对过身份的子进程，再由操作系统终止。锁接管及日志更新均由正式命令执行。

| 中止位置 | 实际核验 |
|---|---|
| 维护阶段，100 条真实行情的写入方法返回后 | 当时公司行为步骤尚未开始。并行日更与维护各返回 4。终止后正式入口接管两把锁，维护及日更旧记录为 INTERRUPTED。重跑和重复运行均退出 0，行情和公司行为版本新增均为 0，复用旧冻结及日报 |
| 冻结已提交，日报生成前 | 隔离副本的旧冻结与日报先转存到同副本的隔离目录，以真实缓存重新冻结当期 20 条行情。终止时该日尚无新报告。重跑复用同一冻结哈希并生成一份日报。再跑复用同一报告 |

演练前后比对了原工作区的 SIP 行情库、冻结库与台账指针哈希。恢复用的隔离副本记录和原工作区分开。第二次演练不计入原工作区的前向观察天数。

两次强制终止的实际 Windows 退出码均为 15。维护场景的日更重跑 ID 为 `1a8d3f75-6ab0-4c1e-a473-b3b8d473d6e9`，冻结后场景的重跑 ID 为 `dcb6b45f-851e-49eb-8d54-ea82df312bae`。后者生成日报 `1517c2e0-fcd9-496f-9fc0-42c96a7a0140`，同日重复运行读取同一报告。

恢复后的独立只读对账显示，原工作区与演练副本均为 99,040 条行情版本、49,520 个证券交易日、99,040 条抓取观察版本和 1,042 条公司行为版本。重算日报引用的冻结记录通过原文及回执核验。对账见 `outputs/crash_recovery/data-reconciliation.json`。

## 复现

```powershell
# 先恢复到新的隔离目录，使用命令实际返回的目录替换参数。
.\.venv\Scripts\python.exe -m quant_research.cli ops-restore --backup-id afd08316-3075-4fb7-9a8e-31cb492ce8f8
.\.venv\Scripts\python.exe scripts/drill_crash_recovery.py --restore-root <新恢复目录> --evidence-dir outputs/crash_recovery/<新证据目录名>

# 实际日常运行。离线重放需有当期真实缓存。
.\scripts\run_daily.ps1 -Offline
.\.venv\Scripts\python.exe -m pytest -q -rs --junitxml=outputs/crash_recovery/tests.xml
```

演练需要当前仍处于允许窗口，以及恢复副本包含该日真实缓存、原始冻结和日报。原 2026-11-06 副本过了窗口后只可查看已记录证据。实验日志和两次状态转移见 `outputs/crash_recovery/windows-drill/machine_evidence.json`。

稳定的 `.guard` 文件是操作系统锁的载体，其存在不代表当前有活动持有者。日常入口可恢复本版本的遗留标记。旧格式、手工文件或损坏标记需要人工确认，正常操作无需删除锁文件。

## 文件与验收范围

Windows 全套回归 **123 通过、1 跳过**，耗时 264.02 秒。跳过项为 Yahoo SPY 的 2026-11-06 缓存缺 OHLCV。锁与维护专项 **17 通过**，与全套重叠。首轮发现沙箱拒绝 Windows 硬链接，改用同目录排他重命名后通过。实际测试记录在 `outputs/crash_recovery/tests.xml` 和 `final-focused-tests.xml`。

- `src/quant_research/workflow/operation_lock.py`、`daily_ops.py`、`maintenance.py`、`ops_backup.py` 共用进程锁，维护保留可识别的阶段进度。
- `scripts/drill_crash_recovery.py` 仅用于隔离恢复副本的演练。`tests/test_operation_lock.py` 覆盖争锁、进程退出、日志接管和旧格式锁。

本轮覆盖 Windows 强制终止的两个指定阶段。数据库事务尚未提交时的故障、操作系统实际定时触发和 Linux 运行仍待验收。严格历史模型和模拟成交的准入未改变。
