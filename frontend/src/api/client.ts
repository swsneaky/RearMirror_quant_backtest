const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const errorBody = await res.text().catch(() => '');
    throw new Error(`API Error: ${res.status} ${path} - ${errorBody}`);
  }
  return res.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const errorBody = await res.text().catch(() => '');
    throw new Error(`API Error: ${res.status} ${path} - ${errorBody}`);
  }
  return res.json();
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errorBody = await res.text().catch(() => '');
    throw new Error(`API Error: ${res.status} ${path} - ${errorBody}`);
  }
  return res.json();
}

export interface LayerStatus {
  layer_name: string;
  output_exists: boolean;
  fingerprint_exists: boolean;
  upstream_changed: boolean;
  config_changed: boolean;
  needs_update: boolean;
  reason: string;
}

export interface LayersResponse {
  layers: Record<string, LayerStatus>;
  summary: {
    total_layers: number;
    needs_update: number;
    all_up_to_date: boolean;
  };
}

export interface CacheStats {
  path: string;
  exists: boolean;
  file_count: number;
  total_size: number;
  total_size_human: string;
  fingerprint: string;
}

export interface HPOStatus {
  study_name: string;
  status: string;
  current_trial: number;
  total_trials: number;
  best_value: number | null;
  elapsed_seconds: number;
  model: string;
  objective_metric: string;
}

export interface HPOStatusResponse {
  status: HPOStatus;
  available_studies: string[];
}

export interface HPOTrial {
  number: number;
  state: string;
  value: number | null;
  params: Record<string, number>;
  duration_seconds?: number;
}

// ================================================================
// Backtest Types
// ================================================================
export interface BacktestMetrics {
  ann_return: number;
  ann_excess_return: number;
  ann_volatility: number;
  tracking_error: number;
  sharpe_ratio: number;
  information_ratio: number;
  max_drawdown: number;
  excess_max_drawdown: number;
  avg_turnover: number;
  avg_cost_per_period: number;
}

export interface BacktestResultsResponse {
  metrics: BacktestMetrics | null;
  has_results: boolean;
  results_path: string;
}

export interface NavDataPoint {
  date: string;
  strategy_nav: number;
  benchmark_nav: number;
  excess_nav: number;
}

export interface NavResponse {
  nav: NavDataPoint[];
}

// Legacy type for backwards compatibility
export interface BacktestResult {
  iteration_id: string;
  status: string;
  metrics: Record<string, number>;
}

// ================================================================
// Dashboard Types
// ================================================================
export interface IterationsSummary {
  total: number;
}

export interface HPOSummary {
  status: string;
  current_trial: number;
  total_trials: number;
  best_value: number | null;
  study_name: string | null;
}

export interface BacktestSummary {
  has_results: boolean;
  sharpe_ratio: number | null;
  ann_return: number | null;
  max_drawdown: number | null;
}

export interface DataLayersSummary {
  total: number;
  needs_update: number;
}

export interface ModelsSummary {
  total: number;
  by_status: Record<string, number>;
}

export interface TasksSummary {
  total: number;
  by_status: Record<string, number>;
}

export interface StocksSummary {
  total: number;
  total_bars: number;
}

export interface DashboardSummaryResponse {
  iterations: IterationsSummary;
  hpo: HPOSummary;
  backtest: BacktestSummary;
  data_layers: DataLayersSummary;
  models: ModelsSummary;
  tasks: TasksSummary;
  stocks: StocksSummary;
}

// ================================================================
// Factor Analysis Types
// ================================================================
export interface FactorSummary {
  factor_name: string;
  ic_mean: number;
  ic_std: number;
  icir: number;
  positive_ratio: number;
  monotonicity: number;
}

export interface FactorSummaryResponse {
  factors: FactorSummary[];
}

export interface ICDataPoint {
  date: string;
  ic: number;
}

export interface FactorICSeriesResponse {
  factor_name: string;
  ic_series: ICDataPoint[];
}

export interface FactorCorrelationResponse {
  factor_names: string[];
  correlation_matrix: number[][];
}

// ================================================================
// Config Types
// ================================================================
export interface ETLConfig {
  index_name: string;
  start_date: string;
  end_date: string;
  max_stocks: number;
  update_mode: string;
  available_indices: string[];
}

export interface ETLConfigUpdate {
  index_name?: string;
  start_date?: string;
  end_date?: string;
  max_stocks?: number;
  update_mode?: string;
}

export interface FeaturesConfig {
  active_factors: string[];
  excluded_features: string[];
  available_factor_groups: string[];
}

export interface FeaturesConfigUpdate {
  active_factors?: string[];
  excluded_features?: string[];
}

export interface CrossSectionConfig {
  mad_multiplier: number;
  min_industry_stocks: number;
  zscore_eps: number;
}

export interface CrossSectionConfigUpdate {
  mad_multiplier?: number;
  min_industry_stocks?: number;
  zscore_eps?: number;
}

// ================================================================
// Model Config Types
// ================================================================
export interface LightGBMConfig {
  // 损失函数 & 迭代
  objective: string;
  boosting_type: string;
  n_estimators: number;
  learning_rate: number;
  early_stopping_round: number | null;
  // 树结构
  max_depth: number;
  num_leaves: number;
  min_child_samples: number;
  min_child_weight: number;
  min_split_gain: number;
  // 直方图
  max_bin: number;
  min_data_in_bin: number;
  // 正则化
  reg_lambda: number;
  reg_alpha: number;
  path_smooth: number;
  extra_trees: boolean;
  // DART
  drop_rate: number;
  max_drop: number;
  skip_drop: number;
  // 采样
  colsample_bytree: number;
  colsample_bynode: number;
  subsample: number;
  subsample_freq: number;
  pos_bagging_fraction: number;
  neg_bagging_fraction: number;
  // GOSS
  top_rate: number;
  other_rate: number;
  // 其他
  importance_type: string;
  verbose: number;
  random_state: number;
  n_jobs: number;
  force_col_wise: boolean;
  force_row_wise: boolean;
}

export interface XGBoostConfig {
  // 损失函数 & 迭代
  objective: string;
  n_estimators: number;
  learning_rate: number;
  early_stopping_rounds: number | null;
  // 树结构
  max_depth: number;
  max_leaves: number;
  grow_policy: string;
  min_child_weight: number;
  gamma: number;
  max_delta_step: number;
  // 直方图
  max_bin: number;
  num_parallel_tree: number;
  // 正则化
  reg_lambda: number;
  reg_alpha: number;
  // 采样
  colsample_bytree: number;
  colsample_bylevel: number;
  colsample_bynode: number;
  subsample: number;
  tree_method: string;
  // 稀疏数据
  sketch_eps: number;
  // DART
  sample_type: string;
  normalize_type: string;
  rate_drop: number;
  one_drop: boolean;
  skip_drop: number;
  // 单调约束
  monotone_constraints: number[] | null;
  interaction_constraints: number[] | null;
  // 其他
  base_score: number;
  random_state: number;
  n_jobs: number;
  verbosity: number;
}

export interface RandomForestConfig {
  // 损失函数 & 基础
  criterion: string;
  n_estimators: number;
  // 树结构
  max_depth: number;
  min_samples_leaf: number;
  min_samples_split: number;
  min_impurity_decrease: number;
  min_weight_fraction_leaf: number;
  // 采样
  max_features: number;
  max_samples: number;
  bootstrap: boolean;
  oob_score: boolean;
  // 正则化
  ccp_alpha: number;
  // 其他
  warm_start: boolean;
  random_state: number;
  n_jobs: number;
}

export interface ModelConfig {
  active: string;
  lightgbm: LightGBMConfig;
  xgboost: XGBoostConfig;
  random_forest: RandomForestConfig;
}

export interface ModelConfigUpdate {
  active?: string;
  lightgbm?: Partial<LightGBMConfig>;
  xgboost?: Partial<XGBoostConfig>;
  random_forest?: Partial<RandomForestConfig>;
}

// ================================================================
// Backtest Config Types
// ================================================================
export interface BacktestConfig {
  train_window: number;
  gap: number;
  test_step: number;
  top_k: number;
  friction_cost: number;
  limit_pct_threshold: number;
  return_shap: boolean;
}

export interface BacktestConfigUpdate {
  train_window?: number;
  gap?: number;
  test_step?: number;
  top_k?: number;
  friction_cost?: number;
  limit_pct_threshold?: number;
  return_shap?: boolean;
}

// ================================================================
// HPO Config Types
// ================================================================
export interface HPOConfig {
  enabled: boolean;
  n_trials: number;
  objective_metric: string;
  output_dir: string;
  n_jobs: number;
  timeout: number | null;
  resume: boolean;
}

export interface HPOConfigUpdate {
  enabled?: boolean;
  n_trials?: number;
  objective_metric?: string;
  n_jobs?: number;
  timeout?: number | null;
  resume?: boolean;
}

// ================================================================
// Stacking Config Types
// ================================================================
export interface StackingConfig {
  enabled: boolean;
  base_learners: string[];
  meta_learner: string;
  validation_ratio: number;
  cv_folds: number;
  use_cv: boolean;
}

export interface StackingConfigUpdate {
  enabled?: boolean;
  base_learners?: string[];
  meta_learner?: string;
  validation_ratio?: number;
  cv_folds?: number;
  use_cv?: boolean;
}

export interface ConfigOptions {
  available_indices: string[];
  available_factor_groups: string[];
  available_models: string[];
  objective_metrics: string[];
  meta_learner_types: string[];
}

export interface ConfigUpdateResponse {
  success: boolean;
  message: string;
  updated_fields: string[];
}

// ================================================================
// Task Types
// ================================================================
export interface TaskCreateRequest {
  task_type: string;
  steps?: string[];
  notes?: string;
}

export interface TaskResponse {
  task_id: string;
  status: 'pending' | 'running' | 'paused' | 'succeeded' | 'failed' | 'cancelled';
  progress_pct: number;
  progress_message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  steps: string;
  model_name: string;
  universe_name: string;
  submit_source: string;
}

export interface TaskListResponse {
  tasks: TaskResponse[];
  total: number;
}

export interface TaskActionResponse {
  success: boolean;
  message: string;
  task_id: string;
}

// ================================================================
// Stock Types
// ================================================================
export interface StockListItem {
  code: string;
  name: string | null;
  industry: string | null;
  latest_date: string | null;
  latest_close: number | null;
  pct_chg: number | null;
  volume: number | null;
  amount: number | null;
  turn: number | null;
  pe_ttm: number | null;
  pb_mrq: number | null;
  is_st: boolean;
  is_delisted: boolean;
  bar_count: number;
}

export interface StockListResponse {
  stocks: StockListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface StockStats {
  total_stocks: number;
  with_names: number;
  by_industry: Record<string, number>;
  date_range: [string, string] | null;
  total_bars: number;
}

export interface StockDetail {
  code: string;
  name: string | null;
  industry: string | null;
  latest_date: string | null;
  latest_close: number | null;
  pct_chg: number | null;
  volume: number | null;
  amount: number | null;
  turn: number | null;
  pe_ttm: number | null;
  pb_mrq: number | null;
  ps_ttm: number | null;
  pcf_ttm: number | null;
  is_st: boolean;
  bar_count: number;
  date_range: [string, string] | null;
}

export interface OHLCBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  pct_chg: number;
  turn: number;
}

export interface OHLCResponse {
  code: string;
  bars: OHLCBar[];
}

export interface SyncNamesResponse {
  success: boolean;
  message: string;
  updated_count: number;
}

export interface UpdateProgress {
  success: boolean;
  message: string;
  total_stocks: number;
  updated_stocks: number;
  failed_stocks: number;
  skipped_stocks: number;
  total_bars: number;
}

export const api = {
  health: () => apiGet<{ status: string; service: string }>('/health'),
  dataLayers: () => apiGet<LayersResponse>('/api/data-layers'),
  dataLayerDetail: (layer: string) => apiGet<LayerStatus>(`/api/data-layers/${layer}`),
  cacheStats: () => apiGet<CacheStats>('/api/data-layers/cache/stats'),
  hpoStatus: () => apiGet<HPOStatusResponse>('/api/hpo/status'),
  hpoTrials: () => apiGet<{ trials: HPOTrial[] }>('/api/hpo/trials'),

  // Backtest API
  backtestResults: () => apiGet<BacktestResultsResponse>('/api/backtest/results'),
  runBacktest: () => apiPost<{ message: string; status: string }>('/api/backtest/run'),
  getNav: () => apiGet<NavResponse>('/api/backtest/nav'),

  // Dashboard API
  getDashboardSummary: () => apiGet<DashboardSummaryResponse>('/api/dashboard/summary'),

  // Factor Analysis API
  getFactorSummary: () => apiGet<FactorSummaryResponse>('/api/factors/summary'),
  getFactorICSeries: (factorName?: string) => apiGet<FactorICSeriesResponse>(`/api/factors/ic-series${factorName ? `?factor=${factorName}` : ''}`),
  getFactorCorrelation: () => apiGet<FactorCorrelationResponse>('/api/factors/correlation'),

  // Config API - ETL
  getETLConfig: () => apiGet<ETLConfig>('/api/config/etl'),
  updateETLConfig: (data: ETLConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/etl', data),

  // Config API - Features
  getFeaturesConfig: () => apiGet<FeaturesConfig>('/api/config/features'),
  updateFeaturesConfig: (data: FeaturesConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/features', data),

  // Config API - CrossSection
  getCrossSectionConfig: () => apiGet<CrossSectionConfig>('/api/config/cross_section'),
  updateCrossSectionConfig: (data: CrossSectionConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/cross_section', data),

  // Config API - Model (新增)
  getModelConfig: () => apiGet<ModelConfig>('/api/config/model'),
  updateModelConfig: (data: ModelConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/model', data),

  // Config API - Backtest (新增)
  getBacktestConfig: () => apiGet<BacktestConfig>('/api/config/backtest'),
  updateBacktestConfig: (data: BacktestConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/backtest', data),

  // Config API - HPO (新增)
  getHPOConfig: () => apiGet<HPOConfig>('/api/config/hpo'),
  updateHPOConfig: (data: HPOConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/hpo', data),

  // Config API - Stacking (新增)
  getStackingConfig: () => apiGet<StackingConfig>('/api/config/stacking'),
  updateStackingConfig: (data: StackingConfigUpdate) => apiPut<ConfigUpdateResponse>('/api/config/stacking', data),

  // Config Options
  getConfigOptions: () => apiGet<ConfigOptions>('/api/config/options'),

  // Task API
  createTask: (data: TaskCreateRequest) => apiPost<TaskActionResponse>('/api/tasks', data),
  getTasks: (status?: string) => apiGet<TaskListResponse>(`/api/tasks${status ? `?status=${status}` : ''}`),
  getTask: (taskId: string) => apiGet<TaskResponse>(`/api/tasks/${taskId}`),
  cancelTask: (taskId: string) => apiPost<TaskActionResponse>(`/api/tasks/${taskId}/cancel`),
  retryTask: (taskId: string) => apiPost<TaskActionResponse>(`/api/tasks/${taskId}/retry`),
  killAndCleanup: (taskId: string) => apiPost<TaskActionResponse>(`/api/tasks/${taskId}/kill-cleanup`),
  pauseTask: (taskId: string) => apiPost<TaskActionResponse>(`/api/tasks/${taskId}/pause`),
  resumeTask: (taskId: string) => apiPost<TaskActionResponse>(`/api/tasks/${taskId}/resume`),

  // Stock API
  getStocks: (params: { page?: number; page_size?: number; search?: string; industry?: string; sort_by?: string; sort_desc?: boolean }) => {
    const query = new URLSearchParams();
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));
    if (params.search) query.set('search', params.search);
    if (params.industry) query.set('industry', params.industry);
    if (params.sort_by) query.set('sort_by', params.sort_by);
    if (params.sort_desc) query.set('sort_desc', 'true');
    return apiGet<StockListResponse>(`/api/stocks?${query.toString()}`);
  },
  getStockStats: () => apiGet<StockStats>('/api/stocks/stats'),
  getIndustries: () => apiGet<{ industries: string[] }>('/api/stocks/industries'),
  getStockDetail: (code: string) => apiGet<StockDetail>(`/api/stocks/${code}`),
  getStockOHLC: (code: string, params?: { start_date?: string; end_date?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.start_date) query.set('start_date', params.start_date);
    if (params?.end_date) query.set('end_date', params.end_date);
    if (params?.limit) query.set('limit', String(params.limit));
    return apiGet<OHLCResponse>(`/api/stocks/${code}/ohlc?${query.toString()}`);
  },
  syncStockNames: () => apiPost<SyncNamesResponse>('/api/stocks/sync-names'),
  updateStockData: () => apiPost<UpdateProgress>('/api/stocks/update'),
  getUpdateStatus: () => apiGet<UpdateProgress>('/api/stocks/update/status'),
  refreshCache: () => apiPost<{ success: boolean; message: string; count: number }>('/api/stocks/cache/refresh'),
};
