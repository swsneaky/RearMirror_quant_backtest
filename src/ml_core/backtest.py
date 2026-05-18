"""
Walk-Forward 回测引擎
铁律五：GAP >= label.horizon，step 对齐预测周期，零前瞻偏差
铁律六：外层顺序执行，内层模型 n_jobs=1 (已在 config 中锁定)

可交易性三重过滤 (每个调仓日执行):
  1. ST/ST* 过滤      -- isST == 1
  2. 停牌过滤         -- tradestatus == 0
  3. 涨跌停过滤       -- |pctChg| >= limit_pct_threshold (无法成交)

交易成本模型 (v2):
  买入: 佣金(万三) + 冲击成本(平方根模型)
  卖出: 佣金(万三) + 印花税(千一) + 冲击成本(平方根模型)
  冲击成本 = impact_coeff x sqrt(trade_amount / daily_amount)

换手率控制:
  max_turnover 限制单期最大换手比例，超出时优先保留已持仓个股
"""
import json
import logging
import os

import joblib
import numpy as np
import pandas as pd
from tqdm import tqdm

from src.ml_core import build_model

logger = logging.getLogger(__name__)

try:
    import shap as _shap
    _SHAP_OK = True
except ImportError:
    _SHAP_OK = False


# ====================================================
# 可交易性过滤
# ====================================================
def _filter_tradeable(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    返回当日可交易子集：去除 ST / 停牌 / 涨跌停。
    兼容旧版特征矩阵 (没有 isST/tradestatus 列时跳过对应过滤)。
    """
    mask = pd.Series(True, index=df.index)

    # 1. ST 过滤 (兼容 str / int 类型)
    if "isST" in df.columns:
        ist = pd.to_numeric(df["isST"], errors="coerce").fillna(0)
        mask &= ist == 0

    # 2. 停牌过滤 (兼容 str / int 类型)
    if "tradestatus" in df.columns:
        ts = pd.to_numeric(df["tradestatus"], errors="coerce").fillna(1)
        mask &= ts == 1

    return df[mask].copy()


# ====================================================
# 换手率控制选股
# ====================================================
def _select_with_turnover_control(
    candidates: pd.DataFrame,
    prev_holdings: set[str],
    top_k: int,
    max_turnover: float,
) -> list[str]:
    """
    在预测得分排序的基础上，限制换手率不超过 max_turnover。
    max_turnover=0 表示不限制，等价于纯 Top-K。
    """
    ranked = candidates.sort_values("pred_score", ascending=False)
    all_codes = ranked["code"].tolist()

    if max_turnover <= 0 or not prev_holdings:
        return all_codes[:top_k]

    # 最多允许换掉的股票数
    max_change = max(1, int(top_k * max_turnover))

    # 当前 Top-K 中，保留的 = 仍在可交易候选中的旧持仓
    holdable = [c for c in all_codes if c in prev_holdings]
    new_candidates = [c for c in all_codes if c not in prev_holdings]

    # 计算需要保留多少只旧仓
    min_keep = top_k - max_change
    kept = holdable[:min_keep] if len(holdable) >= min_keep else holdable[:]

    # 剩余名额从新候选 + 多余旧仓中按得分填充
    remaining_pool = [c for c in all_codes if c not in kept]
    remaining_needed = top_k - len(kept)
    selected = kept + remaining_pool[:remaining_needed]

    return selected[:top_k]


# ====================================================
# 交易成本计算
# ====================================================
def _calc_transaction_cost(
    buy_codes: set[str],
    sell_codes: set[str],
    hold_df: pd.DataFrame,
    portfolio_value: float,
    n_positions: int,
    cost_cfg: dict,
) -> float:
    """
    计算单期交易成本 (占组合市值的比例)。

    成本模型:
      佣金: commission x 交易金额 (买卖双向)
      印花税: stamp_tax x 卖出金额
      冲击成本: impact_coeff x sqrt(单笔金额 / 日成交额)

    Returns: total_cost_ratio (占 portfolio_value 比例)
    """
    commission = cost_cfg.get("commission", 0.0003)
    stamp_tax = cost_cfg.get("stamp_tax", 0.001)
    impact_coeff = cost_cfg.get("impact_coeff", 0.1)

    if n_positions == 0:
        return 0.0

    per_stock_amount = portfolio_value / n_positions
    total_cost = 0.0

    trade_codes = buy_codes | sell_codes
    if not trade_codes:
        return 0.0

    # 获取可用的日成交额信息
    has_amount = "raw_amount" in hold_df.columns
    amount_map = {}
    if has_amount:
        amount_map = hold_df.set_index("code")["raw_amount"].to_dict()

    for code in buy_codes:
        # 买入: 佣金 + 冲击
        trade_cost = commission * per_stock_amount
        if has_amount and code in amount_map:
            daily_amt = max(amount_map[code], 1e-6)
            impact = impact_coeff * np.sqrt(per_stock_amount / daily_amt)
            trade_cost += impact * per_stock_amount
        total_cost += trade_cost

    for code in sell_codes:
        # 卖出: 佣金 + 印花税 + 冲击
        trade_cost = (commission + stamp_tax) * per_stock_amount
        if has_amount and code in amount_map:
            daily_amt = max(amount_map[code], 1e-6)
            impact = impact_coeff * np.sqrt(per_stock_amount / daily_amt)
            trade_cost += impact * per_stock_amount
        total_cost += trade_cost

    return total_cost / portfolio_value


# ====================================================
# 内部阶段函数 -- 从 run_walk_forward 中拆出的职责单元
# ====================================================
def _save_fold_artifacts(
    model, fold_idx: int, rebalance_date, train_dates,
    train_df: pd.DataFrame, features: list[str],
    lbl_name: str, cfg: dict, output_dir: str,
) -> None:
    """[Signal/Artifact] 保存单折训练制品：模型 + 元信息"""
    artifacts_dir = os.path.join(output_dir, "models")
    os.makedirs(artifacts_dir, exist_ok=True)
    model_path = os.path.join(artifacts_dir, f"model_fold_{fold_idx}.pkl")
    joblib.dump(model, model_path)

    feat_imp = {}
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
        feat_imp = {f: float(v) for f, v in zip(features, imp)}

    train_meta = {
        "fold": fold_idx,
        "rebalance_date": str(rebalance_date),
        "train_start": str(train_dates[0]),
        "train_end": str(train_dates[-1]),
        "n_train_samples": len(train_df),
        "n_features": len(features),
        "n_stocks_train": int(train_df["code"].nunique()),
        "label_mean": float(train_df[lbl_name].mean()),
        "label_std": float(train_df[lbl_name].std()),
        "model_name": cfg["model"]["active"],
        "model_params": cfg["model"].get(cfg["model"]["active"], {}),
        "feature_importance_top20": dict(
            sorted(feat_imp.items(), key=lambda x: -x[1])[:20]
        ) if feat_imp else {},
    }
    meta_path = os.path.join(artifacts_dir, f"train_meta_{fold_idx}.json")
    with open(meta_path, "w", encoding="utf-8") as mf:
        json.dump(train_meta, mf, indent=2, ensure_ascii=False, default=str)


def _build_portfolio(
    test_tradeable: pd.DataFrame,
    prev_holdings: set[str],
    top_k: int,
    max_turnover: float,
    cost_cfg: dict,
) -> tuple[set[str], float, float]:
    """
    [Portfolio/Execution] 选股 + 换手率控制 + 交易成本计算。

    Returns: (new_holdings, cost_ratio, turnover_ratio)
    """
    selected_codes = _select_with_turnover_control(
        test_tradeable, prev_holdings, top_k, max_turnover
    )
    new_holdings = set(selected_codes)
    buy_codes = new_holdings - prev_holdings
    sell_codes = prev_holdings - new_holdings
    turnover_ratio = len(buy_codes | sell_codes) / max(top_k, 1)
    cost_ratio = _calc_transaction_cost(
        buy_codes, sell_codes, test_tradeable, 1.0, top_k, cost_cfg
    )
    return new_holdings, cost_ratio, turnover_ratio


def _compute_period_shap(
    model, test_tradeable: pd.DataFrame, features: list[str], rebalance_date,
) -> pd.Series | None:
    """[Analytics] 计算单期 SHAP 特征重要性"""
    try:
        explainer = _shap.TreeExplainer(model)
        sv = explainer.shap_values(test_tradeable[features])
        return pd.Series(np.abs(sv).mean(axis=0), index=features, name=rebalance_date)
    except (ValueError, TypeError, RuntimeError) as exc:
        logger.warning("SHAP 跳过 (%s): %s", rebalance_date, exc)
        return None


# ====================================================
# Walk-Forward 主引擎
# ====================================================
def run_walk_forward(
    df: pd.DataFrame,
    features: list[str],
    cfg: dict,
    output_dir: str | None = None,
) -> pd.DataFrame:
    """
    滚动训练 + 截面预测，返回含 pred_score / pred_rank 的结果 DataFrame。
    支持换手率控制和精细化交易成本。

    内部职责分层:
      1. 数据准备   -- 按日期窗口切分训练/测试集 + 可交易性过滤
      2. 信号生成   -- 模型训练 + 预测 + 制品保存 (_save_fold_artifacts)
      3. 组合构建   -- 选股 + 换手约束 + 成本 (_build_portfolio)
      4. 分析辅助   -- SHAP 计算 (_compute_period_shap)

    当 output_dir 非 None 时，每个折叠保存:
      models/model_fold_{i}.pkl     -- 训练好的模型
      models/train_meta_{i}.json    -- 训练元信息 (样本量、日期范围、特征重要性等)
    """
    bt = cfg["backtest"]
    lbl_name = cfg["label"]["name"]
    train_w = bt["train_window"]
    gap = bt["gap"]
    step = bt["test_step"]
    top_k = bt["top_k"]
    max_turnover = bt.get("max_turnover", 0)
    cost_cfg = bt.get("cost", {})

    # 铁律五校验
    label_horizon = cfg["label"]["horizon"]
    assert gap >= label_horizon, (
        f"铁律五违规！gap({gap}) 必须 >= label.horizon({label_horizon})"
    )

    return_shap: bool = bt.get("return_shap", False)
    shap_records = []
    if return_shap and not _SHAP_OK:
        print("[WARN]  shap 包未安装，跳过 SHAP 计算。请运行: pip install shap")
        return_shap = False

    unique_dates = np.sort(df["date"].unique())
    all_results = []
    prev_holdings: set[str] = set()
    period_costs: list[tuple] = []  # (date, cost_ratio, turnover_ratio)

    print(f"[FAST] Walk-Forward 引擎启动: train={train_w}, gap={gap}, step={step}, "
          f"top_k={top_k}, max_turnover={max_turnover}, return_shap={return_shap}")

    for i in tqdm(
        range(train_w + gap, len(unique_dates), step),
        desc="WFA 滚动回测",
    ):
        rebalance_date = unique_dates[i]

        # ---- 1. 数据准备 ----
        train_end_idx = i - gap
        train_start_idx = max(0, train_end_idx - train_w)
        train_dates = unique_dates[train_start_idx:train_end_idx]

        train_df = df[df["date"].isin(train_dates)]
        test_df = df[df["date"] == rebalance_date].copy()

        if train_df.empty or test_df.empty:
            continue

        train_df = _filter_tradeable(train_df, cfg)
        test_tradeable = _filter_tradeable(test_df, cfg)

        if train_df.empty or test_tradeable.empty:
            continue

        # ---- 2. 信号生成：训练 + 预测 ----
        model = build_model(cfg)
        model.fit(train_df[features], train_df[lbl_name])

        if output_dir is not None:
            _save_fold_artifacts(
                model, len(all_results), rebalance_date, train_dates,
                train_df, features, lbl_name, cfg, output_dir,
            )

        test_tradeable["pred_score"] = model.predict(test_tradeable[features])

        # ---- 3. 组合构建：选股 + 成本 ----
        new_holdings, cost_ratio, turnover_ratio = _build_portfolio(
            test_tradeable, prev_holdings, top_k, max_turnover, cost_cfg
        )
        period_costs.append((rebalance_date, cost_ratio, turnover_ratio))
        prev_holdings = new_holdings

        # ---- 标记持仓 & 收集结果 ----
        test_tradeable["pred_rank"] = test_tradeable["pred_score"].rank(ascending=False)
        test_tradeable["selected"] = test_tradeable["code"].isin(new_holdings).astype(int)

        keep = ["date", "code", lbl_name, "pred_score", "pred_rank", "selected"]
        if "raw_pctChg" in test_tradeable.columns:
            keep.append("raw_pctChg")
        if "raw_amount" in test_tradeable.columns:
            keep.append("raw_amount")
        all_results.append(test_tradeable[keep])

        # ---- 4. 分析辅助：SHAP ----
        if return_shap:
            imp = _compute_period_shap(model, test_tradeable, features, rebalance_date)
            if imp is not None:
                shap_records.append(imp)

        # 保存最后一期模型用于实盘
        if i >= len(unique_dates) - step:
            _save_latest_model(model, rebalance_date, cfg)

    if not all_results:
        print("[WARN]  回测无有效调仓期，请检查数据量或 train_window 配置。")
        return pd.DataFrame()

    results_df = pd.concat(all_results, ignore_index=True)

    # 将交易成本附到 results_df 上 (每期一个值，merge 到对应 date)
    cost_df = pd.DataFrame(period_costs, columns=["date", "cost_ratio", "turnover_ratio"])
    results_df = results_df.merge(cost_df, on="date", how="left")

    print(f"[OK] 回测完毕！共 {len(results_df)} 条预测记录。")
    avg_turnover = cost_df["turnover_ratio"].mean() if not cost_df.empty else 0
    avg_cost = cost_df["cost_ratio"].mean() if not cost_df.empty else 0
    print(f"   平均换手率: {avg_turnover:.1%}  |  平均交易成本: {avg_cost:.4%}")

    # 落盘 SHAP 重要性
    if shap_records:
        shap_df = pd.DataFrame(shap_records)
        shap_df.index.name = "date"
        shap_path = cfg.get("analysis", {}).get(
            "shap_output", "data/features/shap_importance.parquet"
        )
        os.makedirs(os.path.dirname(shap_path) or ".", exist_ok=True)
        shap_df.to_parquet(shap_path, engine="pyarrow")
        print(f"[TIP] SHAP 重要性已落盘: {shap_path}  ({shap_df.shape[0]} 期 x {shap_df.shape[1]} 因子)")

    return results_df



def _save_latest_model(model, date, cfg: dict) -> None:
    """保存最新一期模型"""
    model_dir = cfg["paths"]["models"]
    os.makedirs(model_dir, exist_ok=True)
    date_str = pd.to_datetime(date).strftime("%Y%m%d")
    active = cfg["model"]["active"]
    path = os.path.join(model_dir, f"{active}_latest_{date_str}.json")
    if hasattr(model, "save_model"):
        model.save_model(path)
    elif hasattr(model, "booster_"):
        model.booster_.save_model(path)


# ====================================================
# 业绩评价 (v2)
# ====================================================
def _load_benchmark(cfg: dict, rebalance_dates) -> pd.Series | None:
    """加载基准指数收益序列，对齐到调仓日期"""
    etl = cfg["etl"]
    bt = cfg["backtest"]
    bench_code = bt.get("benchmark_code", "sh.000905")
    safe_code = bench_code.replace(".", "_")
    bench_path = os.path.join(etl.get("cache_dir", "data"), f"benchmark_{safe_code}.parquet")

    if not os.path.exists(bench_path):
        # 尝试在线下载
        try:
            from src.data_hub.baostock_client import download_benchmark_index
            bench_df = download_benchmark_index(cfg)
        except Exception as exc:
            logger.warning("基准指数下载失败，将使用等权基准: %s", exc)
            return None
    else:
        bench_df = pd.read_parquet(bench_path)

    if bench_df.empty:
        return None

    bench_df["date"] = pd.to_datetime(bench_df["date"])
    bench_df = bench_df.set_index("date").sort_index()

    # 计算 step 日累积收益，对齐到调仓日
    step = bt["test_step"]
    bench_df["bench_ret"] = bench_df["pctChg"].rolling(step).sum()
    bench_df = bench_df.dropna(subset=["bench_ret"])

    # 只保留调仓日
    rebalance_idx = pd.DatetimeIndex(rebalance_dates)
    common = bench_df.index.intersection(rebalance_idx)
    if common.empty:
        return None

    return bench_df.loc[common, "bench_ret"]


def evaluate(results_df: pd.DataFrame, cfg: dict) -> dict:
    """
    构建扣费后资金曲线，计算年化收益、超额收益、夏普、最大回撤。

    交易成本模型 (v2):
      - 佣金: 万三 (买卖双向)
      - 印花税: 千一 (仅卖出)
      - 冲击成本: 平方根模型
      - 按实际换手率计算，非固定 100%

    基准:
      - 优先使用中证500指数真实收益
      - 若无指数数据，回退到全市场等权收益
    """
    bt = cfg["backtest"]
    lbl = cfg["label"]["name"]
    top_k = bt["top_k"]
    step = bt["test_step"]
    periods_per_year = 252 / step

    # 每期组合毛收益 (只取 selected=1 的持仓)
    if "selected" in results_df.columns:
        held = results_df[results_df["selected"] == 1]
    else:
        held = results_df[results_df["pred_rank"] <= top_k]
    gross_series = held.groupby("date")[lbl].mean()

    # 每期交易成本 (已预计算，每个 date 一个值)
    if "cost_ratio" in results_df.columns:
        cost_per_period = results_df.groupby("date")["cost_ratio"].first()
        cost_per_period = cost_per_period.reindex(gross_series.index, fill_value=0)
    else:
        # 回退到旧模型
        friction = bt.get("friction_cost", 0.0004)
        cost_per_period = pd.Series(friction * 2, index=gross_series.index)

    net_series = gross_series - cost_per_period

    # ---- 基准收益 ----
    bench_series = _load_benchmark(cfg, gross_series.index)
    if bench_series is None:
        # 回退：全市场等权
        bench_series = results_df.groupby("date")[lbl].mean()
        bench_source = "等权基准"
    else:
        bench_series = bench_series.reindex(gross_series.index)
        bench_source = f"指数 ({bt.get('benchmark_code', 'sh.000905')})"

    # NaN 对齐
    common_idx = gross_series.dropna().index.intersection(bench_series.dropna().index)
    net_series = net_series.loc[common_idx]
    bench_series = bench_series.loc[common_idx]

    # ---- 资金曲线 ----
    nav = (1 + net_series).cumprod()
    bench_nav = (1 + bench_series).cumprod()
    excess_series = net_series - bench_series
    excess_nav = (1 + excess_series).cumprod()

    # ---- 年化指标 ----
    n_periods = len(nav)
    final_nav = nav.iloc[-1] if n_periods > 0 else 1.0

    if final_nav > 0 and n_periods > 0:
        ann_return = final_nav ** (periods_per_year / n_periods) - 1
    else:
        ann_return = -1.0

    ann_excess = excess_series.mean() * periods_per_year
    vol = net_series.std() * np.sqrt(periods_per_year)
    excess_vol = excess_series.std() * np.sqrt(periods_per_year)  # 跟踪误差
    sharpe = ann_return / vol if vol > 0 else 0.0
    info_ratio = ann_excess / excess_vol if excess_vol > 0 else 0.0

    # 最大回撤 (策略 NAV)
    drawdown = nav / nav.cummax() - 1
    max_dd = drawdown.min()

    # 超额最大回撤
    excess_dd = excess_nav / excess_nav.cummax() - 1
    excess_max_dd = excess_dd.min()

    # 平均换手与成本
    avg_cost = cost_per_period.mean()
    if "turnover_ratio" in results_df.columns:
        avg_turnover = results_df.groupby("date")["turnover_ratio"].first().mean()
    else:
        avg_turnover = float("nan")

    metrics = {
        "ann_return": ann_return,
        "ann_excess_return": ann_excess,
        "ann_volatility": vol,
        "tracking_error": excess_vol,
        "sharpe_ratio": sharpe,
        "information_ratio": info_ratio,
        "max_drawdown": max_dd,
        "excess_max_drawdown": excess_max_dd,
        "avg_turnover": avg_turnover,
        "avg_cost_per_period": avg_cost,
        "nav": nav,
        "bench_nav": bench_nav,
        "excess_nav": excess_nav,
    }

    print("=" * 50)
    print(f"[STAT] 基准: {bench_source}")
    print("-" * 50)
    print(f"[RET] 年化收益率 (扣费):    {ann_return:.2%}")
    print(f"[RET] 年化超额收益:         {ann_excess:.2%}")
    print(f"[IC] 年化波动率:           {vol:.2%}")
    print(f"[IC] 跟踪误差:             {excess_vol:.2%}")
    print(f"[UP] 夏普比率:             {sharpe:.2f}")
    print(f"[UP] 信息比率:             {info_ratio:.2f}")
    print(f"[IC] 最大回撤:             {max_dd:.2%}")
    print(f"[IC] 超额最大回撤:         {excess_max_dd:.2%}")
    print(f"[TURN] 平均换手率:           {avg_turnover:.1%}")
    print(f"[COST] 平均交易成本/期:      {avg_cost:.4%}")
    print("=" * 50)
    return metrics
