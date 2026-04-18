import { useState, useEffect } from 'react';
import { Save, Play, RotateCcw, Trash2, Copy, Hash, Calendar, Layers, Filter } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Select } from '@/components/ui/select';
import { DateRangePicker } from '@/components/DateRangePicker';
import { FactorGroupSelect } from '@/components/FactorGroupSelect';
import {
  useConfigOptions,
  useETLConfig,
  useFeaturesConfig,
  useCrossSectionConfig,
  useUpdateETLConfig,
  useUpdateFeaturesConfig,
  useUpdateCrossSectionConfig,
  useStockStats,
} from '@/hooks';

interface TrainingSet {
  id: string;
  name: string;
  factors: string[];
  universe: string;
  startDate: string;
  endDate: string;
  madMultiplier: number;
  industryNeutral: boolean;
  createdAt: string;
}

// 生成训练集 ID
function generateTrainingSetId(): string {
  const hash = Math.random().toString(36).substring(2, 10);
  return `train_set__${hash}`;
}

export function TrainingSetsPage() {
  // 配置数据
  const { data: options } = useConfigOptions();
  const { data: etlConfig } = useETLConfig();
  const { data: featuresConfig } = useFeaturesConfig();
  const { data: crossSectionConfig } = useCrossSectionConfig();
  const { data: stockStats } = useStockStats();

  // Mutations
  const updateETL = useUpdateETLConfig();
  const updateFeatures = useUpdateFeaturesConfig();
  const updateCrossSection = useUpdateCrossSectionConfig();

  // 本地训练集列表
  const [trainingSets, setTrainingSets] = useState<TrainingSet[]>([]);
  const [selectedSet, setSelectedSet] = useState<TrainingSet | null>(null);

  // 当前编辑的配置
  const [name, setName] = useState('');
  const [factors, setFactors] = useState<string[]>([]);
  const [universe, setUniverse] = useState('zz500');
  const [startDate, setStartDate] = useState('2016-01-01');
  const [endDate, setEndDate] = useState('2026-03-29');
  const [madMultiplier, setMadMultiplier] = useState(3.148);
  const [industryNeutral, setIndustryNeutral] = useState(true);

  // 从配置初始化
  useEffect(() => {
    if (etlConfig) {
      setUniverse(etlConfig.index_name || 'zz500');
      setStartDate(etlConfig.start_date || '2016-01-01');
      setEndDate(etlConfig.end_date || '2026-03-29');
    }
    if (featuresConfig) {
      setFactors(featuresConfig.active_factors || []);
    }
    if (crossSectionConfig) {
      setMadMultiplier(crossSectionConfig.mad_multiplier || 3.148);
    }
  }, [etlConfig, featuresConfig, crossSectionConfig]);

  // 保存训练集
  const handleSaveSet = () => {
    if (!name.trim()) {
      toast.error('请输入训练集名称');
      return;
    }
    if (factors.length === 0) {
      toast.error('请选择至少一个因子组');
      return;
    }

    const newSet: TrainingSet = {
      id: selectedSet?.id || generateTrainingSetId(),
      name: name.trim(),
      factors: [...factors],
      universe,
      startDate,
      endDate,
      madMultiplier,
      industryNeutral,
      createdAt: selectedSet?.createdAt || new Date().toISOString(),
    };

    if (selectedSet) {
      setTrainingSets(prev => prev.map(s => s.id === selectedSet.id ? newSet : s));
      toast.success('训练集已更新');
    } else {
      setTrainingSets(prev => [...prev, newSet]);
      toast.success('训练集已创建');
    }
    setSelectedSet(null);
    setName('');
  };

  // 应用训练集配置到系统
  const handleApplySet = async (set: TrainingSet) => {
    try {
      await Promise.all([
        updateETL.mutateAsync({
          index_name: set.universe,
          start_date: set.startDate,
          end_date: set.endDate,
        }),
        updateFeatures.mutateAsync({
          active_factors: set.factors,
        }),
        updateCrossSection.mutateAsync({
          mad_multiplier: set.madMultiplier,
        }),
      ]);
      toast.success(`已应用训练集: ${set.name}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '应用失败');
    }
  };

  // 删除训练集
  const handleDeleteSet = (id: string) => {
    setTrainingSets(prev => prev.filter(s => s.id !== id));
    if (selectedSet?.id === id) {
      setSelectedSet(null);
      setName('');
    }
    toast.success('训练集已删除');
  };

  // 编辑训练集
  const handleEditSet = (set: TrainingSet) => {
    setSelectedSet(set);
    setName(set.name);
    setFactors(set.factors);
    setUniverse(set.universe);
    setStartDate(set.startDate);
    setEndDate(set.endDate);
    setMadMultiplier(set.madMultiplier);
    setIndustryNeutral(set.industryNeutral);
  };

  // 复制训练集
  const handleCopySet = (set: TrainingSet) => {
    const newSet: TrainingSet = {
      ...set,
      id: generateTrainingSetId(),
      name: `${set.name} (副本)`,
      createdAt: new Date().toISOString(),
    };
    setTrainingSets(prev => [...prev, newSet]);
    toast.success('训练集已复制');
  };

  // 重置表单
  const handleReset = () => {
    setSelectedSet(null);
    setName('');
    if (featuresConfig) setFactors(featuresConfig.active_factors || []);
    if (etlConfig) {
      setUniverse(etlConfig.index_name || 'zz500');
      setStartDate(etlConfig.start_date || '2016-01-01');
      setEndDate(etlConfig.end_date || '2026-03-29');
    }
    if (crossSectionConfig) setMadMultiplier(crossSectionConfig.mad_multiplier || 3.148);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">训练集管理</h1>
          <p className="text-muted-foreground">
            定义因子组合、股票池、时间范围，生成版本化训练集
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* 左侧：训练集列表 */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="h-5 w-5" />
              训练集列表
            </CardTitle>
            <CardDescription>
              已保存 {trainingSets.length} 个训练集
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {trainingSets.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  暂无训练集，请创建新的训练集
                </div>
              ) : (
                trainingSets.map((set) => (
                  <div
                    key={set.id}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedSet?.id === set.id
                        ? 'border-primary bg-primary/5'
                        : 'hover:bg-muted/50'
                    }`}
                    onClick={() => handleEditSet(set)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate">{set.name}</p>
                        <p className="text-xs text-muted-foreground font-mono">
                          {set.id}
                        </p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {set.factors.slice(0, 3).map((f) => (
                            <Badge key={f} variant="outline" className="text-xs">
                              {f}
                            </Badge>
                          ))}
                          {set.factors.length > 3 && (
                            <Badge variant="outline" className="text-xs">
                              +{set.factors.length - 3}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleApplySet(set);
                          }}
                          title="应用"
                        >
                          <Play className="h-3 w-3" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCopySet(set);
                          }}
                          title="复制"
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteSet(set.id);
                          }}
                          title="删除"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      {set.startDate} ~ {set.endDate} | {set.universe}
                    </div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        {/* 右侧：配置编辑器 */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>
              {selectedSet ? '编辑训练集' : '创建训练集'}
            </CardTitle>
            <CardDescription>
              配置因子组合、股票池和时间范围
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* 基本信息 */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium flex items-center gap-2">
                <Hash className="h-4 w-4" />
                基本信息
              </h4>
              <div className="grid gap-4 grid-cols-2">
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">训练集名称</span>
                  <Input
                    placeholder="例如: zz500_5y_all_factors"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">股票池 (Universe)</span>
                  <Select value={universe} onChange={(e) => setUniverse(e.target.value)}>
                    {(options?.available_indices ?? ['zz500', 'hs300', 'sz50']).map((i) => (
                      <option key={i} value={i}>{i}</option>
                    ))}
                  </Select>
                </label>
              </div>
            </div>

            {/* 时间范围 */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium flex items-center gap-2">
                <Calendar className="h-4 w-4" />
                时间范围
              </h4>
              <DateRangePicker
                startDate={startDate}
                endDate={endDate}
                onStartDateChange={setStartDate}
                onEndDateChange={setEndDate}
              />
            </div>

            {/* 因子组合 */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium flex items-center gap-2">
                <Layers className="h-4 w-4" />
                因子组合
                <Badge variant="outline">{factors.length} 个已选</Badge>
              </h4>
              <FactorGroupSelect
                options={options?.available_factor_groups ?? []}
                value={factors}
                onChange={setFactors}
              />
            </div>

            {/* 中性化参数 */}
            <div className="space-y-4">
              <h4 className="text-sm font-medium flex items-center gap-2">
                <Filter className="h-4 w-4" />
                中性化参数
              </h4>
              <div className="grid gap-4 grid-cols-3">
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">MAD 倍数</span>
                  <Input
                    type="number"
                    step="0.001"
                    value={madMultiplier}
                    onChange={(e) => setMadMultiplier(Number(e.target.value))}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">行业中性</span>
                  <select
                    value={industryNeutral ? 'true' : 'false'}
                    onChange={(e) => setIndustryNeutral(e.target.value === 'true')}
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs"
                  >
                    <option value="true">开启</option>
                    <option value="false">关闭</option>
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">行业数量</span>
                  <Input
                    type="number"
                    value={Object.keys(stockStats?.by_industry ?? {}).length}
                    disabled
                  />
                </label>
              </div>
            </div>

            {/* 预览 */}
            <div className="p-4 rounded-lg bg-muted/50 space-y-2">
              <p className="text-sm font-medium">训练集预览</p>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>股票池: {universe}</span>
                <span>时间: {startDate} ~ {endDate}</span>
                <span>因子组: {factors.length} 个</span>
                <span>MAD: {madMultiplier}</span>
              </div>
            </div>

            {/* 操作按钮 */}
            <div className="flex gap-2">
              <Button onClick={handleSaveSet} disabled={!name.trim() || factors.length === 0}>
                <Save className="h-4 w-4 mr-2" />
                {selectedSet ? '更新训练集' : '保存训练集'}
              </Button>
              <Button variant="outline" onClick={handleReset}>
                <RotateCcw className="h-4 w-4 mr-2" />
                重置
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
