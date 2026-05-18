import json
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import pipeline
from src.data_layer.dataset_builder import DatasetBuilder
from src.experiment_store import ExperimentStore
from src.runtime_modes import (
    apply_runtime_mode_to_config,
    get_runtime_config,
    resolve_runtime_mode,
)


class TestRuntimeModeHelpers(unittest.TestCase):
    def test_default_runtime_config_contains_formal_and_shared_machine(self):
        runtime_cfg = get_runtime_config({})
        self.assertEqual(runtime_cfg["default_mode"], "formal")
        self.assertEqual(runtime_cfg["shared_machine_default_mode"], "shared_machine")
        self.assertIn("formal", runtime_cfg["modes"])
        self.assertIn("shared_machine", runtime_cfg["modes"])

    def test_apply_runtime_mode_to_config_persists_active_mode_and_overrides(self):
        cfg = {"backtest": {"train_window": 500, "test_step": 5}}
        plan = {
            "mode": "shared_machine",
            "date_range": ("2025-01-01", "2025-12-31"),
            "backtest_overrides": {"train_window": 120, "test_step": 20},
        }
        run_cfg = apply_runtime_mode_to_config(cfg, "shared_machine", plan)

        self.assertEqual(run_cfg["runtime"]["active_mode"], "shared_machine")
        self.assertEqual(run_cfg["runtime"]["resolved_plan"]["date_range"], ["2025-01-01", "2025-12-31"])
        self.assertEqual(run_cfg["backtest"]["train_window"], 120)
        self.assertEqual(run_cfg["backtest"]["test_step"], 20)
        self.assertEqual(cfg["backtest"]["train_window"], 500)

    def test_unknown_runtime_mode_raises(self):
        with self.assertRaises(ValueError):
            resolve_runtime_mode({}, "does_not_exist")


class TestDatasetBuilderRuntimePlan(unittest.TestCase):
    def test_shared_machine_plan_clips_features_and_dates(self):
        builder = DatasetBuilder(
            canonical=None,
            feature_store=None,
            label_store=None,
            cfg={},
        )

        with (
            patch.object(
                builder,
                "_list_available_feature_columns",
                return_value=[f"feat_{i:03d}" for i in range(40)],
            ),
            patch.object(
                builder,
                "_resolve_recent_date_range",
                return_value=("2025-01-02", "2025-12-31"),
            ),
        ):
            plan = builder.resolve_train_runtime_plan(runtime_mode="shared_machine")

        self.assertEqual(plan["mode"], "shared_machine")
        self.assertEqual(plan["feature_count"], 32)
        self.assertEqual(len(plan["feature_subset"]), 32)
        self.assertEqual(plan["date_range"], ("2025-01-02", "2025-12-31"))
        self.assertEqual(plan["backtest_overrides"]["train_window"], 120)
        self.assertEqual(plan["backtest_overrides"]["test_step"], 20)


class TestBacktestPipelineRuntimeMode(unittest.TestCase):
    def test_run_backtest_pipeline_propagates_runtime_mode(self):
        captured: dict = {}

        class DummyStore:
            exists = True

            @classmethod
            def from_config(cls, cfg):
                return cls()

        class DummyBuilder:
            last_kwargs = None

            @classmethod
            def from_config(cls, cfg):
                return cls()

            def build_train_dataset(self, **kwargs):
                type(self).last_kwargs = kwargs
                df = pd.DataFrame(
                    {
                        "date": pd.to_datetime(["2026-01-05", "2026-01-26"]),
                        "code": ["000001.SZ", "000001.SZ"],
                        "feat_A": [0.1, 0.2],
                        "label_5d_ret": [0.01, 0.02],
                        "raw_pctChg": [0.01, 0.02],
                        "raw_amount": [1000.0, 1200.0],
                    }
                )
                df.attrs["dataset_runtime_plan"] = {
                    "mode": "shared_machine",
                    "description": "shared machine test plan",
                    "feature_subset": ["feat_A"],
                    "feature_count": 1,
                    "available_feature_count": 4,
                    "date_range": ("2026-01-05", "2026-01-26"),
                    "recent_trade_dates": 260,
                    "feature_limit": 32,
                    "backtest_overrides": {"train_window": 120, "test_step": 20},
                }
                return df

        class DummyExperimentStore:
            register_cfg = None
            save_cfg = None
            finished = None

            def __init__(self, base_dir="data/results", cfg=None):
                self.cfg = cfg

            def set_lineage(self, feature_set_id=None, label_set_id=None):
                captured["lineage"] = (feature_set_id, label_set_id)

            def register_run(self, cfg=None):
                type(self).register_cfg = cfg

            def save_predictions(self, df):
                captured["saved_predictions"] = len(df)

            def save_holdings(self, df):
                captured["saved_holdings"] = len(df)

            def save_nav(self, df):
                captured["saved_nav"] = len(df)

            def save_metrics(self, metrics):
                captured["saved_metrics"] = metrics

            def save_config(self, cfg):
                type(self).save_cfg = cfg

            def finish_run(self, status="done"):
                type(self).finished = status

        def fake_run_walk_forward(df, features, cfg, output_dir=None):
            captured["run_cfg"] = cfg
            captured["features"] = features
            return pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-01-26"]),
                    "code": ["000001.SZ"],
                    "label_5d_ret": [0.02],
                    "pred_score": [0.5],
                    "pred_rank": [1.0],
                    "selected": [1],
                    "raw_pctChg": [0.02],
                    "cost_ratio": [0.001],
                    "turnover_ratio": [0.1],
                }
            )

        def fake_evaluate(results, cfg):
            captured["eval_cfg"] = cfg
            return {"ann_return": 0.1, "avg_turnover": 0.1}

        def fake_build_holdings(results, top_k):
            return pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-01-26"]),
                    "code": ["000001.SZ"],
                    "weight": [1.0],
                    "is_new": [1],
                    "is_exit": [0],
                }
            )

        def fake_build_nav(metrics, results):
            return pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-01-26"]),
                    "nav": [1.02],
                    "bench_nav": [1.01],
                    "excess_nav": [1.01],
                    "cost_ratio": [0.001],
                    "turnover_ratio": [0.1],
                }
            )

        cfg = {
            "label": {"name": "label_5d_ret", "horizon": 5},
            "backtest": {"train_window": 500, "gap": 5, "test_step": 5, "top_k": 30},
            "runtime": {"default_mode": "formal"},
            "paths": {"models": "models"},
            "model": {"active": "xgboost"},
        }

        with (
            patch.object(pipeline, "FeatureStore", DummyStore),
            patch.object(pipeline, "LabelStore", DummyStore),
            patch.object(pipeline, "DatasetBuilder", DummyBuilder),
            patch.object(pipeline, "ExperimentStore", DummyExperimentStore),
            patch.object(pipeline, "run_walk_forward", side_effect=fake_run_walk_forward),
            patch.object(pipeline, "evaluate", side_effect=fake_evaluate),
            patch.object(pipeline, "build_holdings_from_predictions", side_effect=fake_build_holdings),
            patch.object(pipeline, "build_nav_from_metrics", side_effect=fake_build_nav),
        ):
            results, metrics = pipeline.run_backtest_pipeline(
                cfg=cfg,
                output_dir="qa/runtime_mode_test",
                feature_set_id="feature_set__6c32da819187",
                label_set_id="label_set__3896aeaf202a",
                runtime_mode="shared_machine",
            )

        self.assertFalse(results.empty)
        self.assertEqual(metrics["ann_return"], 0.1)
        self.assertEqual(DummyBuilder.last_kwargs["runtime_mode"], "shared_machine")
        self.assertEqual(captured["features"], ["feat_A"])
        self.assertEqual(captured["run_cfg"]["runtime"]["active_mode"], "shared_machine")
        self.assertEqual(captured["run_cfg"]["backtest"]["train_window"], 120)
        self.assertEqual(captured["run_cfg"]["backtest"]["test_step"], 20)
        self.assertEqual(DummyExperimentStore.register_cfg["runtime"]["active_mode"], "shared_machine")
        self.assertEqual(DummyExperimentStore.save_cfg["runtime"]["resolved_plan"]["date_range"], ["2026-01-05", "2026-01-26"])
        self.assertEqual(DummyExperimentStore.finished, "done")


class TestExperimentStoreMetrics(unittest.TestCase):
    def test_save_metrics_skips_series_like_entries(self):
        tmpdir = tempfile.mkdtemp()
        store = ExperimentStore(tmpdir)
        metrics = {
            "ann_return": 0.12,
            "avg_turnover": 0.34,
            "nav": pd.Series([1.0, 1.1], index=pd.to_datetime(["2026-01-01", "2026-01-02"])),
        }

        path = store.save_metrics(metrics)

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["ann_return"], 0.12)
        self.assertEqual(payload["avg_turnover"], 0.34)
        self.assertNotIn("nav", payload)
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
