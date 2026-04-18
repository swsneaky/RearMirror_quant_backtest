import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Play, Loader2 } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import { useBacktestResults, useNavData, useRunBacktest } from '@/hooks';

const modelOptions = [
  { value: 'lightgbm', label: 'LightGBM' },
  { value: 'xgboost', label: 'XGBoost' },
  { value: 'randomforest', label: 'RandomForest' },
];

export function BacktestPage() {
  const [model, setModel] = useState('lightgbm');
  const [trainWindow, setTrainWindow] = useState(500);
  const [isolationBand, setIsolationBand] = useState(5);
  const [holdingsCount, setHoldingsCount] = useState(30);
  const [stepSize, setStepSize] = useState(5);

  // React Query hooks
  const { data: backtestData, isLoading: metricsLoading, error: metricsError } = useBacktestResults();
  const { data: navData, isLoading: navLoading } = useNavData();
  const runBacktest = useRunBacktest();

  const hasResults = backtestData?.has_results && backtestData?.metrics;
  const metrics = backtestData?.metrics;
  const navPoints = navData?.nav || [];

  const handleRunBacktest = () => {
    runBacktest.mutate();
  };

  const chartOption = navPoints.length > 0 ? {
    title: {
      text: 'NAV Curve',
      left: 'center',
    },
    tooltip: {
      trigger: 'axis',
    },
    legend: {
      data: ['Strategy', 'Benchmark', 'Excess'],
      bottom: 0,
    },
    xAxis: {
      type: 'category',
      data: navPoints.map(p => p.date),
    },
    yAxis: {
      type: 'value',
      name: 'NAV',
    },
    series: [
      {
        name: 'Strategy',
        type: 'line',
        data: navPoints.map(p => p.strategy_nav),
        smooth: true,
        lineStyle: { width: 2 },
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: 'Benchmark',
        type: 'line',
        data: navPoints.map(p => p.benchmark_nav),
        smooth: true,
        lineStyle: { width: 2, type: 'dashed' },
        itemStyle: { color: '#6b7280' },
      },
      {
        name: 'Excess',
        type: 'line',
        data: navPoints.map(p => p.excess_nav),
        smooth: true,
        lineStyle: { width: 2, type: 'dotted' },
        itemStyle: { color: '#10b981' },
      },
    ],
    grid: {
      left: '10%',
      right: '10%',
      bottom: '15%',
      top: '15%',
    },
  } : null;

  const formatPercent = (value: number | null | undefined) => {
    if (value === null || value === undefined) return '--';
    return `${(value * 100).toFixed(2)}%`;
  };

  const formatNumber = (value: number | null | undefined, decimals = 2) => {
    if (value === null || value === undefined) return '--';
    return value.toFixed(decimals);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Backtest Workbench</h1>
        <p className="text-muted-foreground">
          Run walk-forward backtests with configurable parameters
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Parameter Panel */}
        <Card className="lg:w-80 shrink-0">
          <CardHeader>
            <CardTitle>Parameters</CardTitle>
            <CardDescription>Configure backtest settings</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Model Selection */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Model</label>
              <Select
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {modelOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>

            {/* Training Window */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Training Window</label>
              <Input
                type="number"
                value={trainWindow}
                onChange={(e) => setTrainWindow(Number(e.target.value))}
                min={1}
              />
            </div>

            {/* Isolation Band */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Isolation Band</label>
              <Input
                type="number"
                value={isolationBand}
                onChange={(e) => setIsolationBand(Number(e.target.value))}
                min={0}
              />
            </div>

            {/* Holdings Count */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Holdings Count</label>
              <Input
                type="number"
                value={holdingsCount}
                onChange={(e) => setHoldingsCount(Number(e.target.value))}
                min={1}
              />
            </div>

            {/* Step Size */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Step Size</label>
              <Input
                type="number"
                value={stepSize}
                onChange={(e) => setStepSize(Number(e.target.value))}
                min={1}
              />
            </div>

            {/* Run Button */}
            <Button
              className="w-full mt-4"
              onClick={handleRunBacktest}
              disabled={runBacktest.isPending}
            >
              {runBacktest.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Play className="h-4 w-4 mr-2" />
              )}
              {runBacktest.isPending ? 'Running...' : 'Run Backtest'}
            </Button>
          </CardContent>
        </Card>

        {/* Results Panel */}
        <div className="flex-1 space-y-6">
          {/* Loading State */}
          {metricsLoading && (
            <div className="flex items-center justify-center h-40">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <span className="ml-2 text-muted-foreground">Loading results...</span>
            </div>
          )}

          {/* Error State */}
          {metricsError && (
            <Card className="border-destructive">
              <CardContent className="pt-6">
                <p className="text-destructive">Failed to load backtest results. Please check if the backend is running.</p>
              </CardContent>
            </Card>
          )}

          {/* Metrics Cards - Show all 10 metrics */}
          {!metricsLoading && hasResults && metrics && (
            <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Annualized Return
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-green-500">
                    {formatPercent(metrics.ann_return)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Ann. Excess Return
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-green-600">
                    {formatPercent(metrics.ann_excess_return)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Ann. Volatility
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatPercent(metrics.ann_volatility)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Tracking Error
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatPercent(metrics.tracking_error)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Sharpe Ratio
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatNumber(metrics.sharpe_ratio)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Information Ratio
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatNumber(metrics.information_ratio)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Max Drawdown
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-red-500">
                    {formatPercent(metrics.max_drawdown)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Excess Max DD
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold text-red-500">
                    {formatPercent(metrics.excess_max_drawdown)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Avg Turnover
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatPercent(metrics.avg_turnover)}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Avg Cost/Period
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatPercent(metrics.avg_cost_per_period)}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* No Results State */}
          {!metricsLoading && !hasResults && !metricsError && (
            <Card>
              <CardContent className="pt-6">
                <p className="text-muted-foreground text-center">
                  No backtest results available. Click "Run Backtest" to start.
                </p>
              </CardContent>
            </Card>
          )}

          {/* NAV Chart */}
          <Card>
            <CardHeader>
              <CardTitle>Net Asset Value</CardTitle>
              <CardDescription>Strategy vs Benchmark performance</CardDescription>
            </CardHeader>
            <CardContent>
              {navLoading ? (
                <div className="flex items-center justify-center h-[400px]">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : chartOption ? (
                <ReactECharts
                  option={chartOption}
                  style={{ height: '400px' }}
                  opts={{ renderer: 'svg' }}
                />
              ) : (
                <div className="flex items-center justify-center h-[400px] text-muted-foreground">
                  No NAV data available
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
