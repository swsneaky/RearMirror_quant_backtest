import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Loader2, BarChart3, TrendingUp, Grid3X3 } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { useFactorSummary, useFactorICSeries, useFactorCorrelation } from '@/hooks';
import type { FactorSummary } from '@/api/client';

export function FactorsPage() {
  const [selectedFactor, setSelectedFactor] = useState<string | null>(null);

  // Queries
  const { data: summaryData, isLoading: summaryLoading, error: summaryError } = useFactorSummary();
  const { data: icSeriesData, isLoading: icSeriesLoading } = useFactorICSeries(selectedFactor ?? undefined);
  const { data: correlationData, isLoading: correlationLoading } = useFactorCorrelation();

  const factors = summaryData?.factors ?? [];
  const icSeries = icSeriesData?.ic_series ?? [];
  const factorNames = correlationData?.factor_names ?? [];
  const correlationMatrix = correlationData?.correlation_matrix ?? [];

  // Format helpers
  const formatNumber = (v: number | null | undefined, decimals = 4) => {
    if (v === null || v === undefined) return '--';
    return v.toFixed(decimals);
  };

  const formatPercent = (v: number | null | undefined, decimals = 2) => {
    if (v === null || v === undefined) return '--';
    return `${(v * 100).toFixed(decimals)}%`;
  };

  // Get ICIR badge color based on value
  const getICIRBadge = (icir: number) => {
    if (icir >= 2) return 'bg-green-500 text-white';
    if (icir >= 1) return 'bg-green-400 text-white';
    if (icir >= 0.5) return 'bg-yellow-500 text-white';
    return 'bg-gray-400 text-white';
  };

  // IC Time Series Chart Option
  const icChartOption = icSeries.length > 0 ? {
    title: {
      text: `IC Time Series: ${icSeriesData?.factor_name || selectedFactor || ''}`,
      left: 'center',
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0];
        return `${data.name}<br/>IC: ${formatNumber(data.value)}`;
      },
    },
    xAxis: {
      type: 'category',
      data: icSeries.map(p => p.date),
      axisLabel: {
        rotate: 45,
        fontSize: 10,
      },
    },
    yAxis: {
      type: 'value',
      name: 'IC',
      axisLine: {
        show: true,
      },
      splitLine: {
        lineStyle: {
          type: 'dashed',
        },
      },
    },
    series: [
      {
        name: 'IC',
        type: 'line',
        data: icSeries.map(p => p.ic),
        smooth: true,
        lineStyle: { width: 2 },
        itemStyle: { color: '#3b82f6' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
              { offset: 1, color: 'rgba(59, 130, 246, 0.05)' },
            ],
          },
        },
        markLine: {
          silent: true,
          lineStyle: { type: 'dashed', color: '#666' },
          data: [
            { yAxis: 0, label: { position: 'end', formatter: 'Zero' } },
          ],
        },
      },
    ],
    grid: {
      left: '8%',
      right: '8%',
      bottom: '18%',
      top: '15%',
    },
    dataZoom: [
      {
        type: 'inside',
        start: 0,
        end: 100,
      },
      {
        type: 'slider',
        start: 0,
        end: 100,
        bottom: 10,
      },
    ],
  } : null;

  // Correlation Heatmap Chart Option
  const heatmapOption = factorNames.length > 0 && correlationMatrix.length > 0 ? {
    title: {
      text: 'Factor Correlation Matrix',
      left: 'center',
    },
    tooltip: {
      position: 'top',
      formatter: (params: any) => {
        const [x, y, value] = params.data;
        return `${factorNames[x]} vs ${factorNames[y]}<br/>Correlation: ${formatNumber(value)}`;
      },
    },
    grid: {
      left: '15%',
      right: '15%',
      bottom: '25%',
      top: '10%',
    },
    xAxis: {
      type: 'category',
      data: factorNames,
      splitArea: { show: true },
      axisLabel: {
        rotate: 45,
        fontSize: 10,
      },
    },
    yAxis: {
      type: 'category',
      data: factorNames,
      splitArea: { show: true },
      axisLabel: {
        fontSize: 10,
      },
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '0%',
      inRange: {
        color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8',
                '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026'],
      },
    },
    series: [
      {
        name: 'Correlation',
        type: 'heatmap',
        data: (() => {
          const data: [number, number, number][] = [];
          for (let i = 0; i < factorNames.length; i++) {
            for (let j = 0; j < factorNames.length; j++) {
              data.push([i, j, correlationMatrix[i]?.[j] ?? 0]);
            }
          }
          return data;
        })(),
        label: {
          show: factorNames.length <= 15,
          fontSize: 8,
          formatter: (params: any) => formatNumber(params.value[2], 2),
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.5)',
          },
        },
      },
    ],
  } : null;

  // Handle row click
  const handleRowClick = (factor: FactorSummary) => {
    setSelectedFactor(factor.factor_name);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Factor Research</h1>
        <p className="text-muted-foreground">
          ICIR analysis, IC time series, and factor correlation
        </p>
      </div>

      {/* Summary Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Factors</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{factors.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg ICIR</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {factors.length > 0
                ? formatNumber(factors.reduce((sum, f) => sum + f.icir, 0) / factors.length, 2)
                : '--'}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">High ICIR (&gt;=1)</CardTitle>
            <TrendingUp className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-500">
              {factors.filter(f => f.icir >= 1).length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Correlation Matrix</CardTitle>
            <Grid3X3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{factorNames.length}x{factorNames.length}</div>
          </CardContent>
        </Card>
      </div>

      {/* ICIR Ranking Table */}
      <Card>
        <CardHeader>
          <CardTitle>ICIR Ranking Table</CardTitle>
          <CardDescription>
            Click on a row to view IC time series for that factor
          </CardDescription>
        </CardHeader>
        <CardContent>
          {summaryLoading ? (
            <div className="flex items-center justify-center h-40">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <span className="ml-2 text-muted-foreground">Loading factor summary...</span>
            </div>
          ) : summaryError ? (
            <div className="text-center py-8 text-destructive">
              Failed to load factor summary. Please check if the backend is running.
            </div>
          ) : factors.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No factor data available. Run the pipeline to generate factor analysis.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Factor Name</TableHead>
                  <TableHead className="text-right">IC Mean</TableHead>
                  <TableHead className="text-right">IC Std</TableHead>
                  <TableHead className="text-right">ICIR</TableHead>
                  <TableHead className="text-right">Positive Ratio</TableHead>
                  <TableHead className="text-right">Monotonicity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {factors.map((factor, idx) => (
                  <TableRow
                    key={factor.factor_name}
                    className={`cursor-pointer hover:bg-muted/50 ${
                      selectedFactor === factor.factor_name ? 'bg-muted/70' : ''
                    }`}
                    onClick={() => handleRowClick(factor)}
                  >
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground w-6">{idx + 1}.</span>
                        {factor.factor_name}
                      </div>
                    </TableCell>
                    <TableCell className={`text-right ${factor.ic_mean >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {formatNumber(factor.ic_mean)}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatNumber(factor.ic_std)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge className={getICIRBadge(factor.icir)}>
                        {formatNumber(factor.icir, 2)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={factor.positive_ratio >= 0.5 ? 'text-green-500' : 'text-red-500'}>
                        {formatPercent(factor.positive_ratio)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      {formatNumber(factor.monotonicity)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* IC Time Series Chart */}
      <Card>
        <CardHeader>
          <CardTitle>IC Time Series</CardTitle>
          <CardDescription>
            {selectedFactor
              ? `IC values over time for ${selectedFactor}`
              : 'Select a factor from the table above to view IC time series'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {icSeriesLoading ? (
            <div className="flex items-center justify-center h-[400px]">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : icChartOption ? (
            <ReactECharts
              option={icChartOption}
              style={{ height: '400px' }}
              opts={{ renderer: 'svg' }}
            />
          ) : (
            <div className="flex items-center justify-center h-[400px] text-muted-foreground">
              {selectedFactor ? 'No IC data available for this factor' : 'Select a factor to view IC series'}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Correlation Heatmap */}
      <Card>
        <CardHeader>
          <CardTitle>Factor Correlation Heatmap</CardTitle>
          <CardDescription>
            Correlation matrix between factors
          </CardDescription>
        </CardHeader>
        <CardContent>
          {correlationLoading ? (
            <div className="flex items-center justify-center h-[500px]">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : heatmapOption ? (
            <ReactECharts
              option={heatmapOption}
              style={{ height: '500px' }}
              opts={{ renderer: 'svg' }}
            />
          ) : (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              No correlation data available
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
