# PostgreSQL 迁移、备份与恢复手册

## 部署迁移

生产环境必须设置 PostgreSQL `DATABASE_URL`，并保持
`DATABASE_AUTO_MIGRATE=false`。每次发布先执行：

```powershell
python -m alembic upgrade head
python -m alembic current
```

应用启动时会校验 `alembic_version`。数据库版本落后、不可访问或配置成
SQLite 时，生产实例拒绝启动。

从旧版 SQLite 导入时，先对空 PostgreSQL 执行 Alembic，再运行一次性导入。
导入器只读取源库，并拒绝写入非空目标库：

```powershell
python -m backend.migrate_sqlite_to_postgres `
  --source-sqlite backend/data/plans.db `
  --target-url "$env:DATABASE_URL"
```

导入后先验证方案数量、审批状态和审计链，再切换 API 流量；源 SQLite 文件
保留为只读回滚证据，直到迁移验收和备份均完成。

## 备份策略

- 数据库平台开启连续归档和时间点恢复（PITR）。
- 每日至少一次逻辑备份，备份文件加密后写入独立账号控制的对象存储。
- PostgreSQL、审计签名密钥和密钥 ID 必须进入同一个灾难恢复清单；密钥不得写入数据库备份。
- 建议目标：RPO 不超过 5 分钟，RTO 不超过 30 分钟。是否达到目标必须通过恢复演练验证。

示例逻辑备份：

```powershell
pg_dump --format=custom --no-owner --no-privileges --file agent.dump "$env:DATABASE_URL"
```

## 隔离恢复演练

恢复必须指向新建的隔离数据库，不能覆盖当前生产库：

```powershell
createdb industrial_control_agent_restore
pg_restore --no-owner --no-privileges --dbname industrial_control_agent_restore agent.dump
$env:DATABASE_URL="postgresql+psycopg://user:password@host/industrial_control_agent_restore"
python -m alembic current
```

随后执行：

1. 启动只读验收实例，确认 `/ready` 的数据库、审计链和 Outbox 检查均为 `ok`。
2. 以管理员身份调用 `/audit/events`，确认 `chain_valid=true`。
3. 抽查方案、审批、导出记录和创建者归属。
4. 确认 Outbox worker 能继续投递未发布事件，接收端按 `X-Audit-Event-ID` 去重。
5. 记录实际 RPO、RTO、备份时间、恢复时间和验收人。

## 审计签名密钥轮换

`AUDIT_SIGNING_KEYS_JSON` 保存仍需验证的全部历史密钥，
`AUDIT_ACTIVE_KEY_ID` 指定新事件使用的密钥。例如：

```text
AUDIT_SIGNING_KEYS_JSON={"2026-q3":"<32-byte-or-longer-secret>","2026-q4":"<new-secret>"}
AUDIT_ACTIVE_KEY_ID=2026-q4
```

确认所有历史事件验证通过后才能停止使用旧密钥；只要历史审计仍在保留期内，
旧密钥就必须保留在密钥管理系统中。密钥值不得写入代码、日志或前端环境变量。

## Outbox 运行

审计 Outbox worker 与 API 使用相同数据库和签名密钥：

```powershell
python -m backend.outbox_worker
```

模型任务 worker 也必须连接同一个 PostgreSQL 与 Redis（如已配置全局配额）：

```bash
python -m backend.model_job_worker
```

worker 异常退出后，`running` 任务会在租约到期后由其他实例恢复；fencing token
会拒绝旧实例的迟到写入。恢复演练应覆盖 worker 在模型调用中被终止、租约到期后
重新领取、最终只产生一个方案版本，以及取消任务不产生方案。

接收端必须使用事件 ID 实现幂等写入。投递失败会指数退避，锁超时后可由其他
worker 接管；`/ready` 在未发布事件超过 `AUDIT_OUTBOX_MAX_PENDING` 时返回
`not_ready`，worker 心跳超过 `AUDIT_WORKER_MAX_STALENESS_SECONDS` 也会使
readiness 失败。已成功投递的 Outbox 运行记录和已完成幂等记录默认保留
7 天，正式审计事件不会被 worker 清理。
