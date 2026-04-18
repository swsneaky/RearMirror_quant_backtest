import { useState, useEffect } from 'react';
import { RefreshCw, Search, TrendingUp, TrendingDown, Database, Building2, Calendar, ArrowDownUp, Loader2 } from 'lucide-react';

import { useStocks, useStockStats, useIndustries, useSyncStockNames, useUpdateStockData, useUpdateStatus } from '@/hooks';
import { useStocksPageStore } from '@/stores';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { StockDetailDrawer } from '@/components/StockDetailDrawer';
import { toast } from 'sonner';

export function StocksPage() {
  // Persistent State from Zustand
  const {
    page, setPage,
    search, setSearch,
    industry, setIndustry,
    sortBy, setSortBy,
    sortDesc, setSortDesc,
    selectedCode, setSelectedCode,
  } = useStocksPageStore();

  // Local state (not persisted)
  const [pageSize] = useState(20);
  const [searchInput, setSearchInput] = useState(search);

  // Queries
  const { data: stocksData, isLoading, refetch: refetchStocks } = useStocks({ page, page_size: pageSize, search, industry, sort_by: sortBy, sort_desc: sortDesc });
  const { data: stats, refetch: refetchStats } = useStockStats();
  const { data: industriesData } = useIndustries();
  const { data: updateStatus } = useUpdateStatus();

  // Mutations
  const syncNames = useSyncStockNames();
  const updateData = useUpdateStockData();

  // 当更新完成时刷新数据
  useEffect(() => {
    if (updateStatus && !updateStatus.success && updateStatus.total_stocks > 0 && updateStatus.updated_stocks === updateStatus.total_stocks) {
      refetchStocks();
      refetchStats();
    }
  }, [updateStatus, refetchStocks, refetchStats]);

  // Handlers
  const handleSearch = () => {
    setSearch(searchInput);
  };

  const handleSyncNames = async () => {
    try {
      const result = await syncNames.mutateAsync();
      toast.success(result.message);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '同步失败');
    }
  };

  const handleUpdateData = async () => {
    try {
      const result = await updateData.mutateAsync();
      if (result.success) {
        toast.success('更新任务已启动');
      } else {
        toast.info(result.message);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新失败');
    }
  };

  const totalPages = stocksData ? Math.ceil(stocksData.total / pageSize) : 0;

  // 判断是否正在更新
  const isUpdating = updateStatus && !updateStatus.success;
  const updateProgress = updateStatus?.total_stocks ? Math.round((updateStatus.updated_stocks / updateStatus.total_stocks) * 100) : 0;

  // Format helpers
  const formatPct = (v: number | null) => v !== null ? `${(v * 100).toFixed(2)}%` : '-';
  const formatVolume = (v: number | null) => {
    if (v === null) return '-';
    if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
    if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
    return v.toFixed(0);
  };
  const formatPrice = (v: number | null) => v !== null ? v.toFixed(2) : '-';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">股票数据</h1>
          <p className="text-muted-foreground">
            查看本地股票池、K线图和基本信息
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleSyncNames} disabled={syncNames.isPending || isUpdating}>
            <ArrowDownUp className="h-4 w-4 mr-2" />
            同步名称与行业
          </Button>
          <Button size="sm" onClick={handleUpdateData} disabled={isUpdating}>
            {isUpdating ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                更新中 {updateProgress}%
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4 mr-2" />
                更新数据
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Update Progress */}
      {isUpdating && (
        <Card className="border-primary/50 bg-primary/5">
          <CardContent className="pt-4">
            <div className="flex items-center gap-4">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <div className="flex-1">
                <div className="flex justify-between text-sm mb-1">
                  <span>{updateStatus?.message}</span>
                  <span className="text-muted-foreground">
                    {updateStatus?.updated_stocks}/{updateStatus?.total_stocks}
                    {updateStatus?.skipped_stocks ? ` (跳过 ${updateStatus.skipped_stocks})` : ''}
                  </span>
                </div>
                <div className="w-full bg-muted rounded-full h-2">
                  <div
                    className="bg-primary h-2 rounded-full transition-all"
                    style={{ width: `${updateProgress}%` }}
                  />
                </div>
                {updateStatus?.total_bars ? (
                  <div className="text-xs text-muted-foreground mt-1">
                    已新增 {updateStatus.total_bars} 条数据
                  </div>
                ) : null}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">总股票数</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_stocks ?? 0}</div>
            <p className="text-xs text-muted-foreground">
              {stats?.with_names ?? 0} 已同步名称
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">行业分布</CardTitle>
            <Building2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{Object.keys(stats?.by_industry ?? {}).length}</div>
            <p className="text-xs text-muted-foreground">
              个行业
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">数据范围</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-sm font-medium truncate">
              {stats?.date_range ? stats.date_range[0].slice(0, 10) : '-'} ~ {stats?.date_range ? stats.date_range[1].slice(0, 10) : '-'}
            </div>
            <p className="text-xs text-muted-foreground">
              {stats?.total_bars ? `${(stats.total_bars / 10000).toFixed(0)}万条` : '0条'} 日线数据
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">数据状态</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <Badge variant={stats?.with_names === stats?.total_stocks ? 'default' : 'secondary'}>
              {stats?.with_names === stats?.total_stocks ? '完整' : '待完善'}
            </Badge>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs font-medium text-muted-foreground mb-1 block">搜索</label>
              <div className="flex gap-2">
                <Input
                  placeholder="代码或名称..."
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                />
                <Button size="sm" onClick={handleSearch}><Search className="h-4 w-4" /></Button>
              </div>
            </div>
            <div className="w-[150px]">
              <label className="text-xs font-medium text-muted-foreground mb-1 block">行业</label>
              <Select value={industry} onChange={(e) => setIndustry(e.target.value)}>
                <option value="">全部行业</option>
                {(industriesData?.industries ?? []).map((ind) => (
                  <option key={ind} value={ind}>{ind}</option>
                ))}
              </Select>
            </div>
            <div className="w-[120px]">
              <label className="text-xs font-medium text-muted-foreground mb-1 block">排序</label>
              <Select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="code">代码</option>
                <option value="latest_close">最新价</option>
                <option value="pct_chg">涨跌幅</option>
                <option value="turn">换手率</option>
                <option value="bar_count">数据量</option>
              </Select>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSortDesc(!sortDesc)}
            >
              {sortDesc ? '降序' : '升序'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Stock Table */}
      <Card>
        <CardHeader>
          <CardTitle>股票列表</CardTitle>
          <CardDescription>
            共 {stocksData?.total ?? 0} 只股票
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-8 text-muted-foreground">加载中...</div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead>行业</TableHead>
                    <TableHead className="text-right">最新价</TableHead>
                    <TableHead className="text-right">涨跌幅</TableHead>
                    <TableHead className="text-right">成交量</TableHead>
                    <TableHead className="text-right">换手率</TableHead>
                    <TableHead className="text-right">PE(TTM)</TableHead>
                    <TableHead className="text-right">PB</TableHead>
                    <TableHead className="text-right">日线数</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stocksData?.stocks.map((stock) => (
                    <TableRow
                      key={stock.code}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => setSelectedCode(stock.code)}
                    >
                      <TableCell className="font-mono">
                        {stock.code}
                        {stock.is_delisted && (
                          <Badge variant="outline" className="ml-2 text-xs text-muted-foreground">退市</Badge>
                        )}
                      </TableCell>
                      <TableCell>{stock.name || '-'}</TableCell>
                      <TableCell>
                        {stock.industry && (
                          <Badge variant="outline" className="text-xs">{stock.industry}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">{formatPrice(stock.latest_close)}</TableCell>
                      <TableCell className="text-right">
                        {stock.pct_chg !== null && (
                          <span className={stock.pct_chg >= 0 ? 'text-red-500' : 'text-green-500'}>
                            {stock.pct_chg >= 0 ? <TrendingUp className="inline h-3 w-3 mr-1" /> : <TrendingDown className="inline h-3 w-3 mr-1" />}
                            {formatPct(stock.pct_chg)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">{formatVolume(stock.volume)}</TableCell>
                      <TableCell className="text-right">{stock.turn !== null ? `${(stock.turn * 100).toFixed(2)}%` : '-'}</TableCell>
                      <TableCell className="text-right">{stock.pe_ttm !== null ? stock.pe_ttm.toFixed(2) : '-'}</TableCell>
                      <TableCell className="text-right">{stock.pb_mrq !== null ? stock.pb_mrq.toFixed(2) : '-'}</TableCell>
                      <TableCell className="text-right">{stock.bar_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {/* Pagination */}
              <div className="flex items-center justify-between mt-4">
                <div className="text-sm text-muted-foreground">
                  第 {page} 页，共 {totalPages} 页
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page <= 1}
                    onClick={() => setPage(page - 1)}
                  >
                    上一页
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page >= totalPages}
                    onClick={() => setPage(page + 1)}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Stock Detail Drawer */}
      <StockDetailDrawer
        code={selectedCode}
        onClose={() => setSelectedCode(null)}
      />
    </div>
  );
}
