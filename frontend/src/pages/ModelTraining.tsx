import { useState, useEffect } from 'react';
import { Play, Save, RotateCcw, Brain, Loader2, CheckCircle, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import {
  useConfigOptions,
  useModelConfig,
  useUpdateModelConfig,
  useStackingConfig,
  useUpdateStackingConfig,
  useCreateTask,
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

// Parameter field component
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
}: {
  params: Record<string, unknown>;
  onChange: (k: string, v: number | string | boolean) => void;
}) {
  const d = MODEL_DEFAULTS.lightgbm;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <ParamField label="Objective" value={params.objective ?? d.objective} defaultValue={d.objective} onChange={(v) => onChange('objective', v)} type="select" options={['regression', 'huber', 'fair', 'poisson', 'quantile', 'mape']} />
        <ParamField label="Boosting" value={params.boosting_type ?? d.boosting_type} defaultValue={d.boosting_type} onChange={(v) => onChange('boosting_type', v)} type="select" options={['gbdt', 'dart', 'rf', 'goss']} />
        <ParamField label="N Estimators" value={params.n_estimators ?? d.n_estimators} defaultValue={d.n_estimators} onChange={(v) => onChange('n_estimators', v)} min={10} max={2000} />
        <ParamField label="Learning Rate" value={params.learning_rate ?? d.learning_rate} defaultValue={d.learning_rate} onChange={(v) => onChange('learning_rate', v)} step={0.001} min={0.001} max={0.5} />
        <ParamField label="Max Depth" value={params.max_depth ?? d.max_depth} defaultValue={d.max_depth} onChange={(v) => onChange('max_depth', v)} min={-1} max={20} />
        <ParamField label="Num Leaves" value={params.num_leaves ?? d.num_leaves} defaultValue={d.num_leaves} onChange={(v) => onChange('num_leaves', v)} min={2} max={256} />
        <ParamField label="Min Child Samples" value={params.min_child_samples ?? d.min_child_samples} defaultValue={d.min_child_samples} onChange={(v) => onChange('min_child_samples', v)} min={1} />
        <ParamField label="Reg Lambda" value={params.reg_lambda ?? d.reg_lambda} defaultValue={d.reg_lambda} onChange={(v) => onChange('reg_lambda', v)} step={0.1} min={0} />
        <ParamField label="Reg Alpha" value={params.reg_alpha ?? d.reg_alpha} defaultValue={d.reg_alpha} onChange={(v) => onChange('reg_alpha', v)} step={0.1} min={0} />
        <ParamField label="Colsample Bytree" value={params.colsample_bytree ?? d.colsample_bytree} defaultValue={d.colsample_bytree} onChange={(v) => onChange('colsample_bytree', v)} step={0.05} min={0.1} max={1} />
        <ParamField label="Subsample" value={params.subsample ?? d.subsample} defaultValue={d.subsample} onChange={(v) => onChange('subsample', v)} step={0.05} min={0.1} max={1} />
        <ParamField label="Max Bin" value={params.max_bin ?? d.max_bin} defaultValue={d.max_bin} onChange={(v) => onChange('max_bin', v)} min={32} max={1024} />
      </div>
    </div>
  );
}

// XGBoost params form
function XGBoostForm({
  params,
  onChange,
}: {
  params: Record<string, unknown>;
  onChange: (k: string, v: number | string | boolean) => void;
}) {
  const d = MODEL_DEFAULTS.xgboost;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <ParamField label="Objective" value={params.objective ?? d.objective} defaultValue={d.objective} onChange={(v) => onChange('objective', v)} type="select" options={['reg:squarederror', 'reg:squaredlogerror', 'reg:pseudohubererror', 'reg:absoluteerror']} />
        <ParamField label="N Estimators" value={params.n_estimators ?? d.n_estimators} defaultValue={d.n_estimators} onChange={(v) => onChange('n_estimators', v)} min={10} max={2000} />
        <ParamField label="Learning Rate" value={params.learning_rate ?? d.learning_rate} defaultValue={d.learning_rate} onChange={(v) => onChange('learning_rate', v)} step={0.001} min={0.001} max={0.5} />
        <ParamField label="Max Depth" value={params.max_depth ?? d.max_depth} defaultValue={d.max_depth} onChange={(v) => onChange('max_depth', v)} min={0} max={20} />
        <ParamField label="Max Leaves" value={params.max_leaves ?? d.max_leaves} defaultValue={d.max_leaves} onChange={(v) => onChange('max_leaves', v)} min={2} max={256} />
        <ParamField label="Min Child Weight" value={params.min_child_weight ?? d.min_child_weight} defaultValue={d.min_child_weight} onChange={(v) => onChange('min_child_weight', v)} step={0.1} min={0} />
        <ParamField label="Gamma" value={params.gamma ?? d.gamma} defaultValue={d.gamma} onChange={(v) => onChange('gamma', v)} step={0.01} min={0} />
        <ParamField label="Reg Lambda" value={params.reg_lambda ?? d.reg_lambda} defaultValue={d.reg_lambda} onChange={(v) => onChange('reg_lambda', v)} step={0.1} min={0} />
        <ParamField label="Reg Alpha" value={params.reg_alpha ?? d.reg_alpha} defaultValue={d.reg_alpha} onChange={(v) => onChange('reg_alpha', v)} step={0.1} min={0} />
        <ParamField label="Colsample Bytree" value={params.colsample_bytree ?? d.colsample_bytree} defaultValue={d.colsample_bytree} onChange={(v) => onChange('colsample_bytree', v)} step={0.05} min={0.1} max={1} />
        <ParamField label="Subsample" value={params.subsample ?? d.subsample} defaultValue={d.subsample} onChange={(v) => onChange('subsample', v)} step={0.05} min={0.1} max={1} />
        <ParamField label="Max Bin" value={params.max_bin ?? d.max_bin} defaultValue={d.max_bin} onChange={(v) => onChange('max_bin', v)} min={32} max={1024} />
      </div>
    </div>
  );
}

// Random Forest params form
function RandomForestForm({
  params,
  onChange,
}: {
  params: Record<string, unknown>;
  onChange: (k: string, v: number | string | boolean) => void;
}) {
  const d = MODEL_DEFAULTS.random_forest;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <ParamField label="Criterion" value={params.criterion ?? d.criterion} defaultValue={d.criterion} onChange={(v) => onChange('criterion', v)} type="select" options={['squared_error', 'absolute_error', 'friedman_mse', 'poisson']} />
        <ParamField label="N Estimators" value={params.n_estimators ?? d.n_estimators} defaultValue={d.n_estimators} onChange={(v) => onChange('n_estimators', v)} min={10} max={1000} />
        <ParamField label="Max Depth" value={params.max_depth ?? d.max_depth} defaultValue={d.max_depth} onChange={(v) => onChange('max_depth', v)} min={1} max={50} />
        <ParamField label="Min Samples Leaf" value={params.min_samples_leaf ?? d.min_samples_leaf} defaultValue={d.min_samples_leaf} onChange={(v) => onChange('min_samples_leaf', v)} min={1} />
        <ParamField label="Min Samples Split" value={params.min_samples_split ?? d.min_samples_split} defaultValue={d.min_samples_split} onChange={(v) => onChange('min_samples_split', v)} min={2} />
        <ParamField label="Max Features" value={params.max_features ?? d.max_features} defaultValue={d.max_features} onChange={(v) => onChange('max_features', v)} step={0.05} min={0.1} max={1} />
        <ParamField label="Max Samples" value={params.max_samples ?? d.max_samples} defaultValue={d.max_samples} onChange={(v) => onChange('max_samples', v)} step={0.05} min={0.1} max={1} />
        <ParamField label="N Jobs" value={params.n_jobs ?? d.n_jobs} defaultValue={d.n_jobs} onChange={(v) => onChange('n_jobs', v)} min={-1} max={16} />
      </div>
    </div>
  );
}

export function ModelTrainingPage() {
  const { data: options } = useConfigOptions();
  const { data: modelConfig } = useModelConfig();
  const { data: stackingConfig } = useStackingConfig();

  const updateModel = useUpdateModelConfig();
  const updateStacking = useUpdateStackingConfig();
  const createTask = useCreateTask();

  // Model state
  const [activeModel, setActiveModel] = useState<ModelType>('lightgbm');
  const [lightgbmParams, setLightgbmParams] = useState<Record<string, unknown>>({ ...MODEL_DEFAULTS.lightgbm });
  const [xgboostParams, setXgboostParams] = useState<Record<string, unknown>>({ ...MODEL_DEFAULTS.xgboost });
  const [randomForestParams, setRandomForestParams] = useState<Record<string, unknown>>({ ...MODEL_DEFAULTS.random_forest });

  // Stacking state
  const [stackingEnabled, setStackingEnabled] = useState(false);
  const [baseLearners, setBaseLearners] = useState<string[]>(['lightgbm', 'xgboost']);

  // Training state
  const [isTraining, setIsTraining] = useState(false);
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');

  // Initialize from config
  useEffect(() => {
    if (modelConfig) {
      setActiveModel(modelConfig.active as ModelType);
      if (modelConfig.lightgbm) setLightgbmParams({ ...MODEL_DEFAULTS.lightgbm, ...modelConfig.lightgbm });
      if (modelConfig.xgboost) setXgboostParams({ ...MODEL_DEFAULTS.xgboost, ...modelConfig.xgboost });
      if (modelConfig.random_forest) setRandomForestParams({ ...MODEL_DEFAULTS.random_forest, ...modelConfig.random_forest });
    }
  }, [modelConfig]);

  useEffect(() => {
    if (stackingConfig) {
      setStackingEnabled(stackingConfig.enabled);
      setBaseLearners(stackingConfig.base_learners);
    }
  }, [stackingConfig]);

  // Handle param change
  const handleParamChange = (model: ModelType, key: string, value: number | string | boolean) => {
    if (model === 'lightgbm') {
      setLightgbmParams((prev) => ({ ...prev, [key]: value }));
    } else if (model === 'xgboost') {
      setXgboostParams((prev) => ({ ...prev, [key]: value }));
    } else if (model === 'random_forest') {
      setRandomForestParams((prev) => ({ ...prev, [key]: value }));
    }
  };

  // Reset params
  const handleReset = (model: ModelType) => {
    if (model === 'lightgbm') setLightgbmParams({ ...MODEL_DEFAULTS.lightgbm });
    else if (model === 'xgboost') setXgboostParams({ ...MODEL_DEFAULTS.xgboost });
    else if (model === 'random_forest') setRandomForestParams({ ...MODEL_DEFAULTS.random_forest });
  };

  // Save config
  const handleSave = async () => {
    try {
      await updateModel.mutateAsync({
        active: activeModel,
        lightgbm: lightgbmParams,
        xgboost: xgboostParams,
        random_forest: randomForestParams,
      });
      if (stackingEnabled) {
        await updateStacking.mutateAsync({
          enabled: stackingEnabled,
          base_learners: baseLearners,
        });
      }
      toast.success('模型配置已保存');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    }
  };

  // Start training
  const handleTrain = async () => {
    setIsTraining(true);
    setTrainingStatus('running');
    try {
      await createTask.mutateAsync({
        task_type: 'train',
        notes: `Training ${activeModel} model`,
      });
      setTrainingStatus('success');
      toast.success('训练任务已启动');
    } catch (error) {
      setTrainingStatus('error');
      toast.error(error instanceof Error ? error.message : '启动失败');
    } finally {
      setIsTraining(false);
    }
  };

  const toggleBaseLearner = (model: string) => {
    setBaseLearners((prev) =>
      prev.includes(model) ? prev.filter((m) => m !== model) : [...prev, model]
    );
  };

  const isSaving = updateModel.isPending || updateStacking.isPending;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">模型训练</h1>
          <p className="text-muted-foreground">
            配置模型参数并执行训练
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleSave} disabled={isSaving}>
            <Save className="h-4 w-4 mr-2" />
            保存配置
          </Button>
          <Button onClick={handleTrain} disabled={isTraining}>
            {isTraining ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                训练中...
              </>
            ) : (
              <>
                <Play className="h-4 w-4 mr-2" />
                开始训练
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Training Status */}
      {trainingStatus !== 'idle' && (
        <Card className={trainingStatus === 'success' ? 'border-green-500' : trainingStatus === 'error' ? 'border-red-500' : ''}>
          <CardContent className="pt-4">
            <div className="flex items-center gap-3">
              {trainingStatus === 'running' && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
              {trainingStatus === 'success' && <CheckCircle className="h-5 w-5 text-green-500" />}
              {trainingStatus === 'error' && <XCircle className="h-5 w-5 text-red-500" />}
              <span>
                {trainingStatus === 'running' && '训练任务执行中...'}
                {trainingStatus === 'success' && '训练任务已启动，请查看 Tasks 页面查看进度'}
                {trainingStatus === 'error' && '训练任务启动失败'}
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Model Selection */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5" />
              模型配置
            </CardTitle>
            <CardDescription>
              选择模型类型并调整超参数
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue={activeModel} onValueChange={(v) => setActiveModel(v as ModelType)}>
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="lightgbm">LightGBM</TabsTrigger>
                <TabsTrigger value="xgboost">XGBoost</TabsTrigger>
                <TabsTrigger value="random_forest">Random Forest</TabsTrigger>
              </TabsList>

              <TabsContent value="lightgbm" className="space-y-4 mt-4">
                <div className="flex justify-end">
                  <Button size="sm" variant="ghost" onClick={() => handleReset('lightgbm')}>
                    <RotateCcw className="h-3 w-3 mr-1" />Reset
                  </Button>
                </div>
                <LightGBMForm
                  params={lightgbmParams}
                  onChange={(k, v) => handleParamChange('lightgbm', k, v)}
                />
              </TabsContent>

              <TabsContent value="xgboost" className="space-y-4 mt-4">
                <div className="flex justify-end">
                  <Button size="sm" variant="ghost" onClick={() => handleReset('xgboost')}>
                    <RotateCcw className="h-3 w-3 mr-1" />Reset
                  </Button>
                </div>
                <XGBoostForm
                  params={xgboostParams}
                  onChange={(k, v) => handleParamChange('xgboost', k, v)}
                />
              </TabsContent>

              <TabsContent value="random_forest" className="space-y-4 mt-4">
                <div className="flex justify-end">
                  <Button size="sm" variant="ghost" onClick={() => handleReset('random_forest')}>
                    <RotateCcw className="h-3 w-3 mr-1" />Reset
                  </Button>
                </div>
                <RandomForestForm
                  params={randomForestParams}
                  onChange={(k, v) => handleParamChange('random_forest', k, v)}
                />
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        {/* Stacking Config */}
        <Card>
          <CardHeader>
            <CardTitle>Stacking 集成</CardTitle>
            <CardDescription>
              可选：多模型集成学习
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={stackingEnabled}
                onChange={(e) => setStackingEnabled(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm font-medium">启用 Stacking</span>
            </label>

            {stackingEnabled && (
              <div className="space-y-3">
                <p className="text-xs font-medium text-muted-foreground">基学习器</p>
                <div className="flex flex-wrap gap-2">
                  {(options?.available_models ?? ['lightgbm', 'xgboost', 'random_forest']).map((m) => (
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
            )}

            <div className="p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
              <p><strong>Stacking</strong> 通过组合多个模型提升预测性能</p>
              <p className="mt-1">推荐: LightGBM + XGBoost</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
