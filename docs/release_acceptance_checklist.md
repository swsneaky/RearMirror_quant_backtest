# 发布验收清单 (release_acceptance_checklist.md)

## 1. 代码完整性

| 检查项 | 命令 | 预期结果 | 状态 |
|--------|------|----------|------|
| Python 语法检查 | `python -m py_compile src/*.py` | 无错误 | ⬜ |
| 导入测试 | `python -c "import pipeline, src"` | 无错误 | ⬜ |
| 单元测试 | `pytest tests/ -q` | 102 passed | ⬜ |
| 前端构建 | `cd frontend && npm run build` | 成功 | ⬜ |
| 三大文件校验 | `python tools/validate_three_files.py` | OK | ⬜ |

---

## 2. 数据完整性

| 检查项 | SQL/命令 | 预期结果 | 状态 |
|--------|----------|----------|------|
| daily_bar 存在 | `SELECT COUNT(*) FROM daily_bar` | > 4,000,000 | ⬜ |
| cum_factor 非空 | `SELECT ... WHERE cum_factor IS NULL` | < 1% | ⬜ |
| feature_wide 存在 | `SELECT COUNT(*) FROM feature_wide` | > 3,900,000 | ⬜ |
| label_wide 存在 | `SELECT COUNT(*) FROM label_wide` | > 3,900,000 | ⬜ |
| 日期同步 | `feature_max == daily_max` | True | ⬜ |
| 标签滞后 | `label_max <= daily_max - 5` | True | ⬜ |

---

## 3. 功能验证

| 检查项 | 测试方法 | 预期结果 | 状态 |
|--------|----------|----------|------|
| API 启动 | `uvicorn api.main:app` | 服务启动 | ⬜ |
| Dashboard API | `GET /api/dashboard/summary` | 200 OK | ⬜ |
| Stocks API | `GET /api/stocks` | 200 OK | ⬜ |
| Backtest API | `GET /api/backtest/results` | 200 OK | ⬜ |
| Factors API | `GET /api/factors/summary` | 200 OK | ⬜ |
| 前端首页 | 访问 `/` | 页面渲染 | ⬜ |

---

## 4. 幂等性验证

| 检查项 | 测试方法 | 预期结果 | 状态 |
|--------|----------|----------|------|
| run_label_pipeline | 执行两次 | 第二次 status=skipped | ⬜ |
| run_daily_update | 执行两次 | 无数据变化 | ⬜ |
| 数据行数不变 | 执行前后 COUNT(*) | 一致 | ⬜ |

---

## 5. 文档完整性

| 文档 | 路径 | 状态 |
|------|------|------|
| README.md | 项目根目录 | ⬜ |
| 部署指南 | docs/bootstrap_from_scratch.md | ⬜ |
| 训练指南 | docs/first_train_guide.md | ⬜ |
| 发布清单 | docs/release_manifest.md | ⬜ |
| 灾难恢复 | docs/disaster_recovery.md | ⬜ |
| 可复现性报告 | docs/reproducibility_report.md | ⬜ |
| 验收清单 | docs/release_acceptance_checklist.md | ⬜ |

---

## 6. 发布包验证

| 检查项 | 命令 | 预期结果 | 状态 |
|--------|------|----------|------|
| 发布包存在 | `ls RearMirror-v*.zip` | 文件存在 | ⬜ |
| 包大小合理 | `du -h RearMirror-v*.zip` | < 10 MB | ⬜ |
| 解压测试 | `unzip -t RearMirror-v*.zip` | 无错误 | ⬜ |

---

## 7. 安全检查

| 检查项 | 命令 | 预期结果 | 状态 |
|--------|------|----------|------|
| 无敏感信息 | `grep -r "password\|secret\|api_key"` | 无匹配 | ⬜ |
| 无 .env 文件 | `ls .env*` | 不存在 | ⬜ |
| 无数据库密码 | 检查配置 | SQLite 无密码 | ⬜ |

---

## 8. 性能基准

| 检查项 | 测试方法 | 预期结果 | 状态 |
|--------|----------|----------|------|
| API 响应时间 | `curl -w "%{time_total}"` | < 1s | ⬜ |
| 数据库查询 | `EXPLAIN QUERY PLAN` | 使用索引 | ⬜ |
| 前端加载 | 浏览器 DevTools | < 3s | ⬜ |

---

## 9. 验收签名

| 角色 | 姓名 | 日期 | 签名 |
|------|------|------|------|
| 开发者 | | | |
| 测试者 | | | |
| 发布者 | | | |

---

## 10. 验收结论

- [ ] 所有关键检查项通过
- [ ] 无阻塞问题
- [ ] 文档完整
- [ ] 可以发布

**验收结果**: ________________

**验收日期**: ________________

---

## 附录: 快速验证脚本

```bash
#!/bin/bash
# quick_verify.sh

echo "=== 1. 测试 ==="
pytest tests/ -q --ignore=tests/test_v2_asset.py

echo "=== 2. 前端构建 ==="
cd frontend && npm run build && cd ..

echo "=== 3. 数据状态 ==="
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
for t in ['daily_bar', 'feature_wide', 'label_wide']:
    r = con.execute(f'SELECT MAX(date), COUNT(*) FROM {t}').fetchone()
    print(f'{t}: {r[0]}, {r[1]:,} rows')
"

echo "=== 4. API 测试 ==="
uvicorn api.main:app --port 8000 &
sleep 3
curl -s http://localhost:8000/api/dashboard/summary | python -m json.tool

echo "=== 5. 三大文件校验 ==="
python tools/validate_three_files.py

echo "=== 验证完成 ==="
```
