"""
标签生成器 -- 生成预测目标 label_*
铁律二：列名带 label_ 前缀
"""
import pandas as pd


def generate_labels(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """按 config 中的 label 配置生成预测标签"""
    lbl_cfg = cfg["label"]
    name = lbl_cfg["name"]       # e.g. label_5d_ret
    horizon = lbl_cfg["horizon"]  # e.g. 5

    print(f"[TAG] 正在生成预测目标 ({name}, 未来 {horizon} 天收益)...", flush=True)

    if lbl_cfg["method"] == "pctChg_sum":
        shifted = df.groupby("code", sort=False)["raw_pctChg"].shift(-horizon)
        label_values = (
            shifted.groupby(df["code"], sort=False)
            .rolling(horizon)
            .sum()
            .reset_index(level=0, drop=True)
        )
    elif lbl_cfg["method"] == "close_ratio":
        future_close = df.groupby("code", sort=False)["raw_close"].shift(-horizon)
        label_values = future_close.div(df["raw_close"]).sub(1.0)
    else:
        raise ValueError(f"不支持的 label method: {lbl_cfg['method']}")

    # 截面处理阶段会频繁逐列赋值，这里用 concat 重新组装一次以避免
    # 最后一列标签插入时触发 DataFrame 高碎片度告警。
    df = pd.concat([df, label_values.rename(name)], axis=1, copy=False)

    before = len(df)
    df = df.dropna(subset=[name]).reset_index(drop=True)
    print(f"  清理无标签行: {before} -> {len(df)}", flush=True)
    return df
