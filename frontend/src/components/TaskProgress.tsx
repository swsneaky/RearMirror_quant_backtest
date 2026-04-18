import { Loader2, Square } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useCancelTask, useTasks } from '@/hooks';
import type { TaskResponse } from '@/api/client';

function statusVariant(status: TaskResponse['status']) {
  if (status === 'failed' || status === 'cancelled') return 'destructive';
  if (status === 'succeeded') return 'default';
  return 'secondary';
}

export function TaskProgress() {
  const { data, isLoading, isError } = useTasks();
  const cancelTask = useCancelTask();
  const tasks = data?.tasks ?? [];
  const latestTasks = tasks.slice(0, 5);

  const handleCancel = (taskId: string) => {
    cancelTask.mutate(taskId, {
      onSuccess: () => toast.success(`Task ${taskId} cancelled`),
      onError: (error) => toast.error(error.message),
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Task Progress
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </CardTitle>
        <CardDescription>Recent UI-triggered jobs and their progress.</CardDescription>
      </CardHeader>
      <CardContent>
        {isError ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            Failed to load task status.
          </div>
        ) : latestTasks.length === 0 ? (
          <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No task has been submitted yet.
          </div>
        ) : (
          <div className="space-y-3">
            {latestTasks.map((task) => {
              const canCancel = task.status === 'pending' || task.status === 'running';
              return (
                <div key={task.task_id} className="rounded-lg border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm">{task.task_id}</span>
                        <Badge variant={statusVariant(task.status)}>{task.status}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {task.steps || 'no steps'} · {task.universe_name || 'unknown universe'}
                      </p>
                    </div>
                    {canCancel && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => handleCancel(task.task_id)}
                        disabled={cancelTask.isPending}
                      >
                        <Square className="h-3.5 w-3.5" />
                        Cancel
                      </Button>
                    )}
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${task.progress_pct}%` }}
                    />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                    <span>{task.progress_message || 'Waiting for progress update'}</span>
                    <span>{task.progress_pct}%</span>
                  </div>
                  {task.error_message && (
                    <p className="mt-2 text-xs text-destructive">{task.error_message}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
