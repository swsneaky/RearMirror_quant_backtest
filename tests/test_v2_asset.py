"""Quick smoke test for v2 asset ID + factor metadata."""
import sys
sys.path.insert(0, "RearMirror")

from src.data_layer.asset_id import make_asset_id, make_config_hash, make_table_name, make_factor_id
from src.registry import registry, FactorMeta
import src.factors  # trigger registration

# Test asset_id generation
cfg1 = {"active_factors": ["kline", "rolling"], "windows": [5, 10, 20, 30, 60]}
cfg2 = {"active_factors": ["kline", "rolling", "technical"], "windows": [5, 10, 20, 30, 60]}
id1 = make_asset_id("feature_set", cfg1)
id2 = make_asset_id("feature_set", cfg2)
assert id1 != id2, "Different configs should produce different IDs"
assert id1 == make_asset_id("feature_set", cfg1), "Same config should produce same ID"
print(f"asset_id idempotent: OK  ({id1})")
print(f"table_name: {make_table_name('feature_set', cfg1)}")

# Test factor meta
for name in registry.list_factors():
    meta = registry.get_factor_meta(name)
    code_hash = registry.get_factor_code_hash(name)
    fid = make_factor_id(name, code_hash)
    status = "META" if meta else "LEGACY"
    n_out = len(meta.output_cols) if meta else 0
    print(f"  {fid}  [{status}] inputs={meta.input_cols if meta else 'N/A'} outputs={n_out}")

# Test SQLite schema creation (new tables)
# import duckdb  # removed after SQLite migration
import tempfile, os
db_path = os.path.join(tempfile.mkdtemp(), "test.db")
test_cfg = {"database": {"path": db_path}}
from src.data_layer.db import get_connection, register_asset, get_asset, list_assets, register_factor_def, close_connection

con = get_connection(test_cfg)

# Check all 3 new tables exist
for t in ["asset_registry", "factor_definitions", "feature_set_factors"]:
    count = con.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{t}'").fetchone()[0]
    assert count == 1, f"Table {t} not found!"
    print(f"  Table {t}: EXISTS")

# Test register + get
register_asset(test_cfg, asset_id="test__abc123", asset_type="feature_set",
               name="test_features", config_hash="abc123")
result = get_asset(test_cfg, "test__abc123")
assert result is not None
assert result["name"] == "test_features"
print(f"  register_asset + get_asset: OK")

# Test register_factor_def
register_factor_def(test_cfg, factor_id="kline__xyz", factor_group="kline",
                    code_hash="xyz", input_cols=["raw_open"], output_cols=["feat_KMID"])
row = con.execute("SELECT * FROM factor_definitions WHERE factor_id = 'kline__xyz'").fetchone()
assert row is not None
print(f"  register_factor_def: OK")

# Cleanup
close_connection(test_cfg)
os.remove(db_path)

print("\nAll v2 smoke tests passed!")
