"""
Session D - Pipeline Verification Script
Verify: feature_wide -> label_wide -> train -> backtest chain
"""
import sys, os, time
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

from src.config_loader import load_config
from src.data_layer import FeatureStore, LabelStore, DatasetBuilder
from src.ml_core.backtest import run_walk_forward, evaluate
from src.experiment_store import ExperimentStore, build_holdings_from_predictions, build_nav_from_metrics
from src.runtime_modes import apply_runtime_mode_to_config
import pandas as pd

def main():
    t_start = time.time()
    cfg = load_config()
    print('[1/6] Config loaded')

    # Step 1: Check stores
    feature_store = FeatureStore.from_config(cfg)
    label_store = LabelStore.from_config(cfg)
    print(f'[2/6] FeatureStore exists={feature_store.exists}, LabelStore exists={label_store.exists}')

    # Step 2: Build dataset (skip_pair_validation -- date gaps are known/documented)
    builder = DatasetBuilder.from_config(cfg)
    df = builder.build_train_dataset(
        label_name=cfg['label']['name'],
        skip_pair_validation=True,
    )
    print(f'[3/6] Dataset built: {df.shape[0]:,} rows x {df.shape[1]} cols')
    print(f'       Date range: {df["date"].min()} ~ {df["date"].max()}')
    print(f'       Codes: {df["code"].nunique()}, Features: {len([c for c in df.columns if c.startswith("feat_")])}')

    runtime_plan = df.attrs.get('dataset_runtime_plan', {})
    run_cfg = apply_runtime_mode_to_config(cfg, runtime_plan.get('mode', 'formal'), runtime_plan)

    # Step 3: Run backtest
    features = [c for c in df.columns if c.startswith('feat_')]
    print(f'[4/6] Starting Walk-Forward Backtest ({len(features)} features)...')
    t_bt = time.time()
    results = run_walk_forward(df, features, run_cfg, output_dir='data/results/qa/pipeline_verify_20260428')
    print(f'       Backtest done in {time.time()-t_bt:.1f}s, {len(results)} rows')

    # Step 4: Evaluate
    print('[5/6] Computing metrics...')
    metrics = evaluate(results, run_cfg)
    print(f'       Metrics computed: {len(metrics)} metrics')

    # Step 5: Save results
    print('[6/6] Saving results...')
    exp_store = ExperimentStore('data/results/qa/pipeline_verify_20260428', cfg=run_cfg)
    exp_store.register_run(run_cfg)

    if not results.empty:
        exp_store.save_predictions(results)
        holdings_df = build_holdings_from_predictions(results, cfg['backtest']['top_k'])
        exp_store.save_holdings(holdings_df)
        nav_df = build_nav_from_metrics(metrics, results)
        if not nav_df.empty:
            exp_store.save_nav(nav_df)
        exp_store.save_metrics(metrics)
        exp_store.save_config(run_cfg)
        exp_store.finish_run('done')
    else:
        exp_store.finish_run('empty')

    total = time.time() - t_start
    print(f'\n=== VERIFICATION COMPLETE in {total:.1f}s ===')
    print(f'Results: {len(results)} rows, {len(results.columns)} cols')
    print(f'Predictions date range: {results["date"].min()} ~ {results["date"].max()}')

    # Print key metrics
    print('\n--- Key Metrics ---')
    key_metrics = ['sharpe_ratio', 'annual_return', 'max_drawdown', 'win_rate',
                   'total_return', 'ic_mean', 'icir']
    for k in key_metrics:
        if k in metrics and isinstance(metrics[k], (int, float)):
            print(f'  {k}: {metrics[k]:.4f}')

    return results, metrics

if __name__ == '__main__':
    main()
