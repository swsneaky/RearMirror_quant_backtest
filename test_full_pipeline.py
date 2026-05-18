"""
全链路冒烟测试 -- 用 20 只股票跑通: ETL -> Feature -> CrossSection -> Label -> Backtest(+SHAP) -> IC Analysis

第一阶段重构后新增验证:
  - FeatureStore / LabelStore 独立落盘
  - DatasetBuilder 拼装训练集
  - ExperimentStore 标准化产物 (predictions, holdings, nav, metrics)

第二阶段 SQLite 验证:
  - ETL -> daily_bar + industry_map 入库
  - FeatureStore -> feature_wide 表
  - LabelStore -> label_wide 表
  - DatasetBuilder -> SQLite SQL JOIN
  - ExperimentStore -> predictions/holdings/nav_daily/metrics_summary 表
"""
import os

from src.config_loader import load_config
from src.data_hub import merge_and_clean
from pipeline import run_feature_pipeline, run_backtest_pipeline, run_factor_analysis
from src.data_layer import FeatureStore, LabelStore, DatasetBuilder
from src.data_layer import get_connection, table_exists, table_row_count
from src.experiment_store import ExperimentStore


def main():
    cfg = load_config()

    # 缩短训练窗口以适配小数据量
    cfg["backtest"]["train_window"] = 200
    cfg["backtest"]["top_k"] = 5                   # 20只股票，top_k 设小
    cfg["backtest"]["return_shap"] = True          # 开启 SHAP
    cfg["features"]["min_listing_days"] = 30       # 测试用，放宽一点

    print("=" * 60)
    print("STEP 1: ETL 合并清洗")
    print("=" * 60)
    raw_df = merge_and_clean(cfg)
    print(f"  -> 原始矩阵 shape: {raw_df.shape}")
    print(f"  -> 列: {raw_df.columns.tolist()[:10]} ...")

    # --- SQLite 验证: daily_bar ---
    print("\n  [DB] SQLite 验证:")
    assert table_exists(cfg, "daily_bar"), "daily_bar 表未创建!"
    db_rows = table_row_count(cfg, "daily_bar")
    print(f"    daily_bar: {db_rows} 行")
    assert db_rows > 0, "daily_bar 为空!"

    print("\n" + "=" * 60)
    print("STEP 2: 特征工程 + 截面处理 + 标签生成")
    print("=" * 60)
    feat_df = run_feature_pipeline(cfg)
    print(f"  -> 特征矩阵 shape: {feat_df.shape}")
    features = [c for c in feat_df.columns if c.startswith("feat_")]
    print(f"  -> 因子数: {len(features)}")

    # --- 验证数据资产分层 ---
    print("\n  [CHECK] 验证 FeatureStore / LabelStore 独立落盘:")
    fs = FeatureStore.from_config(cfg)
    ls = LabelStore.from_config(cfg)
    assert fs.exists, "FeatureStore 未落盘!"
    assert ls.exists, "LabelStore 未落盘!"
    print(f"    FeatureStore: {fs.store_path} ({len(fs.list_features())} 因子)")
    print(f"    LabelStore:   {ls.store_path} ({len(ls.list_labels())} 标签)")

    # --- SQLite 验证: feature_wide + label_wide ---
    print("\n  [DB] SQLite 验证:")
    assert table_exists(cfg, "feature_wide"), "feature_wide 表未创建!"
    assert table_exists(cfg, "label_wide"), "label_wide 表未创建!"
    print(f"    feature_wide: {table_row_count(cfg, 'feature_wide')} 行, {len(fs.list_features())} 因子")
    print(f"    label_wide:   {table_row_count(cfg, 'label_wide')} 行, {len(ls.list_labels())} 标签")
    print(f"    FS._use_db(): {fs._use_db()}")
    print(f"    LS._use_db(): {ls._use_db()}")

    # --- 验证 DatasetBuilder ---
    print("\n  [CHECK] 验证 DatasetBuilder 组装:")
    builder = DatasetBuilder.from_config(cfg)
    print(f"    DB._use_db(): {builder._use_db()}")
    train_ds = builder.build_train_dataset(label_name=cfg["label"]["name"])
    print(f"    训练集 shape: {train_ds.shape}")
    assert cfg["label"]["name"] in train_ds.columns, "训练集缺少标签列!"
    feat_cols = [c for c in train_ds.columns if c.startswith("feat_")]
    assert len(feat_cols) > 0, "训练集缺少因子列!"
    print(f"    [OK] DatasetBuilder 验证通过")

    print("\n" + "=" * 60)
    print("STEP 3: Walk-Forward 回测 (with SHAP)")
    print("=" * 60)
    results, metrics = run_backtest_pipeline(cfg)
    print(f"  -> 预测记录数: {len(results)}")

    # --- 验证标准化实验产物 ---
    print("\n  [CHECK] 验证 ExperimentStore 标准化产物:")
    exp_store = ExperimentStore("data/results", cfg=cfg)
    pred = exp_store.load_predictions()
    assert pred is not None, "predictions 未落盘!"
    print(f"    predictions: {len(pred)} 行")

    holdings = exp_store.load_holdings()
    assert holdings is not None, "holdings 未落盘!"
    print(f"    holdings: {len(holdings)} 行")

    nav = exp_store.load_nav()
    if nav is not None:
        print(f"    nav_daily: {len(nav)} 行")

    m = exp_store.load_metrics()
    assert m is not None, "metrics 未落盘!"
    print(f"    metrics: {list(m.keys())[:5]} ...")
    print(f"    [OK] ExperimentStore 验证通过")

    # --- SQLite 验证: 实验表 ---
    print("\n  [DB] SQLite 实验表验证:")
    for t in ["predictions", "holdings", "nav_daily", "metrics_summary"]:
        rows = table_row_count(cfg, t)
        print(f"    {t}: {rows} 行")

    print("\n" + "=" * 60)
    print("STEP 4: IC / ICIR / Decay 因子分析")
    print("=" * 60)
    analysis = run_factor_analysis(cfg)
    print(f"\n  -> IC 时序 shape: {analysis['ic_df'].shape}")
    print(f"  -> IC Decay shape: {analysis['decay_df'].shape}")
    print(f"  -> 相关矩阵 shape: {analysis['corr_df'].shape}")

    # 检查 SHAP 输出
    shap_path = cfg.get("analysis", {}).get("shap_output", "data/features/shap_importance.parquet")
    if os.path.exists(shap_path):
        import pandas as pd
        shap_df = pd.read_parquet(shap_path)
        print(f"\n  -> SHAP 重要性 shape: {shap_df.shape}")
        print(f"  -> SHAP Top 5 因子 (末期均值):")
        print(shap_df.iloc[-1].sort_values(ascending=False).head(5).to_string())

    # --- SQLite 最终汇总 ---
    print("\n" + "=" * 60)
    print("[STAT] SQLite 数据库最终汇总:")
    print("=" * 60)
    con = get_connection(cfg)
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    for (t,) in tables:
        rows = table_row_count(cfg, t)
        print(f"  {t}: {rows} 行")

    db_path = cfg.get("database", {}).get("path", "data/quant.db")
    db_size = os.path.getsize(db_path) / 1024 / 1024
    print(f"\n  数据库文件: {db_path} ({db_size:.1f} MB)")

    print("\n" + "=" * 60)
    print("[OK] 全链路测试通过! (含 SQLite 统一数据库)")
    print("=" * 60)


if __name__ == "__main__":
    main()
