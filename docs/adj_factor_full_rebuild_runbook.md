# 复权因子纠偏与全量重算执行手册（含单股短窗闸门）

## 1. 目的与结论

当历史 `fwd_factor` / `bwd_factor` 错误或缺失时，`forward/backward` 价格视图会失真，所有依赖价格的特征、标签、回测结果都会被污染。  
本手册要求采用 **“先单股短窗试跑 -> 再全量重算”** 的硬门禁流程，避免直接全量重算后才发现口径问题。

> 硬规则：  
> 1) 单股短窗闸门未通过，禁止进入全量重算。  
> 2) 全量重算前必须做可恢复备份。  
> 3) 全量重算后必须完成验收 SQL 与抽样核对。


## 2. 适用范围

- 代码仓：`E:\quant\RearMirror`
- 数据库：`data/quant.db`
- 关键表：`daily_bar`, `feature_wide`, `label_wide`, `factor_rebuild_queue`
- 关键逻辑：
  - 复权因子落库：`src/data_hub/baostock_client.py`
  - 因子清洗/回补队列：`src/data_hub/etl_process.py`
  - 价格投影：`src/price_mode.py`
  - 特征增量/回补：`pipeline.py::run_raw_feature_pipeline`
  - 标签更新：`pipeline.py::run_label_pipeline`


## 3. 执行前准备

1. 进入仓库根目录：`E:\quant\RearMirror`
2. 使用项目 Python：`E:\quant\.venv\Scripts\python.exe`
3. 确认本次执行时间戳（示例）：`TS=20260419_224500`
4. 创建输出目录：

```powershell
New-Item -ItemType Directory -Force qa/adj_factor_rebuild/$env:TS | Out-Null
```

5. 先记录当前基线（不要跳过）：

```powershell
@'
import sqlite3, pandas as pd
con=sqlite3.connect("data/quant.db")
for name in ["daily_bar","feature_wide","label_wide","factor_rebuild_queue"]:
    try:
        df=pd.read_sql_query(f"SELECT COUNT(*) AS cnt, MIN(DATE(date)) AS min_date, MAX(DATE(date)) AS max_date FROM {name}", con)
        print(name); print(df.to_string(index=False)); print()
    except Exception as e:
        print(name, "missing:", e)
con.close()
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/00_baseline.txt
```


## 4. Phase A：单股短窗试跑（Gate-1，必须通过）

### A1. 生成试跑配置（独立 QA 库，不污染正式库）

```powershell
@'
from pathlib import Path
import yaml

cfg_path = Path("configs/base_config.yaml")
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

cfg["database"]["path"] = "data/qa/pilot_adj_factor.db"
cfg["etl"]["cache_dir"] = "data/qa/pilot_cache"
cfg["etl"]["update_mode"] = "full"
cfg["etl"]["start_date"] = "2023-01-01"
cfg["etl"]["end_date"] = "2024-12-31"
cfg["etl"]["max_stocks"] = 0
cfg["price"]["mode"] = "forward"

Path("configs/tmp").mkdir(parents=True, exist_ok=True)
Path("configs/tmp/pilot_adj_factor.yaml").write_text(
    yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
    encoding="utf-8"
)
print("written configs/tmp/pilot_adj_factor.yaml")
'@ | E:\quant\.venv\Scripts\python.exe -
```

### A2. 单股抓取 + 入库（短窗）

> 建议优先用一个你熟悉且历史上有公司行为的代码。  
> 若第一次样本全 1 因子，则换代码或拉长窗口后重试。

```powershell
@'
import yaml
from baostock import bs
from src.data_hub.baostock_client import _fetch_single_stock
from src.data_hub.etl_process import ingest_daily_bar_df

cfg = yaml.safe_load(open("configs/tmp/pilot_adj_factor.yaml","r",encoding="utf-8"))
code = "sh.600000"   # 可替换
sd, ed = "2023-01-01", "2024-12-31"

bs.login()
df = _fetch_single_stock(code, cfg, start_date=sd, end_date=ed)
bs.logout()

if df is None or df.empty:
    raise RuntimeError("pilot fetch empty")

ingest_daily_bar_df(df, cfg)
print("pilot rows:", len(df), "code:", code)
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/10_pilot_fetch_ingest.txt
```

### A3. 单股因子质量闸门检查

```powershell
@'
import sqlite3, pandas as pd
con=sqlite3.connect("data/qa/pilot_adj_factor.db")
q = """
SELECT
  COUNT(*) AS n_rows,
  SUM(CASE WHEN fwd_factor IS NULL THEN 1 ELSE 0 END) AS fwd_null,
  SUM(CASE WHEN bwd_factor IS NULL THEN 1 ELSE 0 END) AS bwd_null,
  SUM(CASE WHEN COALESCE(fwd_factor,1)<=0 THEN 1 ELSE 0 END) AS fwd_nonpos,
  SUM(CASE WHEN COALESCE(bwd_factor,1)<=0 THEN 1 ELSE 0 END) AS bwd_nonpos,
  SUM(CASE WHEN ABS(COALESCE(fwd_factor,1)-1.0) > 1e-10 THEN 1 ELSE 0 END) AS fwd_not_one,
  SUM(CASE WHEN ABS(COALESCE(bwd_factor,1)-1.0) > 1e-10 THEN 1 ELSE 0 END) AS bwd_not_one
FROM daily_bar
"""
df = pd.read_sql_query(q, con)
print(df.to_string(index=False))
con.close()
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/11_pilot_factor_quality.txt
```

Gate-1 通过标准（全部满足）：

1. `n_rows > 0`
2. `fwd_null = 0` 且 `bwd_null = 0`
3. `fwd_nonpos = 0` 且 `bwd_nonpos = 0`
4. 至少一个方向出现过 `*_not_one > 0`（若都为 0，说明样本不足以验证复权，必须换代码或延长区间重试）

### A4. 单股特征/标签链路试跑

```powershell
@'
import yaml
from pipeline import run_raw_feature_pipeline, run_label_pipeline, _check_data_freshness

cfg = yaml.safe_load(open("configs/tmp/pilot_adj_factor.yaml","r",encoding="utf-8"))
run_raw_feature_pipeline(cfg)
res = run_label_pipeline(cfg, incremental=True)
fresh = _check_data_freshness(cfg, run_prediction=False)
print("label_result:", res)
print("freshness:", fresh)
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/12_pilot_feature_label.txt
```

Gate-1 最终判定：

- 通过：进入 Phase B 全量重算
- 不通过：停止执行，记录失败原因并修复后从 A1 重来


## 5. Phase B：全量重算（Gate-2）

### B1. 全量前备份（必须）

```powershell
$ts = $env:TS
New-Item -ItemType Directory -Force "backups/$ts" | Out-Null
Copy-Item data/quant.db "backups/$ts/quant.db.bak" -Force
if (Test-Path data/features/feature_store.parquet) { Copy-Item data/features/feature_store.parquet "backups/$ts/feature_store.parquet.bak" -Force }
if (Test-Path data/features/zz500_alpha158_raw.parquet) { Copy-Item data/features/zz500_alpha158_raw.parquet "backups/$ts/raw_feature.parquet.bak" -Force }
```

> 注：`stock_daily_cache` 体积可能很大，可按磁盘空间决定是否整目录备份。

### B2. 调整正式配置为全量模式

必须确认 `configs/base_config.yaml`：

- `etl.update_mode: "full"`
- `etl.end_date` 覆盖到本次目标日期
- `price.mode: "forward"`（或你指定的最终模式）

### B3. 执行全量下载 + 全量 ETL

```powershell
@'
from src.config_loader import load_config
from src.data_hub.baostock_client import run_downloader
from src.data_hub.etl_process import merge_and_clean
cfg = load_config("configs/base_config.yaml")
run_downloader(cfg)
merge_and_clean(cfg)
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/20_full_download_etl.txt
```

### B4. 强制全量重建 feature/label

先清空旧结果，确保不是增量拼接：

```powershell
@'
from src.config_loader import load_config
from src.data_layer.db import get_connection, table_exists
cfg = load_config("configs/base_config.yaml")
con = get_connection(cfg)
if table_exists(cfg, "feature_wide"): con.execute("DELETE FROM feature_wide")
if table_exists(cfg, "label_wide"): con.execute("DELETE FROM label_wide")
if table_exists(cfg, "factor_rebuild_queue"): con.execute("DELETE FROM factor_rebuild_queue")
print("cleared feature_wide/label_wide/factor_rebuild_queue")
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/21_clear_old_outputs.txt
```

然后重算：

```powershell
@'
from src.config_loader import load_config
from pipeline import run_raw_feature_pipeline, run_neutralize_pipeline, run_label_pipeline
cfg = load_config("configs/base_config.yaml")
raw_df, all_features, gfm = run_raw_feature_pipeline(cfg)
run_neutralize_pipeline(cfg, raw_df, all_features, gfm)
run_label_pipeline(cfg, incremental=True)
print("full rebuild done")
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/22_full_feature_label_neutralize.txt
```


## 6. Phase C：验收（必须）

### C1. 因子覆盖验收

```powershell
@'
import sqlite3, pandas as pd
con=sqlite3.connect("data/quant.db")
q = """
SELECT
  COUNT(*) AS n_rows,
  COUNT(DISTINCT code) AS n_codes,
  MIN(DATE(date)) AS min_date,
  MAX(DATE(date)) AS max_date,
  SUM(CASE WHEN fwd_factor IS NULL THEN 1 ELSE 0 END) AS fwd_null,
  SUM(CASE WHEN bwd_factor IS NULL THEN 1 ELSE 0 END) AS bwd_null,
  SUM(CASE WHEN COALESCE(fwd_factor,1)<=0 THEN 1 ELSE 0 END) AS fwd_nonpos,
  SUM(CASE WHEN COALESCE(bwd_factor,1)<=0 THEN 1 ELSE 0 END) AS bwd_nonpos,
  SUM(CASE WHEN ABS(COALESCE(fwd_factor,1)-1.0) > 1e-10 THEN 1 ELSE 0 END) AS fwd_not_one,
  SUM(CASE WHEN ABS(COALESCE(bwd_factor,1)-1.0) > 1e-10 THEN 1 ELSE 0 END) AS bwd_not_one
FROM daily_bar
"""
print(pd.read_sql_query(q, con).to_string(index=False))
con.close()
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/30_accept_factor_coverage.txt
```

通过标准：

1. `fwd_null = 0` 且 `bwd_null = 0`
2. `fwd_nonpos = 0` 且 `bwd_nonpos = 0`
3. 全市场层面 `fwd_not_one > 0` 且 `bwd_not_one > 0`

### C2. 新鲜度与链路一致性验收

```powershell
@'
from src.config_loader import load_config
from pipeline import _check_data_freshness
cfg = load_config("configs/base_config.yaml")
print(_check_data_freshness(cfg, run_prediction=False))
'@ | E:\quant\.venv\Scripts\python.exe - | Tee-Object qa/adj_factor_rebuild/$env:TS/31_accept_freshness.txt
```

通过标准：

- `feature_wide.max_date == daily_bar.max_date`
- `label_wide` 通过 horizon 滞后规则（`_check_data_freshness` 不报 fail）

### C3. 业务抽样验收（建议）

随机抽 10~20 只股票，检查：

- 复权前后收益序列是否符合预期（有公司行为的股票出现尺度调整）
- 关键价格类特征（如 `feat_VWAP_BIAS*`）是否仍在合理分布区间


## 7. 回滚方案

出现以下任一情况必须回滚：

1. 全量后 `fwd/bwd` 仍大面积缺失或非正
2. `feature_wide` 日期无法追平 `daily_bar`
3. 样本核对显示复权价格明显异常

回滚命令（PowerShell）：

```powershell
$ts = "<你的备份时间戳>"
Copy-Item "backups/$ts/quant.db.bak" "data/quant.db" -Force
if (Test-Path "backups/$ts/feature_store.parquet.bak") { Copy-Item "backups/$ts/feature_store.parquet.bak" "data/features/feature_store.parquet" -Force }
if (Test-Path "backups/$ts/raw_feature.parquet.bak") { Copy-Item "backups/$ts/raw_feature.parquet.bak" "data/features/zz500_alpha158_raw.parquet" -Force }
```

回滚后，把 `price.mode` 临时设为 `raw`，阻止继续消费错误复权口径。


## 8. 交付物清单（低级 AI 必交）

执行完成后，必须提交以下文件到 `qa/adj_factor_rebuild/<TS>/`：

1. `00_baseline.txt`
2. `10_pilot_fetch_ingest.txt`
3. `11_pilot_factor_quality.txt`
4. `12_pilot_feature_label.txt`
5. `20_full_download_etl.txt`
6. `21_clear_old_outputs.txt`
7. `22_full_feature_label_neutralize.txt`
8. `30_accept_factor_coverage.txt`
9. `31_accept_freshness.txt`
10. 失败时的 `rollback` 记录

并在 `WORKLOG_archive/2026Q2.md` 追加：

- 执行时间
- Gate-1 是否通过
- Gate-2 是否通过
- 是否回滚
- 最终结论（可用 / 不可用）

