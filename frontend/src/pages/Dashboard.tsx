import { Link } from 'react-router-dom';
import { Layers, FlaskConical, ChartLine, Cpu, Database, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

import { useDashboardSummary } from '@/hooks';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export function Dashboard() {
  const { data: summary, isLoading } = useDashboardSummary();

  // Format helpers
  const formatPct = (v: number | null) => v !== null ? `${(v * 100).toFixed(2)}%` : '-';
  const formatNumber = (v: number) => {
    if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
    if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
    return v.toLocaleString();
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Welcome to RearMirror - A-share Quantitative Research Platform
        </p>
      </div>

      {/* Statistics Overview */}
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : summary && (
        <div className="space-y-4">
          {/* Primary Stats */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {/* Iterations Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">迭代总数</CardTitle>
                <ChartLine className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{summary.iterations.total}</div>
                <p className="text-xs text-muted-foreground">
                  已完成的回测迭代
                </p>
              </CardContent>
            </Card>

            {/* HPO Status Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">HPO 状态</CardTitle>
                <Cpu className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                {summary.hpo.status === 'not_started' || summary.hpo.total_trials === 0 ? (
                  <>
                    <div className="text-2xl font-bold">-</div>
                    <p className="text-xs text-muted-foreground">尚未运行 HPO</p>
                  </>
                ) : (
                  <>
                    <div className="text-2xl font-bold">
                      {summary.hpo.current_trial}/{summary.hpo.total_trials}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant={summary.hpo.status === 'running' ? 'default' : 'secondary'}>
                        {summary.hpo.status === 'running' ? '运行中' : '已完成'}
                      </Badge>
                      {summary.hpo.best_value !== null && (
                        <span className="text-xs text-muted-foreground">
                          最佳: {summary.hpo.best_value.toFixed(4)}
                        </span>
                      )}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Backtest Metrics Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">最新回测</CardTitle>
                <ChartLine className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                {summary.backtest.has_results ? (
                  <>
                    <div className="flex items-center gap-4">
                      <div>
                        <div className="text-xs text-muted-foreground">夏普比率</div>
                        <div className="text-lg font-bold">
                          {summary.backtest.sharpe_ratio?.toFixed(2) ?? '-'}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">年化收益</div>
                        <div className="text-lg font-bold text-green-500">
                          {formatPct(summary.backtest.ann_return)}
                        </div>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      最大回撤: {formatPct(summary.backtest.max_drawdown)}
                    </p>
                  </>
                ) : (
                  <>
                    <div className="text-2xl font-bold">-</div>
                    <p className="text-xs text-muted-foreground">暂无回测结果</p>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Data Layers Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">数据层状态</CardTitle>
                <Database className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{summary.data_layers.total}</div>
                <div className="flex items-center gap-2 mt-1">
                  {summary.data_layers.needs_update > 0 ? (
                    <>
                      <AlertCircle className="h-4 w-4 text-yellow-500" />
                      <span className="text-xs text-yellow-600">
                        {summary.data_layers.needs_update} 层待更新
                      </span>
                    </>
                  ) : (
                    <>
                      <CheckCircle className="h-4 w-4 text-green-500" />
                      <span className="text-xs text-green-600">全部最新</span>
                    </>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Secondary Stats */}
          <div className="grid gap-4 md:grid-cols-3">
            {/* Models Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">模型数量</CardTitle>
                <Cpu className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{summary.models.total}</div>
                {Object.keys(summary.models.by_status).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {Object.entries(summary.models.by_status).map(([status, count]) => (
                      <Badge key={status} variant="outline" className="text-xs">
                        {status}: {count}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Tasks Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">任务统计</CardTitle>
                <Layers className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{summary.tasks.total}</div>
                {Object.keys(summary.tasks.by_status).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {Object.entries(summary.tasks.by_status).map(([status, count]) => (
                      <Badge
                        key={status}
                        variant={status === 'running' ? 'default' : status === 'failed' ? 'destructive' : 'secondary'}
                        className="text-xs"
                      >
                        {status}: {count}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Stocks Card */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">股票池</CardTitle>
                <Database className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatNumber(summary.stocks.total)}</div>
                <p className="text-xs text-muted-foreground">
                  {formatNumber(summary.stocks.total_bars)} 条日线数据
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Navigation Cards */}
      <div>
        <h2 className="text-lg font-semibold mb-4">快速导航</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Link to="/data-layers" className="block">
            <Card className="h-full hover:bg-muted/50 transition-colors">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Database className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">Data Layers</CardTitle>
                </div>
                <CardDescription>管理版本化数据资产，查看数据层状态</CardDescription>
              </CardHeader>
            </Card>
          </Link>
          <Link to="/backtest" className="block">
            <Card className="h-full hover:bg-muted/50 transition-colors">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <ChartLine className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">Backtesting</CardTitle>
                </div>
                <CardDescription>运行回测，查看绩效指标和净值曲线</CardDescription>
              </CardHeader>
            </Card>
          </Link>
          <Link to="/hpo" className="block">
            <Card className="h-full hover:bg-muted/50 transition-colors">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Cpu className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">HPO</CardTitle>
                </div>
                <CardDescription>超参数优化，探索最优模型配置</CardDescription>
              </CardHeader>
            </Card>
          </Link>
          <Link to="/factors" className="block">
            <Card className="h-full hover:bg-muted/50 transition-colors">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <FlaskConical className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">Factor Research</CardTitle>
                </div>
                <CardDescription>因子分析，IC 序列与因子相关性</CardDescription>
              </CardHeader>
            </Card>
          </Link>
          <Link to="/stocks" className="block">
            <Card className="h-full hover:bg-muted/50 transition-colors">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Database className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">Stocks</CardTitle>
                </div>
                <CardDescription>股票池数据，K 线图与基本信息</CardDescription>
              </CardHeader>
            </Card>
          </Link>
          <Link to="/iterations" className="block">
            <Card className="h-full hover:bg-muted/50 transition-colors">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Layers className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">Iterations</CardTitle>
                </div>
                <CardDescription>迭代历史，查看各轮训练与回测结果</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        </div>
      </div>
    </div>
  );
}
