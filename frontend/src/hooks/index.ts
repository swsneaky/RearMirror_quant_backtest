import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type {
  BacktestConfig,
  BacktestConfigUpdate,
  BacktestResultsResponse,
  NavResponse,
  CacheStats,
  CrossSectionConfig,
  CrossSectionConfigUpdate,
  DashboardSummaryResponse,
  ETLConfig,
  ETLConfigUpdate,
  FeaturesConfig,
  FeaturesConfigUpdate,
  HPOConfig,
  HPOConfigUpdate,
  HPOStatusResponse,
  HPOTrial,
  LayersResponse,
  ModelConfig,
  ModelConfigUpdate,
  StackingConfig,
  StackingConfigUpdate,
  TaskCreateRequest,
  TaskListResponse,
  TaskResponse,
  StockListResponse,
  StockStats,
  StockDetail,
  OHLCResponse,
  UpdateProgress,
  FactorSummaryResponse,
  FactorICSeriesResponse,
  FactorCorrelationResponse,
} from '@/api/client';

export function useDataLayers() {
  return useQuery<LayersResponse>({
    queryKey: ['dataLayers'],
    queryFn: api.dataLayers,
  });
}

export function useCacheStats() {
  return useQuery<CacheStats>({
    queryKey: ['cacheStats'],
    queryFn: api.cacheStats,
  });
}

export function useHealth() {
  return useQuery<{ status: string; service: string }>({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30000,
  });
}

export function useHPOStatus() {
  return useQuery<HPOStatusResponse>({
    queryKey: ['hpoStatus'],
    queryFn: api.hpoStatus,
    refetchInterval: 5000, // Refresh every 5 seconds for running optimizations
  });
}

export function useHPOTrials() {
  return useQuery<{ trials: HPOTrial[] }>({
    queryKey: ['hpoTrials'],
    queryFn: api.hpoTrials,
    refetchInterval: 5000,
  });
}

export function useBacktestResults() {
  return useQuery<BacktestResultsResponse>({
    queryKey: ['backtestResults'],
    queryFn: api.backtestResults,
  });
}

export function useNavData() {
  return useQuery<NavResponse>({
    queryKey: ['navData'],
    queryFn: api.getNav,
  });
}

export function useRunBacktest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.runBacktest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backtestResults'] });
      queryClient.invalidateQueries({ queryKey: ['navData'] });
    },
  });
}

export function useETLConfig() {
  return useQuery<ETLConfig>({
    queryKey: ['config', 'etl'],
    queryFn: api.getETLConfig,
  });
}

export function useFeaturesConfig() {
  return useQuery<FeaturesConfig>({
    queryKey: ['config', 'features'],
    queryFn: api.getFeaturesConfig,
  });
}

export function useCrossSectionConfig() {
  return useQuery<CrossSectionConfig>({
    queryKey: ['config', 'crossSection'],
    queryFn: api.getCrossSectionConfig,
  });
}

export function useConfigOptions() {
  return useQuery({
    queryKey: ['config', 'options'],
    queryFn: api.getConfigOptions,
  });
}

export function useUpdateETLConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ETLConfigUpdate) => api.updateETLConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'etl'] });
      queryClient.invalidateQueries({ queryKey: ['dataLayers'] });
    },
  });
}

export function useUpdateFeaturesConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: FeaturesConfigUpdate) => api.updateFeaturesConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'features'] });
      queryClient.invalidateQueries({ queryKey: ['dataLayers'] });
    },
  });
}

export function useUpdateCrossSectionConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CrossSectionConfigUpdate) => api.updateCrossSectionConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'crossSection'] });
      queryClient.invalidateQueries({ queryKey: ['dataLayers'] });
    },
  });
}

export function useTasks() {
  return useQuery<TaskListResponse>({
    queryKey: ['tasks'],
    queryFn: () => api.getTasks(),
    refetchInterval: 3000,
  });
}

export function useTask(taskId?: string) {
  return useQuery<TaskResponse>({
    queryKey: ['tasks', taskId],
    queryFn: () => api.getTask(taskId!),
    enabled: Boolean(taskId),
    refetchInterval: 3000,
  });
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: TaskCreateRequest) => api.createTask(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

export function useCancelTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api.cancelTask(taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

// ================================================================
// Model Config Hooks
// ================================================================
export function useModelConfig() {
  return useQuery<ModelConfig>({
    queryKey: ['config', 'model'],
    queryFn: api.getModelConfig,
  });
}

export function useUpdateModelConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ModelConfigUpdate) => api.updateModelConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'model'] });
    },
  });
}

// ================================================================
// Backtest Config Hooks
// ================================================================
export function useBacktestConfig() {
  return useQuery<BacktestConfig>({
    queryKey: ['config', 'backtest'],
    queryFn: api.getBacktestConfig,
  });
}

export function useUpdateBacktestConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: BacktestConfigUpdate) => api.updateBacktestConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'backtest'] });
    },
  });
}

// ================================================================
// HPO Config Hooks
// ================================================================
export function useHPOConfig() {
  return useQuery<HPOConfig>({
    queryKey: ['config', 'hpo'],
    queryFn: api.getHPOConfig,
  });
}

export function useUpdateHPOConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: HPOConfigUpdate) => api.updateHPOConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'hpo'] });
    },
  });
}

// ================================================================
// Stacking Config Hooks
// ================================================================
export function useStackingConfig() {
  return useQuery<StackingConfig>({
    queryKey: ['config', 'stacking'],
    queryFn: api.getStackingConfig,
  });
}

export function useUpdateStackingConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: StackingConfigUpdate) => api.updateStackingConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config', 'stacking'] });
    },
  });
}

// ================================================================
// Stock Hooks
// ================================================================
export function useStocks(params: { page?: number; page_size?: number; search?: string; industry?: string; sort_by?: string; sort_desc?: boolean }) {
  return useQuery<StockListResponse>({
    queryKey: ['stocks', params],
    queryFn: () => api.getStocks(params),
  });
}

export function useStockStats() {
  return useQuery<StockStats>({
    queryKey: ['stockStats'],
    queryFn: api.getStockStats,
  });
}

export function useIndustries() {
  return useQuery<{ industries: string[] }>({
    queryKey: ['industries'],
    queryFn: api.getIndustries,
  });
}

export function useStockDetail(code: string | null) {
  return useQuery<StockDetail>({
    queryKey: ['stock', code],
    queryFn: () => api.getStockDetail(code!),
    enabled: Boolean(code),
  });
}

export function useStockOHLC(code: string | null, params?: { start_date?: string; end_date?: string; limit?: number }) {
  return useQuery<OHLCResponse>({
    queryKey: ['stockOHLC', code, params],
    queryFn: () => api.getStockOHLC(code!, params),
    enabled: Boolean(code),
  });
}

export function useSyncStockNames() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.syncStockNames,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stocks'] });
      queryClient.invalidateQueries({ queryKey: ['stockStats'] });
    },
  });
}

export function useUpdateStockData() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.updateStockData,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stocks'] });
      queryClient.invalidateQueries({ queryKey: ['stockStats'] });
    },
  });
}

export function useUpdateStatus() {
  return useQuery<UpdateProgress>({
    queryKey: ['updateStatus'],
    queryFn: api.getUpdateStatus,
    refetchInterval: 2000, // 每2秒刷新
  });
}

// ================================================================
// Factor Analysis Hooks
// ================================================================
export function useFactorSummary() {
  return useQuery<FactorSummaryResponse>({
    queryKey: ['factorSummary'],
    queryFn: api.getFactorSummary,
  });
}

export function useFactorICSeries(factorName?: string) {
  return useQuery<FactorICSeriesResponse>({
    queryKey: ['factorICSeries', factorName],
    queryFn: () => api.getFactorICSeries(factorName),
    enabled: true, // Always enabled, backend returns first factor if not specified
  });
}

export function useFactorCorrelation() {
  return useQuery<FactorCorrelationResponse>({
    queryKey: ['factorCorrelation'],
    queryFn: api.getFactorCorrelation,
  });
}

// ================================================================
// Dashboard Hooks
// ================================================================
export function useDashboardSummary() {
  return useQuery<DashboardSummaryResponse>({
    queryKey: ['dashboardSummary'],
    queryFn: api.getDashboardSummary,
    refetchInterval: 10000, // 每10秒刷新
  });
}
