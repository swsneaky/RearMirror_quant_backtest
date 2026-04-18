import { X, TrendingUp, TrendingDown, Calendar, Database, BarChart3 } from 'lucide-react';

import { useStockDetail, useStockOHLC } from '@/hooks';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { KLineChart } from '@/components/KLineChart';

interface StockDetailDrawerProps {
  code: string | null;
  onClose: () => void;
}

export function StockDetailDrawer({ code, onClose }: StockDetailDrawerProps) {
  const { data: detail, isLoading } = useStockDetail(code);
  const { data: ohlc } = useStockOHLC(code, { limit: 500 });

  if (!code) return null;

  const formatPct = (v: number | null) => v !== null ? `${(v * 100).toFixed(2)}%` : '-';
  const formatVolume = (v: number | null) => {
    if (v === null) return '-';
    if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
    if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
    return v.toFixed(0);
  };
  const formatPrice = (v: number | null) => v !== null ? v.toFixed(2) : '-';

  return (
    <div className="fixed inset-y-0 right-0 w-[600px] bg-background border-l shadow-lg z-50 overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 bg-background border-b p-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold">{detail?.name || code}</h2>
          <p className="text-sm text-muted-foreground font-mono">{code}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Content */}
      <div className="p-4 space-y-4">
        {isLoading ? (
          <div className="text-center py-8 text-muted-foreground">加载中...</div>
        ) : detail ? (
          <>
            {/* Basic Info */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">基本信息</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground">行业</p>
                    <p className="font-medium">
                      {detail.industry ? (
                        <Badge variant="outline">{detail.industry}</Badge>
                      ) : '-'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">ST状态</p>
                    <Badge variant={detail.is_st ? 'destructive' : 'secondary'}>
                      {detail.is_st ? 'ST' : '正常'}
                    </Badge>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">最新价</p>
                    <p className="font-medium text-lg">{formatPrice(detail.latest_close)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">涨跌幅</p>
                    <p className={`font-medium ${detail.pct_chg && detail.pct_chg >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                      {detail.pct_chg !== null && (
                        <>
                          {detail.pct_chg >= 0 ? <TrendingUp className="inline h-4 w-4 mr-1" /> : <TrendingDown className="inline h-4 w-4 mr-1" />}
                          {formatPct(detail.pct_chg)}
                        </>
                      )}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Trading Data */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <BarChart3 className="h-4 w-4" />
                  交易数据
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground">成交量</p>
                    <p className="font-medium">{formatVolume(detail.volume)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">成交额</p>
                    <p className="font-medium">{formatVolume(detail.amount)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">换手率</p>
                    <p className="font-medium">{detail.turn !== null ? `${(detail.turn * 100).toFixed(2)}%` : '-'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">PE(TTM)</p>
                    <p className="font-medium">{detail.pe_ttm !== null ? detail.pe_ttm.toFixed(2) : '-'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">PB(MRQ)</p>
                    <p className="font-medium">{detail.pb_mrq !== null ? detail.pb_mrq.toFixed(2) : '-'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">PS(TTM)</p>
                    <p className="font-medium">{detail.ps_ttm !== null ? detail.ps_ttm.toFixed(2) : '-'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">PCF(TTM)</p>
                    <p className="font-medium">{detail.pcf_ttm !== null ? detail.pcf_ttm.toFixed(2) : '-'}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Data Range */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Calendar className="h-4 w-4" />
                  数据范围
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <Database className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">
                      {detail.date_range ? `${detail.date_range[0].slice(0, 10)} ~ ${detail.date_range[1].slice(0, 10)}` : '-'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      共 {detail.bar_count} 条日线数据
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* K-Line Chart */}
            <Card>
              <CardContent className="pt-4">
                <KLineChart code={code} bars={ohlc?.bars ?? []} height={350} />
              </CardContent>
            </Card>
          </>
        ) : (
          <div className="text-center py-8 text-muted-foreground">未找到数据</div>
        )}
      </div>
    </div>
  );
}
