import { useEffect, useState } from 'react';
import { Play, Save, Settings, Brain, FlaskConical, Layers, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { DateRangePicker } from '@/components/DateRangePicker';
import { FactorGroupSelect } from '@/components/FactorGroupSelect';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import {
  useConfigOptions,
  useCreateTask,
  useCrossSectionConfig,
  useETLConfig,
  useFeaturesConfig,
  useModelConfig,
  useBacktestConfig,
  useHPOConfig,
  useStackingConfig,
  useUpdateCrossSectionConfig,
  useUpdateETLConfig,
  useUpdateFeaturesConfig,
  useUpdateModelConfig,
  useUpdateBacktestConfig,
  useUpdateHPOConfig,
  useUpdateStackingConfig,
} from '@/hooks';

// ============================================================
// Model Parameter Defaults (from base_config.yaml)
// ============================================================
const MODEL_DEFAULTS = {
  lightgbm: {
    objective: 'huber',
    boosting_type: 'gbdt',
    n_estimators: 200,
    learning_rate: 0.05,
    early_stopping_round: 50,
    max_depth: 4,
    num_leaves: 12,
    min_child_samples: 800,
    min_child_weight: 0.001,
    min_split_gain: 0.0,
    max_bin: 255,
    min_data_in_bin: 3,
    reg_lambda: 10.0,
    reg_alpha: 1.0,
    path_smooth: 0.0,
    extra_trees: false,
    drop_rate: 0.1,
    max_drop: 50,
    skip_drop: 0.5,
    colsample_bytree: 0.8,
    colsample_bynode: 1.0,
    subsample: 0.8,
    subsample_freq: 1,
    pos_bagging_fraction: 1.0,
    neg_bagging_fraction: 1.0,
    top_rate: 0.2,
    other_rate: 0.1,
    importance_type: 'gain',
    verbose: -1,
    random_state: 42,
    n_jobs: 1,
    force_col_wise: false,
    force_row_wise: false,
  },
  xgboost: {
    objective: 'reg:squarederror',
    n_estimators: 200,
    learning_rate: 0.05,
    early_stopping_rounds: 50,
    max_depth: 4,
    max_leaves: 12,
    grow_policy: 'lossguide',
    min_child_weight: 1.0,
    gamma: 0.1,
    max_delta_step: 0.0,
    max_bin: 256,
    num_parallel_tree: 1,
    reg_lambda: 10.0,
    reg_alpha: 1.0,
    colsample_bytree: 0.8,
    colsample_bylevel: 1.0,
    colsample_bynode: 1.0,
    subsample: 0.8,
    tree_method: 'hist',
    sketch_eps: 0.03,
    sample_type: 'uniform',
    normalize_type: 'tree',
    rate_drop: 0.0,
    one_drop: false,
    skip_drop: 0.0,
    base_score: 0.5,
    random_state: 42,
    n_jobs: 1,
    verbosity: 0,
  },
  random_forest: {
    criterion: 'squared_error',
    n_estimators: 100,
    max_depth: 10,
    min_samples_leaf: 200,
    min_samples_split: 400,
    min_impurity_decrease: 0.0,
    min_weight_fraction_leaf: 0.0,
    max_features: 0.8,
    max_samples: 0.8,
    bootstrap: true,
    oob_score: false,
    ccp_alpha: 0.01,
    warm_start: false,
    random_state: 42,
    n_jobs: 8,
  },
};

type ModelType = 'lightgbm' | 'xgboost' | 'random_forest';

// Parameter field component with default value hint
function ParamField({
  label,
  value,
  defaultValue,
  onChange,
  type = 'number',
  step,
  min,
  max,
  options,
}: {
  label: string;
  value: unknown;
  defaultValue: number | string | boolean;
  onChange: (v: number | string | boolean) => void;
  type?: 'number' | 'select' | 'checkbox';
  step?: number;
  min?: number;
  max?: number;
  options?: string[];
}) {
  const typedValue = value as number | string | boolean;
  const isDefault = typedValue === defaultValue;
  const inputId = label.replace(/\s+/g, '-').toLowerCase();

  return (
    <label className="space-y-1" htmlFor={inputId}>
      <span className={`text-xs font-medium ${isDefault ? 'text-muted-foreground' : 'text-primary'}`}>
        {label}
        {!isDefault && <span className="ml-1 text-[10px]">(modified)</span>}
      </span>
      <span className="text-[10px] text-muted-foreground block">default: {String(defaultValue)}</span>
      {type === 'checkbox' ? (
        <input
          id={inputId}
          type="checkbox"
          checked={value as boolean}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded h-5 w-5"
        />
      ) : type === 'select' ? (
        <select
          id={inputId}
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs"
        >
          {options?.map((o) => (<option key={o} value={o}>{o}</option>))}
        </select>
      ) : (
        <Input
          id={inputId}
          type="number"
          step={step}
          min={min}
          max={max}
          value={value as number}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      )}
    </label>
  );
}

// LightGBM params form
function LightGBMForm({
  params,
  onChange,
  onReset,
}: {
  params: Record<string, unknown>;
  onChange: (k: string, v: number | string | boolean) => void;
  onReset: () => void;
}) {
  const d = MODEL_DEFAULTS.lightgbm;
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h4 className="text-sm font-medium">LightGBM Parameters</h4>
        <Button size="sm" variant="ghost" onClick={onReset}><RotateCcw className="h-3 w-3 mr-1" />Reset</Button>
      </div>
      {/* 迭代 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Iteration</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Objective" value={params.objective ?? d.objective} defaultValue={d.objective} onChange={(v) => onChange('objective', v)} type="select" options={['regression', 'huber', 'fair', 'poisson', 'quantile', 'mape']} />
          <ParamField label="Boosting" value={params.boosting_type ?? d.boosting_type} defaultValue={d.boosting_type} onChange={(v) => onChange('boosting_type', v)} type="select" options={['gbdt', 'dart', 'rf', 'goss']} />
          <ParamField label="N Estimators" value={params.n_estimators ?? d.n_estimators} defaultValue={d.n_estimators} onChange={(v) => onChange('n_estimators', v)} min={10} max={2000} />
          <ParamField label="Learning Rate" value={params.learning_rate ?? d.learning_rate} defaultValue={d.learning_rate} onChange={(v) => onChange('learning_rate', v)} step={0.001} min={0.001} max={0.5} />
          <ParamField label="Early Stop" value={params.early_stopping_round ?? d.early_stopping_round} defaultValue={d.early_stopping_round} onChange={(v) => onChange('early_stopping_round', v)} min={0} />
        </div>
      </div>
      {/* 树结构 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Tree Structure</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Max Depth" value={params.max_depth ?? d.max_depth} defaultValue={d.max_depth} onChange={(v) => onChange('max_depth', v)} min={-1} max={20} />
          <ParamField label="Num Leaves" value={params.num_leaves ?? d.num_leaves} defaultValue={d.num_leaves} onChange={(v) => onChange('num_leaves', v)} min={2} max={256} />
          <ParamField label="Min Child Samples" value={params.min_child_samples ?? d.min_child_samples} defaultValue={d.min_child_samples} onChange={(v) => onChange('min_child_samples', v)} min={1} />
          <ParamField label="Min Child Weight" value={params.min_child_weight ?? d.min_child_weight} defaultValue={d.min_child_weight} onChange={(v) => onChange('min_child_weight', v)} step={0.001} min={0} />
          <ParamField label="Min Split Gain" value={params.min_split_gain ?? d.min_split_gain} defaultValue={d.min_split_gain} onChange={(v) => onChange('min_split_gain', v)} step={0.01} min={0} />
        </div>
      </div>
      {/* 直方图 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Histogram</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Max Bin" value={params.max_bin ?? d.max_bin} defaultValue={d.max_bin} onChange={(v) => onChange('max_bin', v)} min={32} max={1024} />
          <ParamField label="Min Data/Bin" value={params.min_data_in_bin ?? d.min_data_in_bin} defaultValue={d.min_data_in_bin} onChange={(v) => onChange('min_data_in_bin', v)} min={1} />
        </div>
      </div>
      {/* 正则化 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Regularization</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Reg Lambda" value={params.reg_lambda ?? d.reg_lambda} defaultValue={d.reg_lambda} onChange={(v) => onChange('reg_lambda', v)} step={0.1} min={0} />
          <ParamField label="Reg Alpha" value={params.reg_alpha ?? d.reg_alpha} defaultValue={d.reg_alpha} onChange={(v) => onChange('reg_alpha', v)} step={0.1} min={0} />
          <ParamField label="Path Smooth" value={params.path_smooth ?? d.path_smooth} defaultValue={d.path_smooth} onChange={(v) => onChange('path_smooth', v)} step={0.01} min={0} />
          <ParamField label="Extra Trees" value={params.extra_trees ?? d.extra_trees} defaultValue={d.extra_trees} onChange={(v) => onChange('extra_trees', v)} type="checkbox" />
        </div>
      </div>
      {/* 采样 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Sampling</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Colsample Bytree" value={params.colsample_bytree ?? d.colsample_bytree} defaultValue={d.colsample_bytree} onChange={(v) => onChange('colsample_bytree', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Colsample Bynode" value={params.colsample_bynode ?? d.colsample_bynode} defaultValue={d.colsample_bynode} onChange={(v) => onChange('colsample_bynode', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Subsample" value={params.subsample ?? d.subsample} defaultValue={d.subsample} onChange={(v) => onChange('subsample', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Subsample Freq" value={params.subsample_freq ?? d.subsample_freq} defaultValue={d.subsample_freq} onChange={(v) => onChange('subsample_freq', v)} min={0} />
          <ParamField label="Pos Bagging" value={params.pos_bagging_fraction ?? d.pos_bagging_fraction} defaultValue={d.pos_bagging_fraction} onChange={(v) => onChange('pos_bagging_fraction', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Neg Bagging" value={params.neg_bagging_fraction ?? d.neg_bagging_fraction} defaultValue={d.neg_bagging_fraction} onChange={(v) => onChange('neg_bagging_fraction', v)} step={0.05} min={0.1} max={1} />
        </div>
      </div>
      {/* DART */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">DART (boosting_type=dart)</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Drop Rate" value={params.drop_rate ?? d.drop_rate} defaultValue={d.drop_rate} onChange={(v) => onChange('drop_rate', v)} step={0.05} min={0} max={1} />
          <ParamField label="Max Drop" value={params.max_drop ?? d.max_drop} defaultValue={d.max_drop} onChange={(v) => onChange('max_drop', v)} min={1} />
          <ParamField label="Skip Drop" value={params.skip_drop ?? d.skip_drop} defaultValue={d.skip_drop} onChange={(v) => onChange('skip_drop', v)} step={0.05} min={0} max={1} />
        </div>
      </div>
      {/* GOSS */}
      <div>
        <p className="text-xs text-muted-foreground mb-2">GOSS (boosting_type=goss)</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Top Rate" value={params.top_rate ?? d.top_rate} defaultValue={d.top_rate} onChange={(v) => onChange('top_rate', v)} step={0.05} min={0} max={1} />
          <ParamField label="Other Rate" value={params.other_rate ?? d.other_rate} defaultValue={d.other_rate} onChange={(v) => onChange('other_rate', v)} step={0.05} min={0} max={1} />
        </div>
      </div>
    </div>
  );
}

// XGBoost params form
function XGBoostForm({
  params,
  onChange,
  onReset,
}: {
  params: Record<string, unknown>;
  onChange: (k: string, v: number | string | boolean) => void;
  onReset: () => void;
}) {
  const d = MODEL_DEFAULTS.xgboost;
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h4 className="text-sm font-medium">XGBoost Parameters</h4>
        <Button size="sm" variant="ghost" onClick={onReset}><RotateCcw className="h-3 w-3 mr-1" />Reset</Button>
      </div>
      {/* 迭代 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Iteration</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Objective" value={params.objective ?? d.objective} defaultValue={d.objective} onChange={(v) => onChange('objective', v)} type="select" options={['reg:squarederror', 'reg:squaredlogerror', 'reg:pseudohubererror', 'reg:absoluteerror']} />
          <ParamField label="N Estimators" value={params.n_estimators ?? d.n_estimators} defaultValue={d.n_estimators} onChange={(v) => onChange('n_estimators', v)} min={10} max={2000} />
          <ParamField label="Learning Rate" value={params.learning_rate ?? d.learning_rate} defaultValue={d.learning_rate} onChange={(v) => onChange('learning_rate', v)} step={0.001} min={0.001} max={0.5} />
          <ParamField label="Early Stop" value={params.early_stopping_rounds ?? d.early_stopping_rounds} defaultValue={d.early_stopping_rounds} onChange={(v) => onChange('early_stopping_rounds', v)} min={0} />
        </div>
      </div>
      {/* 树结构 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Tree Structure</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Max Depth" value={params.max_depth ?? d.max_depth} defaultValue={d.max_depth} onChange={(v) => onChange('max_depth', v)} min={0} max={20} />
          <ParamField label="Max Leaves" value={params.max_leaves ?? d.max_leaves} defaultValue={d.max_leaves} onChange={(v) => onChange('max_leaves', v)} min={2} max={256} />
          <ParamField label="Grow Policy" value={params.grow_policy ?? d.grow_policy} defaultValue={d.grow_policy} onChange={(v) => onChange('grow_policy', v)} type="select" options={['depthwise', 'lossguide']} />
          <ParamField label="Min Child Weight" value={params.min_child_weight ?? d.min_child_weight} defaultValue={d.min_child_weight} onChange={(v) => onChange('min_child_weight', v)} step={0.1} min={0} />
          <ParamField label="Gamma" value={params.gamma ?? d.gamma} defaultValue={d.gamma} onChange={(v) => onChange('gamma', v)} step={0.01} min={0} />
          <ParamField label="Max Delta Step" value={params.max_delta_step ?? d.max_delta_step} defaultValue={d.max_delta_step} onChange={(v) => onChange('max_delta_step', v)} step={0.1} min={0} />
        </div>
      </div>
      {/* 直方图 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Histogram (tree_method=hist)</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Max Bin" value={params.max_bin ?? d.max_bin} defaultValue={d.max_bin} onChange={(v) => onChange('max_bin', v)} min={32} max={1024} />
          <ParamField label="Parallel Trees" value={params.num_parallel_tree ?? d.num_parallel_tree} defaultValue={d.num_parallel_tree} onChange={(v) => onChange('num_parallel_tree', v)} min={1} />
        </div>
      </div>
      {/* 正则化 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Regularization</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Reg Lambda" value={params.reg_lambda ?? d.reg_lambda} defaultValue={d.reg_lambda} onChange={(v) => onChange('reg_lambda', v)} step={0.1} min={0} />
          <ParamField label="Reg Alpha" value={params.reg_alpha ?? d.reg_alpha} defaultValue={d.reg_alpha} onChange={(v) => onChange('reg_alpha', v)} step={0.1} min={0} />
        </div>
      </div>
      {/* 采样 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Sampling</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Colsample Bytree" value={params.colsample_bytree ?? d.colsample_bytree} defaultValue={d.colsample_bytree} onChange={(v) => onChange('colsample_bytree', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Colsample Bylevel" value={params.colsample_bylevel ?? d.colsample_bylevel} defaultValue={d.colsample_bylevel} onChange={(v) => onChange('colsample_bylevel', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Colsample Bynode" value={params.colsample_bynode ?? d.colsample_bynode} defaultValue={d.colsample_bynode} onChange={(v) => onChange('colsample_bynode', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Subsample" value={params.subsample ?? d.subsample} defaultValue={d.subsample} onChange={(v) => onChange('subsample', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Tree Method" value={params.tree_method ?? d.tree_method} defaultValue={d.tree_method} onChange={(v) => onChange('tree_method', v)} type="select" options={['auto', 'exact', 'approx', 'hist', 'gpu_hist']} />
          <ParamField label="Sketch Eps" value={params.sketch_eps ?? d.sketch_eps} defaultValue={d.sketch_eps} onChange={(v) => onChange('sketch_eps', v)} step={0.001} min={0.001} max={0.1} />
        </div>
      </div>
      {/* DART */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">DART (booster=dart)</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Sample Type" value={params.sample_type ?? d.sample_type} defaultValue={d.sample_type} onChange={(v) => onChange('sample_type', v)} type="select" options={['uniform', 'weighted']} />
          <ParamField label="Normalize Type" value={params.normalize_type ?? d.normalize_type} defaultValue={d.normalize_type} onChange={(v) => onChange('normalize_type', v)} type="select" options={['tree', 'forest']} />
          <ParamField label="Rate Drop" value={params.rate_drop ?? d.rate_drop} defaultValue={d.rate_drop} onChange={(v) => onChange('rate_drop', v)} step={0.05} min={0} max={1} />
          <ParamField label="One Drop" value={params.one_drop ?? d.one_drop} defaultValue={d.one_drop} onChange={(v) => onChange('one_drop', v)} type="checkbox" />
          <ParamField label="Skip Drop" value={params.skip_drop ?? d.skip_drop} defaultValue={d.skip_drop} onChange={(v) => onChange('skip_drop', v)} step={0.05} min={0} max={1} />
        </div>
      </div>
      {/* 其他 */}
      <div>
        <p className="text-xs text-muted-foreground mb-2">Other</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Base Score" value={params.base_score ?? d.base_score} defaultValue={d.base_score} onChange={(v) => onChange('base_score', v)} step={0.1} min={0} max={1} />
          <ParamField label="N Jobs" value={params.n_jobs ?? d.n_jobs} defaultValue={d.n_jobs} onChange={(v) => onChange('n_jobs', v)} min={-1} max={16} />
          <ParamField label="Verbosity" value={params.verbosity ?? d.verbosity} defaultValue={d.verbosity} onChange={(v) => onChange('verbosity', v)} min={0} max={3} />
        </div>
      </div>
    </div>
  );
}

// Random Forest params form
function RandomForestForm({
  params,
  onChange,
  onReset,
}: {
  params: Record<string, unknown>;
  onChange: (k: string, v: number | string | boolean) => void;
  onReset: () => void;
}) {
  const d = MODEL_DEFAULTS.random_forest;
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h4 className="text-sm font-medium">Random Forest Parameters</h4>
        <Button size="sm" variant="ghost" onClick={onReset}><RotateCcw className="h-3 w-3 mr-1" />Reset</Button>
      </div>
      {/* 基础 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Basic</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Criterion" value={params.criterion ?? d.criterion} defaultValue={d.criterion} onChange={(v) => onChange('criterion', v)} type="select" options={['squared_error', 'absolute_error', 'friedman_mse', 'poisson']} />
          <ParamField label="N Estimators" value={params.n_estimators ?? d.n_estimators} defaultValue={d.n_estimators} onChange={(v) => onChange('n_estimators', v)} min={10} max={1000} />
        </div>
      </div>
      {/* 树结构 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Tree Structure</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Max Depth" value={params.max_depth ?? d.max_depth} defaultValue={d.max_depth} onChange={(v) => onChange('max_depth', v)} min={1} max={50} />
          <ParamField label="Min Samples Leaf" value={params.min_samples_leaf ?? d.min_samples_leaf} defaultValue={d.min_samples_leaf} onChange={(v) => onChange('min_samples_leaf', v)} min={1} />
          <ParamField label="Min Samples Split" value={params.min_samples_split ?? d.min_samples_split} defaultValue={d.min_samples_split} onChange={(v) => onChange('min_samples_split', v)} min={2} />
          <ParamField label="Min Impurity Decr" value={params.min_impurity_decrease ?? d.min_impurity_decrease} defaultValue={d.min_impurity_decrease} onChange={(v) => onChange('min_impurity_decrease', v)} step={0.001} min={0} />
          <ParamField label="Min Weight Frac" value={params.min_weight_fraction_leaf ?? d.min_weight_fraction_leaf} defaultValue={d.min_weight_fraction_leaf} onChange={(v) => onChange('min_weight_fraction_leaf', v)} step={0.01} min={0} max={0.5} />
        </div>
      </div>
      {/* 采样 */}
      <div className="border-b pb-3 mb-3">
        <p className="text-xs text-muted-foreground mb-2">Sampling</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="Max Features" value={params.max_features ?? d.max_features} defaultValue={d.max_features} onChange={(v) => onChange('max_features', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Max Samples" value={params.max_samples ?? d.max_samples} defaultValue={d.max_samples} onChange={(v) => onChange('max_samples', v)} step={0.05} min={0.1} max={1} />
          <ParamField label="Bootstrap" value={params.bootstrap ?? d.bootstrap} defaultValue={d.bootstrap} onChange={(v) => onChange('bootstrap', v)} type="checkbox" />
          <ParamField label="OOB Score" value={params.oob_score ?? d.oob_score} defaultValue={d.oob_score} onChange={(v) => onChange('oob_score', v)} type="checkbox" />
        </div>
      </div>
      {/* 正则化 & 其他 */}
      <div>
        <p className="text-xs text-muted-foreground mb-2">Regularization & Other</p>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <ParamField label="CCP Alpha" value={params.ccp_alpha ?? d.ccp_alpha} defaultValue={d.ccp_alpha} onChange={(v) => onChange('ccp_alpha', v)} step={0.001} min={0} />
          <ParamField label="Warm Start" value={params.warm_start ?? d.warm_start} defaultValue={d.warm_start} onChange={(v) => onChange('warm_start', v)} type="checkbox" />
          <ParamField label="N Jobs" value={params.n_jobs ?? d.n_jobs} defaultValue={d.n_jobs} onChange={(v) => onChange('n_jobs', v)} min={-1} max={16} />
        </div>
      </div>
    </div>
  );
}

export function ConfigPanel() {
  // Config queries
  const { data: etlConfig, isLoading: etlLoading } = useETLConfig();
  const { data: featuresConfig, isLoading: featuresLoading } = useFeaturesConfig();
  const { data: crossSectionConfig, isLoading: crossSectionLoading } = useCrossSectionConfig();
  const { data: modelConfig, isLoading: modelLoading } = useModelConfig();
  const { data: backtestConfig, isLoading: backtestLoading } = useBacktestConfig();
  const { data: hpoConfig, isLoading: hpoLoading } = useHPOConfig();
  const { data: stackingConfig, isLoading: stackingLoading } = useStackingConfig();
  const { data: options } = useConfigOptions();

  // Mutations
  const updateETL = useUpdateETLConfig();
  const updateFeatures = useUpdateFeaturesConfig();
  const updateCrossSection = useUpdateCrossSectionConfig();
  const updateModel = useUpdateModelConfig();
  const updateBacktest = useUpdateBacktestConfig();
  const updateHPO = useUpdateHPOConfig();
  const updateStacking = useUpdateStackingConfig();
  const createTask = useCreateTask();

  // ETL state
  const [indexName, setIndexName] = useState('zz500');
  const [maxStocks, setMaxStocks] = useState(0);
  const [startDate, setStartDate] = useState('2016-01-01');
  const [endDate, setEndDate] = useState('2026-03-29');

  // Features state
  const [activeFactors, setActiveFactors] = useState<string[]>([]);

  // CrossSection state
  const [madMultiplier, setMadMultiplier] = useState(3.148);
  const [minIndustryStocks, setMinIndustryStocks] = useState(5);
  const [zscoreEps, setZscoreEps] = useState(1e-8);

  // Model state - each model has its own params object
  const [activeModel, setActiveModel] = useState<ModelType>('lightgbm');
  const [lightgbmParams, setLightgbmParams] = useState<Record<string, unknown>>({ ...MODEL_DEFAULTS.lightgbm });
  const [xgboostParams, setXgboostParams] = useState<Record<string, unknown>>({ ...MODEL_DEFAULTS.xgboost });
  const [randomForestParams, setRandomForestParams] = useState<Record<string, unknown>>({ ...MODEL_DEFAULTS.random_forest });

  // Backtest state
  const [trainWindow, setTrainWindow] = useState(500);
  const [gap, setGap] = useState(5);
  const [testStep, setTestStep] = useState(5);
  const [topK, setTopK] = useState(30);
  const [frictionCost, setFrictionCost] = useState(0.0004);

  // HPO state
  const [hpoEnabled, setHpoEnabled] = useState(false);
  const [nTrials, setNTrials] = useState(50);
  const [objectiveMetric, setObjectiveMetric] = useState('sharpe_ratio');

  // Stacking state
  const [stackingEnabled, setStackingEnabled] = useState(false);
  const [baseLearners, setBaseLearners] = useState<string[]>(['lightgbm', 'xgboost']);
  const [metaLearner, setMetaLearner] = useState('weight_averaging');

  // Initialize from loaded configs
  useEffect(() => {
    if (!etlConfig) return;
    setIndexName(etlConfig.index_name);
    setMaxStocks(etlConfig.max_stocks);
    setStartDate(etlConfig.start_date);
    setEndDate(etlConfig.end_date);
  }, [etlConfig]);

  useEffect(() => {
    if (!featuresConfig) return;
    setActiveFactors(featuresConfig.active_factors);
  }, [featuresConfig]);

  useEffect(() => {
    if (!crossSectionConfig) return;
    setMadMultiplier(crossSectionConfig.mad_multiplier);
    setMinIndustryStocks(crossSectionConfig.min_industry_stocks);
    setZscoreEps(crossSectionConfig.zscore_eps);
  }, [crossSectionConfig]);

  useEffect(() => {
    if (!modelConfig) return;
    setActiveModel(modelConfig.active as ModelType);
    // Load all model params from config
    if (modelConfig.lightgbm) {
      setLightgbmParams({ ...MODEL_DEFAULTS.lightgbm, ...modelConfig.lightgbm });
    }
    if (modelConfig.xgboost) {
      setXgboostParams({ ...MODEL_DEFAULTS.xgboost, ...modelConfig.xgboost });
    }
    if (modelConfig.random_forest) {
      setRandomForestParams({ ...MODEL_DEFAULTS.random_forest, ...modelConfig.random_forest });
    }
  }, [modelConfig]);

  useEffect(() => {
    if (!backtestConfig) return;
    setTrainWindow(backtestConfig.train_window);
    setGap(backtestConfig.gap);
    setTestStep(backtestConfig.test_step);
    setTopK(backtestConfig.top_k);
    setFrictionCost(backtestConfig.friction_cost);
  }, [backtestConfig]);

  useEffect(() => {
    if (!hpoConfig) return;
    setHpoEnabled(hpoConfig.enabled);
    setNTrials(hpoConfig.n_trials);
    setObjectiveMetric(hpoConfig.objective_metric);
  }, [hpoConfig]);

  useEffect(() => {
    if (!stackingConfig) return;
    setStackingEnabled(stackingConfig.enabled);
    setBaseLearners(stackingConfig.base_learners);
    setMetaLearner(stackingConfig.meta_learner);
  }, [stackingConfig]);

  const isLoading = etlLoading || featuresLoading || crossSectionLoading || modelLoading || backtestLoading || hpoLoading || stackingLoading;
  const isSaving = updateETL.isPending || updateFeatures.isPending || updateCrossSection.isPending || updateModel.isPending || updateBacktest.isPending || updateHPO.isPending || updateStacking.isPending;

  const handleSaveData = async () => {
    try {
      await Promise.all([
        updateETL.mutateAsync({ index_name: indexName, max_stocks: Number(maxStocks), start_date: startDate, end_date: endDate }),
        updateFeatures.mutateAsync({ active_factors: activeFactors }),
        updateCrossSection.mutateAsync({ mad_multiplier: Number(madMultiplier), min_industry_stocks: Number(minIndustryStocks), zscore_eps: Number(zscoreEps) }),
      ]);
      toast.success('Data configuration saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    }
  };

  const handleSaveModel = async () => {
    try {
      await updateModel.mutateAsync({
        active: activeModel,
        lightgbm: lightgbmParams,
        xgboost: xgboostParams,
        random_forest: randomForestParams,
      });
      toast.success('Model configuration saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    }
  };

  const handleSaveBacktest = async () => {
    try {
      await updateBacktest.mutateAsync({
        train_window: Number(trainWindow),
        gap: Number(gap),
        test_step: Number(testStep),
        top_k: Number(topK),
        friction_cost: Number(frictionCost),
      });
      toast.success('Backtest configuration saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    }
  };

  const handleSaveHPO = async () => {
    try {
      await updateHPO.mutateAsync({
        enabled: hpoEnabled,
        n_trials: Number(nTrials),
        objective_metric: objectiveMetric,
      });
      toast.success('HPO configuration saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    }
  };

  const handleSaveStacking = async () => {
    try {
      await updateStacking.mutateAsync({
        enabled: stackingEnabled,
        base_learners: baseLearners,
        meta_learner: metaLearner,
      });
      toast.success('Stacking configuration saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    }
  };

  const handleDataUpdate = () => {
    createTask.mutate(
      { task_type: 'data_update', notes: 'Submitted from UI' },
      { onSuccess: (result) => toast.success(`Task created: ${result.task_id}`), onError: (error) => toast.error(error.message) }
    );
  };

  const toggleBaseLearner = (model: string) => {
    setBaseLearners((prev) => (prev.includes(model) ? prev.filter((m) => m !== model) : [...prev, model]));
  };

  // Model param handlers
  const handleModelParamChange = (model: ModelType, key: string, value: number | string | boolean) => {
    if (model === 'lightgbm') {
      setLightgbmParams((prev) => ({ ...prev, [key]: value }));
    } else if (model === 'xgboost') {
      setXgboostParams((prev) => ({ ...prev, [key]: value }));
    } else if (model === 'random_forest') {
      setRandomForestParams((prev) => ({ ...prev, [key]: value }));
    }
  };

  const handleResetModelParams = (model: ModelType) => {
    if (model === 'lightgbm') {
      setLightgbmParams({ ...MODEL_DEFAULTS.lightgbm });
    } else if (model === 'xgboost') {
      setXgboostParams({ ...MODEL_DEFAULTS.xgboost });
    } else if (model === 'random_forest') {
      setRandomForestParams({ ...MODEL_DEFAULTS.random_forest });
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center h-32">
          <span className="text-muted-foreground">Loading configuration...</span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-foreground/10 bg-gradient-to-br from-card to-muted/30">
      <CardHeader>
        <CardTitle>Configuration</CardTitle>
        <CardDescription>Edit research parameters and trigger tasks</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="data" className="space-y-4">
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="data" className="text-xs"><Settings className="h-3 w-3 mr-1" />Data</TabsTrigger>
            <TabsTrigger value="model" className="text-xs"><Brain className="h-3 w-3 mr-1" />Model</TabsTrigger>
            <TabsTrigger value="backtest" className="text-xs"><FlaskConical className="h-3 w-3 mr-1" />Backtest</TabsTrigger>
            <TabsTrigger value="hpo" className="text-xs">HPO</TabsTrigger>
            <TabsTrigger value="stacking" className="text-xs"><Layers className="h-3 w-3 mr-1" />Stacking</TabsTrigger>
          </TabsList>

          {/* Data Tab */}
          <TabsContent value="data" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <div className="grid gap-3 grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Universe</span>
                    <Select value={indexName} onChange={(e) => setIndexName(e.target.value)}>
                      {(options?.available_indices ?? []).map((i) => (<option key={i} value={i}>{i}</option>))}
                    </Select>
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Max stocks</span>
                    <Input type="number" min={0} value={maxStocks} onChange={(e) => setMaxStocks(Number(e.target.value))} />
                  </label>
                </div>
                <DateRangePicker startDate={startDate} endDate={endDate} onStartDateChange={setStartDate} onEndDateChange={setEndDate} />
              </div>
              <div className="space-y-3">
                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground">Factor groups</p>
                  <FactorGroupSelect options={options?.available_factor_groups ?? []} value={activeFactors} onChange={setActiveFactors} />
                </div>
                <div className="grid gap-3 grid-cols-3">
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">MAD</span>
                    <Input type="number" step="0.001" value={madMultiplier} onChange={(e) => setMadMultiplier(Number(e.target.value))} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Ind. min</span>
                    <Input type="number" min={1} value={minIndustryStocks} onChange={(e) => setMinIndustryStocks(Number(e.target.value))} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Z-eps</span>
                    <Input type="number" step="1e-9" value={zscoreEps} onChange={(e) => setZscoreEps(Number(e.target.value))} />
                  </label>
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSaveData} disabled={isSaving}><Save className="h-3 w-3 mr-1" />Save</Button>
              <Button size="sm" variant="outline" onClick={handleDataUpdate} disabled={createTask.isPending}><Play className="h-3 w-3 mr-1" />Update Data</Button>
            </div>
          </TabsContent>

          {/* Model Tab - Dynamic based on selected model */}
          <TabsContent value="model" className="space-y-4">
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">Active Model</span>
                  <Select value={activeModel} onChange={(e) => setActiveModel(e.target.value as ModelType)}>
                    {(options?.available_models ?? []).map((m) => (<option key={m} value={m}>{m}</option>))}
                  </Select>
                </label>
                <div className="flex-1" />
                <Badge variant="outline">{activeModel}</Badge>
              </div>

              {activeModel === 'lightgbm' && (
                <LightGBMForm
                  params={lightgbmParams}
                  onChange={(k, v) => handleModelParamChange('lightgbm', k, v)}
                  onReset={() => handleResetModelParams('lightgbm')}
                />
              )}

              {activeModel === 'xgboost' && (
                <XGBoostForm
                  params={xgboostParams}
                  onChange={(k, v) => handleModelParamChange('xgboost', k, v)}
                  onReset={() => handleResetModelParams('xgboost')}
                />
              )}

              {activeModel === 'random_forest' && (
                <RandomForestForm
                  params={randomForestParams}
                  onChange={(k, v) => handleModelParamChange('random_forest', k, v)}
                  onReset={() => handleResetModelParams('random_forest')}
                />
              )}

              <div className="p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
                <p><strong>Note:</strong> Parameters with "(modified)" tag differ from defaults.</p>
                <p>Click <strong>Reset</strong> to restore default values for the current model.</p>
              </div>
            </div>
            <Button size="sm" onClick={handleSaveModel} disabled={isSaving}><Save className="h-3 w-3 mr-1" />Save Model Config</Button>
          </TabsContent>

          {/* Backtest Tab */}
          <TabsContent value="backtest" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <h4 className="text-sm font-medium">Walk-Forward Parameters</h4>
                <div className="grid gap-3 grid-cols-3">
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Train Window</span>
                    <Input type="number" min={50} value={trainWindow} onChange={(e) => setTrainWindow(Number(e.target.value))} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Gap</span>
                    <Input type="number" min={1} value={gap} onChange={(e) => setGap(Number(e.target.value))} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Test Step</span>
                    <Input type="number" min={1} value={testStep} onChange={(e) => setTestStep(Number(e.target.value))} />
                  </label>
                </div>
              </div>
              <div className="space-y-3">
                <h4 className="text-sm font-medium">Trading Parameters</h4>
                <div className="grid gap-3 grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Top K Stocks</span>
                    <Input type="number" min={1} max={100} value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Friction Cost</span>
                    <Input type="number" step="0.0001" min={0} max={0.01} value={frictionCost} onChange={(e) => setFrictionCost(Number(e.target.value))} />
                  </label>
                </div>
                <p className="text-xs text-muted-foreground">Friction cost: {frictionCost} = {(frictionCost * 10000).toFixed(1)} bps</p>
              </div>
            </div>
            <Button size="sm" onClick={handleSaveBacktest} disabled={isSaving}><Save className="h-3 w-3 mr-1" />Save Backtest Config</Button>
          </TabsContent>

          {/* HPO Tab */}
          <TabsContent value="hpo" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={hpoEnabled} onChange={(e) => setHpoEnabled(e.target.checked)} className="rounded" />
                  <span className="text-sm font-medium">Enable HPO</span>
                </label>
                <div className="grid gap-3 grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">N Trials</span>
                    <Input type="number" min={1} max={500} value={nTrials} onChange={(e) => setNTrials(Number(e.target.value))} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">Objective</span>
                    <Select value={objectiveMetric} onChange={(e) => setObjectiveMetric(e.target.value)}>
                      {(options?.objective_metrics ?? []).map((m) => (<option key={m} value={m}>{m}</option>))}
                    </Select>
                  </label>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
                <p><strong>HPO</strong> = Hyperparameter Optimization</p>
                <p>Uses Optuna TPE sampler to find best parameters</p>
                <p className="mt-2"><strong>Objective metrics:</strong></p>
                <ul className="list-disc list-inside">
                  <li>sharpe_ratio - Risk-adjusted return</li>
                  <li>ic_mean - Average Information Coefficient</li>
                  <li>icir - IC Information Ratio</li>
                </ul>
              </div>
            </div>
            <Button size="sm" onClick={handleSaveHPO} disabled={isSaving}><Save className="h-3 w-3 mr-1" />Save HPO Config</Button>
          </TabsContent>

          {/* Stacking Tab */}
          <TabsContent value="stacking" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={stackingEnabled} onChange={(e) => setStackingEnabled(e.target.checked)} className="rounded" />
                  <span className="text-sm font-medium">Enable Stacking</span>
                </label>
                <div className="space-y-2">
                  <span className="text-xs font-medium text-muted-foreground">Base Learners</span>
                  <div className="flex flex-wrap gap-2">
                    {(options?.available_models ?? []).map((m) => (
                      <Badge
                        key={m}
                        variant={baseLearners.includes(m) ? 'default' : 'outline'}
                        className="cursor-pointer"
                        onClick={() => toggleBaseLearner(m)}
                      >
                        {m}
                      </Badge>
                    ))}
                  </div>
                </div>
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">Meta Learner</span>
                  <Select value={metaLearner} onChange={(e) => setMetaLearner(e.target.value)}>
                    {(options?.meta_learner_types ?? []).map((t) => (<option key={t} value={t}>{t}</option>))}
                  </Select>
                </label>
              </div>
              <div className="p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
                <p><strong>Stacking</strong> = Ensemble learning</p>
                <p>Combines multiple models for better predictions</p>
                <p className="mt-2"><strong>Meta learners:</strong></p>
                <ul className="list-disc list-inside">
                  <li>weight_averaging - IC-weighted average</li>
                  <li>linear - Ridge regression</li>
                </ul>
              </div>
            </div>
            <Button size="sm" onClick={handleSaveStacking} disabled={isSaving}><Save className="h-3 w-3 mr-1" />Save Stacking Config</Button>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
