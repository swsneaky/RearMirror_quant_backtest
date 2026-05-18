"""
cross_section 截面处理语义回归测试
锁住 MAD -> 行业中性化(基于clipped) -> Z-Score 的实现语义
"""
import numpy as np
import pandas as pd
import pytest

from src.cross_section import cross_sectional_process, _mad_clip


@pytest.fixture
def cs_cfg():
    return {
        "cross_section": {
            "mad_multiplier": 3.0,
            "min_industry_stocks": 2,
            "zscore_eps": 1e-8,
        }
    }


def _make_daily(values_a, values_b, date="2024-01-15"):
    """构造双行业单日截面数据"""
    n_a, n_b = len(values_a), len(values_b)
    return pd.DataFrame({
        "date": [date] * (n_a + n_b),
        "code": [f"A{i}" for i in range(n_a)] + [f"B{i}" for i in range(n_b)],
        "industry": ["IndA"] * n_a + ["IndB"] * n_b,
        "feat_x": values_a + values_b,
    })


class TestCrossSectionSemantics:
    """MAD -> 行业中性化(clipped) -> Z-Score 三步曲语义"""

    def test_mad_then_neutralize_uses_clipped(self, cs_cfg):
        """行业均值必须基于 MAD 截尾后序列，而非原始值"""
        # IndA 含极端值 100，MAD 截尾后应被拉回
        df = _make_daily(
            values_a=[1.0, 2.0, 3.0, 100.0],
            values_b=[5.0, 6.0, 7.0, 8.0],
        )
        result = cross_sectional_process(df, ["feat_x"], cs_cfg)

        # 手工计算期望: 先 MAD clip，再用 clipped 行业均值中性化，再 Z-Score
        raw = df["feat_x"].copy()
        mad_mult = cs_cfg["cross_section"]["mad_multiplier"]
        clipped = _mad_clip(raw, mad_mult)

        # 行业均值应基于 clipped
        ind_a_mask = df["industry"] == "IndA"
        ind_b_mask = df["industry"] == "IndB"
        mean_a = clipped[ind_a_mask].mean()
        mean_b = clipped[ind_b_mask].mean()
        neutralized = clipped.copy()
        neutralized[ind_a_mask] -= mean_a
        neutralized[ind_b_mask] -= mean_b
        std_val = neutralized.std()
        expected = (neutralized - neutralized.mean()) / std_val

        np.testing.assert_allclose(
            result["feat_x"].values, expected.values, atol=1e-6,
            err_msg="行业中性化未基于 MAD 截尾后序列"
        )

    def test_small_industry_skips_neutralize(self, cs_cfg):
        """行业样本数 < min_industry_stocks 时跳过行业中性化"""
        cs_cfg["cross_section"]["min_industry_stocks"] = 3
        df = _make_daily(
            values_a=[1.0, 2.0],  # IndA 只有 2 只，不足 3
            values_b=[5.0, 6.0, 7.0],
        )
        result = cross_sectional_process(df, ["feat_x"], cs_cfg)

        # IndA (2只 < min=3): 跳过中性化，仅 MAD + Z-Score
        # IndB (3只 >= min=3): 正常中性化
        raw = df["feat_x"].copy()
        clipped = _mad_clip(raw, cs_cfg["cross_section"]["mad_multiplier"])
        ind_a = df["industry"] == "IndA"
        ind_b = df["industry"] == "IndB"
        mean_b = clipped[ind_b].mean()
        neutralized = clipped.copy()
        # IndA: 不减行业均值 (小样本保护)
        neutralized[ind_b] -= mean_b
        std_val = neutralized.std()
        expected = (neutralized - neutralized.mean()) / std_val

        np.testing.assert_allclose(
            result["feat_x"].values, expected.values, atol=1e-6,
            err_msg="小样本行业保护语义不正确"
        )

    def test_zscore_zero_when_constant(self, cs_cfg):
        """所有值相同时 Z-Score 应输出 0"""
        df = _make_daily(
            values_a=[5.0, 5.0, 5.0],
            values_b=[5.0, 5.0, 5.0],
        )
        result = cross_sectional_process(df, ["feat_x"], cs_cfg)
        assert (result["feat_x"] == 0.0).all()

    def test_multi_feature_independence(self, cs_cfg):
        """多个因子列应各自独立处理"""
        df = _make_daily(
            values_a=[1.0, 2.0, 3.0],
            values_b=[10.0, 20.0, 30.0],
        )
        df["feat_y"] = [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
        result = cross_sectional_process(df, ["feat_x", "feat_y"], cs_cfg)

        # 各列独立计算，feat_x 的存在不影响 feat_y
        df_single = _make_daily(
            values_a=[1.0, 2.0, 3.0],
            values_b=[10.0, 20.0, 30.0],
        )
        df_single["feat_y"] = [100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
        result_y_only = cross_sectional_process(df_single, ["feat_y"], cs_cfg)

        np.testing.assert_allclose(
            result["feat_y"].values, result_y_only["feat_y"].values, atol=1e-6
        )

    def test_segmented_execution_matches_single_pass(self, cs_cfg):
        """分段执行不应改变逐日截面语义或输出顺序"""
        dates = pd.date_range("2024-01-01", periods=4)
        df = pd.concat(
            [
                pd.DataFrame(
                    {
                        "date": [d] * 6,
                        "code": [f"A{i}" for i in range(3)] + [f"B{i}" for i in range(3)],
                        "industry": ["IndA"] * 3 + ["IndB"] * 3,
                        "feat_x": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
                        "feat_y": [5.0, 6.0, 7.0, 100.0, 110.0, 120.0],
                    }
                )
                for d in dates
            ],
            ignore_index=True,
        )

        single_pass = cross_sectional_process(df.copy(), ["feat_x", "feat_y"], cs_cfg, chunk_size=4)
        segmented = cross_sectional_process(df.copy(), ["feat_x", "feat_y"], cs_cfg, chunk_size=2)

        pd.testing.assert_frame_equal(segmented, single_pass)

    def test_segment_plan_manifest_is_exposed(self, cs_cfg):
        """分段执行应暴露可审计的 chunk manifest"""
        dates = pd.date_range("2024-01-01", periods=5)
        df = pd.concat(
            [
                pd.DataFrame(
                    {
                        "date": [d] * 4,
                        "code": [f"A{i}" for i in range(2)] + [f"B{i}" for i in range(2)],
                        "industry": ["IndA"] * 2 + ["IndB"] * 2,
                        "feat_x": [1.0, 2.0, 10.0, 11.0],
                    }
                )
                for d in dates
            ],
            ignore_index=True,
        )

        result = cross_sectional_process(df, ["feat_x"], cs_cfg, chunk_size=2)
        plan = result.attrs["cross_section_segment_plan"]

        assert plan["chunk_days"] == 2
        assert plan["segment_count"] == 3
        assert [seg["date_count"] for seg in plan["segments"]] == [2, 2, 1]
        assert plan["segments"][0]["date_start"].startswith("2024-01-01")
        assert plan["segments"][-1]["date_end"].startswith("2024-01-05")

    def test_runtime_mode_chunk_budget_keeps_same_semantics(self, cs_cfg):
        """formal/shared_machine 只允许改变 chunk budget，不改变结果语义"""
        cs_cfg["runtime"] = {
            "default_mode": "formal",
            "modes": {
                "formal": {"neutralize_chunk_days": 4},
                "shared_machine": {"neutralize_chunk_days": 1},
            },
        }
        dates = pd.date_range("2024-01-01", periods=4)
        df = pd.concat(
            [
                pd.DataFrame(
                    {
                        "date": [d] * 4,
                        "code": [f"A{i}" for i in range(2)] + [f"B{i}" for i in range(2)],
                        "industry": ["IndA"] * 2 + ["IndB"] * 2,
                        "feat_x": [1.0, 2.0, 10.0, 11.0],
                    }
                )
                for d in dates
            ],
            ignore_index=True,
        )

        formal = cross_sectional_process(df.copy(), ["feat_x"], cs_cfg, runtime_mode="formal")
        shared = cross_sectional_process(df.copy(), ["feat_x"], cs_cfg, runtime_mode="shared_machine")

        pd.testing.assert_frame_equal(shared, formal)
        assert formal.attrs["cross_section_segment_plan"]["chunk_days"] == 4
        assert shared.attrs["cross_section_segment_plan"]["chunk_days"] == 1
