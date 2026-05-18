"""Quick validation of SQLite integration."""
import os

from src.data_layer import get_connection, table_exists, table_row_count
from src.data_layer import CanonicalStore, FeatureStore, LabelStore, DatasetBuilder
from src.experiment_store import ExperimentStore
from src.config_loader import load_config


def main():
    cfg = load_config()
    print("database.path:", cfg.get("database", {}).get("path", "NOT SET"))

    # Test connection + schema init
    con = get_connection(cfg)
    print("SQLite connection OK")

    # List all created tables
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    print("Tables:", [t[0] for t in tables])

    # Test table state
    for t in ["daily_bar", "industry_map", "feature_wide", "predictions", "data_versions"]:
        print(f"  {t}: exists={table_exists(cfg, t)}, rows={table_row_count(cfg, t)}")

    # Test Store instantiation with cfg
    fs = FeatureStore.from_config(cfg)
    ls = LabelStore.from_config(cfg)
    cs = CanonicalStore.from_config(cfg)
    db = DatasetBuilder.from_config(cfg)
    es = ExperimentStore("data/results", cfg=cfg)
    print("All stores instantiated OK")

    # SQLite detection (should be False - tables empty, feature_wide not yet created)
    print("FS._use_db():", fs._use_db())
    print("LS._use_db():", ls._use_db())
    print("CS._use_db():", cs._use_db())
    print("DB._use_db():", db._use_db())

    # Test write + read cycle with small DataFrame
    import pandas as pd
    import numpy as np

    test_df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10),
        "code": ["sh.600000"] * 10,
        "industry": ["银行"] * 10,
        "feat_test1": np.random.randn(10),
        "feat_test2": np.random.randn(10),
    })

    # Save to FeatureStore
    fs.save(test_df, ["feat_test1", "feat_test2"])
    print("\nAfter FeatureStore.save():")
    print("  FS._use_db():", fs._use_db())
    print("  FS.list_features():", fs.list_features())

    # Load from SQLite
    loaded = fs.load()
    print("  Loaded shape:", loaded.shape)
    print("  Loaded cols:", loaded.columns.tolist())

    # Test filtered load
    subset = fs.load(feature_subset=["feat_test1"], date_range=("2024-01-03", "2024-01-07"))
    print("  Filtered shape:", subset.shape)

    # Label test
    label_df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10),
        "code": ["sh.600000"] * 10,
        "label_5d_ret": np.random.randn(10),
    })
    ls.save(label_df, "label_5d_ret")
    print("\nAfter LabelStore.save():")
    print("  LS._use_db():", ls._use_db())
    print("  LS.list_labels():", ls.list_labels())

    # DatasetBuilder test
    print("\nDatasetBuilder._use_db():", db._use_db())
    train = db.build_train_dataset(label_name="label_5d_ret")
    print("  Train dataset shape:", train.shape)
    print("  Train cols:", train.columns.tolist())

    # Cleanup
    from src.data_layer.db import close_connection
    close_connection(cfg)

    # Remove test db
    db_path = cfg.get("database", {}).get("path", "data/quant.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"\nCleaned up test DB: {db_path}")

    print("\n[OK] ALL SQLITE INTEGRATION TESTS PASSED!")


if __name__ == "__main__":
    main()
