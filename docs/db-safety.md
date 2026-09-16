# 数据库安全须知（含一次真实事故的记录与恢复方法）

> 本文记录一次**真实的数据库清空事故**及其恢复过程，目的是让后来者不再踩同一个坑。
> 适用项目：智能选座与导航一体化系统（`D:\MAX_xiangmu`）。

---

## 一、事故经过（2026-09-16）

排查「学校模式数据隔离覆盖范围」时，写了一个临时探测脚本，脚本里包含：

```python
with app.app_context():
    db.drop_all()      # ← 灾难在这一行
    db.create_all()
```

脚本**没有任何测试隔离**，因此 `drop_all()` **直接作用在 MySQL 真实库 `seat_navigation` 上**，
清空了 `buildings / floors / seats / users / sensor_devices / sensor_data` 等表。

### 为什么改 `SQLALCHEMY_DATABASE_URI` 没用

Flask-SQLAlchemy 3.x 在 `db.init_app(app)` 时（即 `app.py` 被 import 的瞬间）
**就已经按 MySQL 配置创建好了引擎**。之后再改 `app.config['SQLALCHEMY_DATABASE_URI']`
**完全不生效** —— `create_all()` / `drop_all()` 仍然打向 MySQL。

这正是 `tests/conftest.py` 里 `_use_inmemory_db()` 存在的原因：它必须
**显式重建引擎**才能真正切到内存 SQLite。

---

## 二、铁律（务必遵守）

1. **任何会写库的临时脚本，绝不能在真库上调用 `drop_all()`。**
2. 需要隔离时，走 `tests/conftest.py` 里 `_use_inmemory_db()` 的同一套做法（显式重建引擎）。
3. 一定要在真库上做实验时，**先备份**：

   ```bash
   python backup_db.py            # 备份到 backups/（已加入 .gitignore）
   python backup_db.py --list     # 查看已有备份
   ```

4. 生产/演示数据库请另行开启定时备份（本项目的 `backup_db.py` 可直接挂计划任务）。

---

## 三、恢复方法（本次靠它救回了数据）

本次能恢复，依赖三个 MySQL 配置同时满足：

```sql
log_bin            = ON      -- 打开了 binlog
binlog_format      = ROW      -- 行格式，记录的是行数据而非 SQL 文本
binlog_row_image   = FULL     -- 每次变更记录【完整】行镜像（关键！）
expire_logs_days   = 0        -- 日志不过期，历史都还在
```

### 关键点

**1. binlog 文件在 MySQL 数据目录里、权限受限读不到**
绕过办法：用 `mysqlbinlog` 的 `--read-from-remote-server`，**让服务端把 binlog 流式发过来**：

```bash
mysqlbinlog --read-from-remote-server \
  --host=127.0.0.1 --port=3306 --user=<user> --password=<pwd> \
  --base64-output=DECODE-ROWS -vv \
  --result-file=out.sql  <binlog文件名>
```

**2. 一定要用 `-vv`（双 verbose）**
`-v` 只显示**发生变化的列**；`-vv` 才输出**含未变化列的完整行镜像**。
恢复数据必须用 `-vv`。

**3. 定位删除点**

```sql
SHOW BINLOG EVENTS IN '<当前binlog名>';   -- 找 DROP TABLE 事件的 Pos
SHOW MASTER STATUS;                        -- 看当前 binlog 名
SHOW BINARY LOGS;                          -- 列出所有 binlog 及大小
```

**4. 重建思路**
因为 `binlog_row_image=FULL`，**每个 UPDATE 事件都含「改前 + 改后」的完整行**。
所以：**对每个主键，取它在整个 binlog 中「最后一次出现的行镜像」**，
即可还原事故前的数据状态。

行镜像的格式（可直接解析）：

```
### UPDATE `seat_navigation`.`seats`
### WHERE
###   @1=1 /* INT meta=0 nullable=0 is_null=0 */
###   @3='A-1' /* VARSTRING(200) ... */
### SET
###   @1=1
###   @3='A-1'
```

`@N` 即该表第 N 列（按事故前的表结构顺序）。

### 本次恢复结果

| 数据 | 是否恢复 | 说明 |
|------|---------|------|
| `seats`（14 个座位） | ✅ 精确恢复 | 含 floor_id / 编号 / 坐标 / 状态 / 红外值 |
| `users`（含管理员） | ✅ 精确恢复 | **含 `password_hash`，可用原密码登录** |
| `buildings` / `floors` | ⚠️ 重建 | 这两个表只被 INSERT、从未 UPDATE，binlog 里没有行镜像 |
| `sensor_devices` | 🔁 自动重建 | ESP32 上电后会按 MAC 自动注册 |
| `sensor_data`（历史） | ❌ 无法恢复 | 只有 UPDATE 无 INSERT，且价值低 |

> **教训总结**：`binlog_row_image=FULL` + `log_bin=ON` 是这次能救回数据的关键。
> 建议保持这两个配置不变。

---

## 四、日常备份

```bash
python backup_db.py                       # 备份
python backup_db.py --list                # 列出备份
python backup_db.py --restore <文件>       # 恢复（会二次确认）
```

* 备份存放在 `backups/`，**已加入 `.gitignore`**（含密码哈希等敏感信息，切勿提交）
* 脚本会自动在常见路径查找 `mysqldump`，也可用环境变量 `MYSQL_BIN` 指定
