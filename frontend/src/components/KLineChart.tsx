import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import type { OHLCBar } from '@/api/client';

interface KLineChartProps {
  code: string;
  bars: OHLCBar[];
  height?: number;
}

export function KLineChart({ code, bars, height = 400 }: KLineChartProps) {
  const option = useMemo(() => {
    if (!bars.length) return {};

    // 计算均线
    const calculateMA = (data: number[], period: number) => {
      const result: (number | null)[] = [];
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push(null);
        } else {
          const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
          result.push(sum / period);
        }
      }
      return result;
    };

    const dates = bars.map(b => b.date.slice(0, 10));
    const closes = bars.map(b => b.close);

    const ma5 = calculateMA(closes, 5);
    const ma10 = calculateMA(closes, 10);
    const ma20 = calculateMA(closes, 20);
    const ma60 = calculateMA(closes, 60);

    // K线数据: [open, close, low, high]
    const klineData = bars.map(b => [b.open, b.close, b.low, b.high]);

    // 成交量数据，根据涨跌着色
    const volumeData = bars.map((b) => ({
      value: b.volume,
      itemStyle: {
        color: b.close >= b.open ? '#ef4444' : '#22c55e', // 红涨绿跌
      },
    }));

    return {
      animation: false,
      legend: {
        data: ['K线', 'MA5', 'MA10', 'MA20', 'MA60'],
        top: 10,
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderColor: '#333',
        textStyle: {
          color: '#fff',
        },
        formatter: (params: unknown[]) => {
          const p = params as { seriesName: string; data: unknown; dataIndex: number }[];
          const idx = p[0]?.dataIndex ?? 0;
          const bar = bars[idx];
          if (!bar) return '';
          return `
            <div style="font-family: monospace;">
              <div style="font-weight: bold; margin-bottom: 4px;">${bar.date.slice(0, 10)}</div>
              <div>开盘: ${bar.open.toFixed(2)}</div>
              <div>收盘: ${bar.close.toFixed(2)}</div>
              <div>最高: ${bar.high.toFixed(2)}</div>
              <div>最低: ${bar.low.toFixed(2)}</div>
              <div>涨跌: ${(bar.pct_chg * 100).toFixed(2)}%</div>
              <div>成交量: ${(bar.volume / 10000).toFixed(0)}万</div>
              <div>换手率: ${(bar.turn * 100).toFixed(2)}%</div>
            </div>
          `;
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
      },
      grid: [
        {
          left: '10%',
          right: '8%',
          top: '15%',
          height: '50%',
        },
        {
          left: '10%',
          right: '8%',
          top: '72%',
          height: '18%',
        },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { onZero: false },
          splitLine: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          boundaryGap: false,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
      ],
      yAxis: [
        {
          scale: true,
          splitArea: {
            show: true,
          },
        },
        {
          scale: true,
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 80,
          end: 100,
        },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          bottom: '2%',
          start: 80,
          end: 100,
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: klineData,
          itemStyle: {
            color: '#ef4444', // 红色上涨
            color0: '#22c55e', // 绿色下跌
            borderColor: '#ef4444',
            borderColor0: '#22c55e',
          },
        },
        {
          name: 'MA5',
          type: 'line',
          data: ma5,
          smooth: true,
          lineStyle: { width: 1 },
          showSymbol: false,
        },
        {
          name: 'MA10',
          type: 'line',
          data: ma10,
          smooth: true,
          lineStyle: { width: 1 },
          showSymbol: false,
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma20,
          smooth: true,
          lineStyle: { width: 1 },
          showSymbol: false,
        },
        {
          name: 'MA60',
          type: 'line',
          data: ma60,
          smooth: true,
          lineStyle: { width: 1 },
          showSymbol: false,
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeData,
        },
      ],
    };
  }, [bars]);

  if (!bars.length) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        暂无K线数据
      </div>
    );
  }

  return (
    <div>
      <div className="text-sm font-medium mb-2">{code} K线图</div>
      <ReactECharts
        option={option}
        style={{ height }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
