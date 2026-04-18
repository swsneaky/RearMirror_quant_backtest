import { useDataLayers, useCacheStats, useHealth, useCreateTask, useTasks } from '@/hooks';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { RefreshCw, Database, HardDrive, Activity, CheckCircle, AlertTriangle, Link, Play, Loader2, Trash2, Pause } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/api/client';

export function DataLayersPage() {
  const { data: layersData, isLoading: layersLoading, isError: layersError, error: layersErrorMsg, refetch: refetchLayers } = useDataLayers();
  const { data: cacheStats, refetch: refetchCache } = useCacheStats();
  const { data: health } = useHealth();
  const { data: tasksData } = useTasks();
  const createTask = useCreateTask();

  const handleRefresh = () => {
    refetchLayers();
    refetchCache();
  };

  // 检查是否有正在运行的任务（包括暂停的）
  const runningTasks = tasksData?.tasks?.filter(t => t.status === 'running' || t.status === 'pending' || t.status === 'paused') ?? [];
  const isTaskRunning = runningTasks.length > 0;

  // 触发任务
  const handleCreateTask = async (taskType: string, steps: string[], notes: string) => {
    try {
      const result = await createTask.mutateAsync({
        task_type: taskType,
        steps,
        notes,
      });
      toast.success(`任务已创建: ${result.task_id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '任务创建失败');
    }
  };

  // 杀进程并清理
  const handleKillAndCleanup = async (taskId: string) => {
    try {
      const result = await api.killAndCleanup(taskId);
      toast.success(result.message || '已终止并清理');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '操作失败');
    }
  };

  // 暂停任务
  const handlePauseTask = async (taskId: string) => {
    try {
      const result = await api.pauseTask(taskId);
      toast.success(result.message || '已暂停');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '操作失败');
    }
  };

  // 恢复任务
  const handleResumeTask = async (taskId: string) => {
    try {
      const result = await api.resumeTask(taskId);
      toast.success(result.message || '已恢复');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '操作失败');
    }
  };

  const layers = layersData?.layers ? Object.entries(layersData.layers) : [];
  const summary = layersData?.summary;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Data Layers</h1>
          <p className="text-muted-foreground">
            数据层状态监控：Raw → Canonical → Feature → Label
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm">
            <Activity className={`h-4 w-4 ${health?.status === 'ok' ? 'text-green-500' : 'text-red-500'}`} />
            <span className="text-muted-foreground">API: {health?.status ?? 'checking...'}</span>
          </div>
          <Button onClick={handleRefresh} variant="outline" size="sm">
            <RefreshCw className="h-4 w-4 mr-2" />
            刷新状态
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">数据层总数</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary?.total_layers ?? 0}</div>
            <p className="text-xs text-muted-foreground">
              {summary?.needs_update ?? 0} 个需要更新
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">缓存大小</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{cacheStats?.total_size_human ?? '0 B'}</div>
            <p className="text-xs text-muted-foreground">
              {cacheStats?.file_count ?? 0} 个文件
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">数据状态</CardTitle>
            {summary?.all_up_to_date ? (
              <CheckCircle className="h-4 w-4 text-green-500" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
            )}
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {summary?.all_up_to_date ? '最新' : '待更新'}
            </div>
            <p className="text-xs text-muted-foreground">
              {summary?.all_up_to_date ? '所有数据层已是最新' : '部分数据层需要更新'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">数据链路</CardTitle>
            <Link className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-sm space-y-1">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs">Raw</Badge>
                <span className="text-muted-foreground">→</span>
                <Badge variant="outline" className="text-xs">Canonical</Badge>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs">Feature</Badge>
                <span className="text-muted-foreground">→</span>
                <Badge variant="outline" className="text-xs">Label</Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Data Flow Diagram */}
      <Card>
        <CardHeader>
          <CardTitle>数据流转</CardTitle>
          <CardDescription>
            数据从原始层到标签层的处理流程
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center gap-4 py-4">
            {['Raw', 'Canonical', 'Feature', 'Label'].map((stage, idx) => (
              <div key={stage} className="flex items-center gap-4">
                <div className={`flex flex-col items-center p-4 rounded-lg border ${
                  idx === 3 ? 'bg-primary/10 border-primary' : 'bg-muted/50'
                }`}>
                  <Database className="h-8 w-8 mb-2 text-muted-foreground" />
                  <span className="font-medium">{stage}</span>
                  <span className="text-xs text-muted-foreground">
                    {stage === 'Raw' && '原始日线'}
                    {stage === 'Canonical' && '规范化数据'}
                    {stage === 'Feature' && '因子矩阵'}
                    {stage === 'Label' && '预测标签'}
                  </span>
                </div>
                {idx < 3 && (
                  <div className="flex flex-col items-center text-muted-foreground">
                    <span className="text-xs">处理</span>
                    <span className="text-lg">→</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Tabs: Layers + Cache */}
      <Tabs defaultValue="layers" className="space-y-4">
        <TabsList>
          <TabsTrigger value="layers">数据层详情</TabsTrigger>
          <TabsTrigger value="cache">缓存信息</TabsTrigger>
        </TabsList>

        <TabsContent value="layers">
          <Card>
            <CardHeader>
              <CardTitle>数据层资产状态</CardTitle>
              <CardDescription>
                各数据层的输出文件、指纹和更新状态
              </CardDescription>
            </CardHeader>
            <CardContent>
              {layersLoading ? (
                <div className="text-center py-8 text-muted-foreground">加载中...</div>
              ) : layersError ? (
                <div className="text-center py-8 text-red-500">
                  加载失败: {layersErrorMsg?.message}
                </div>
              ) : layers.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  暂无数据层信息，请先运行数据处理流程
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>数据层</TableHead>
                      <TableHead>输出文件</TableHead>
                      <TableHead>指纹</TableHead>
                      <TableHead>上游变更</TableHead>
                      <TableHead>配置变更</TableHead>
                      <TableHead>更新状态</TableHead>
                      <TableHead>原因</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {layers.map(([name, status]) => (
                      <TableRow key={name}>
                        <TableCell className="font-medium">{status.layer_name}</TableCell>
                        <TableCell>
                          <Badge variant={status.output_exists ? 'default' : 'destructive'}>
                            {status.output_exists ? '存在' : '缺失'}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={status.fingerprint_exists ? 'default' : 'destructive'}>
                            {status.fingerprint_exists ? '存在' : '缺失'}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={status.upstream_changed ? 'destructive' : 'secondary'}>
                            {status.upstream_changed ? '已变更' : '稳定'}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={status.config_changed ? 'destructive' : 'secondary'}>
                            {status.config_changed ? '已变更' : '稳定'}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={status.needs_update ? 'destructive' : 'default'}>
                            {status.needs_update ? '需更新' : '最新'}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm max-w-xs truncate">
                          {status.reason || '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="cache">
          <Card>
            <CardHeader>
              <CardTitle>缓存统计</CardTitle>
              <CardDescription>
                缓存目录和存储信息
              </CardDescription>
            </CardHeader>
            <CardContent>
              {cacheStats ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">缓存路径</p>
                      <p className="text-sm font-mono">{cacheStats.path}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">指纹</p>
                      <p className="text-sm font-mono truncate">{cacheStats.fingerprint || 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">总大小</p>
                      <p className="text-sm">{cacheStats.total_size_human}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">文件数</p>
                      <p className="text-sm">{cacheStats.file_count}</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-muted-foreground mb-2">状态</p>
                    <Badge variant={cacheStats.exists ? 'default' : 'destructive'}>
                      {cacheStats.exists ? '缓存存在' : '缓存缺失'}
                    </Badge>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  暂无缓存信息
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Task Triggers */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            数据任务
          </CardTitle>
          <CardDescription>
            触发数据处理流程
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-4">
            <Button
              onClick={() => handleCreateTask('data_update', ['download', 'etl'], '增量更新原始数据')}
              disabled={isTaskRunning || createTask.isPending}
            >
              {createTask.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4 mr-2" />
              )}
              数据更新
            </Button>
            <Button
              onClick={() => handleCreateTask('feature_compute', ['raw_feature', 'neutralize'], '计算特征矩阵')}
              disabled={isTaskRunning || createTask.isPending}
              variant="outline"
            >
              {createTask.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Database className="h-4 w-4 mr-2" />
              )}
              特征计算
            </Button>
          </div>

          {/* 任务进度显示 */}
          {runningTasks.length > 0 && (
            <div className="space-y-3 pt-2">
              {runningTasks.map((task) => (
                <div key={task.task_id} className="space-y-1 p-3 rounded-lg border bg-muted/30">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-mono text-xs text-muted-foreground">
                      {task.task_id}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{task.progress_pct}%</span>
                      {/* 任务控制按钮 */}
                      <div className="flex gap-1 ml-2">
                        {task.status === 'running' && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6"
                            onClick={() => handlePauseTask(task.task_id)}
                            title="暂停"
                          >
                            <Pause className="h-3 w-3" />
                          </Button>
                        )}
                        {task.status === 'paused' && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6"
                            onClick={() => handleResumeTask(task.task_id)}
                            title="恢复"
                          >
                            <Play className="h-3 w-3" />
                          </Button>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 text-destructive hover:text-destructive"
                          onClick={() => handleKillAndCleanup(task.task_id)}
                          title="终止并清理"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  </div>
                  <div className="h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary transition-all duration-300"
                      style={{ width: `${task.progress_pct}%` }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {task.progress_message || '准备中...'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Quick Links */}
      <Card>
        <CardHeader>
          <CardTitle>快速导航</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4">
            <a href="/stocks" className="text-sm text-primary hover:underline">
              → 查看股票列表
            </a>
            <a href="/training-sets" className="text-sm text-primary hover:underline">
              → 创建训练集
            </a>
            <a href="/model-training" className="text-sm text-primary hover:underline">
              → 开始训练
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
