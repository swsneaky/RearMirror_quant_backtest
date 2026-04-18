import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { RefreshCw, Copy, Check, Play, Loader2, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import { useHPOStatus, useHPOTrials } from '@/hooks';

function getStatusBadgeVariant(status: string): 'default' | 'secondary' | 'outline' {
  switch (status) {
    case 'running':
      return 'default';
    case 'completed':
      return 'secondary';
    default:
      return 'outline';
  }
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'running':
      return 'Running';
    case 'completed':
      return 'Completed';
    default:
      return 'Not Started';
  }
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds.toFixed(0)}s`;
}

export function HPOPage() {
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: hpoStatus, isLoading: statusLoading, error: statusError, refetch: refetchStatus } = useHPOStatus();
  const { data: trialsData, isLoading: trialsLoading, error: trialsError, refetch: refetchTrials } = useHPOTrials();

  const isLoading = statusLoading || trialsLoading;
  const hasError = statusError || trialsError;

  const trials = useMemo(() => {
    if (!trialsData?.trials) return [];
    if (sortOrder === null) return trialsData.trials;

    return [...trialsData.trials].sort((a, b) => {
      if (a.state !== 'COMPLETE' && b.state !== 'COMPLETE') return 0;
      if (a.state !== 'COMPLETE') return 1;
      if (b.state !== 'COMPLETE') return -1;
      const aValue = a.value ?? -Infinity;
      const bValue = b.value ?? -Infinity;
      return sortOrder === 'asc' ? aValue - bValue : bValue - aValue;
    });
  }, [trialsData, sortOrder]);

  const bestTrialNumber = useMemo(() => {
    const completeTrials = trials.filter(t => t.state === 'COMPLETE' && t.value !== null);
    if (completeTrials.length === 0) return -1;
    const best = completeTrials.reduce((best, trial) =>
      (trial.value ?? -Infinity) > (best.value ?? -Infinity) ? trial : best
    );
    return best.number;
  }, [trials]);

  const bestParams = useMemo(() => {
    if (bestTrialNumber === -1) return null;
    const bestTrial = trials.find(t => t.number === bestTrialNumber);
    return bestTrial?.params ?? null;
  }, [trials, bestTrialNumber]);

  const handleSort = () => {
    const newSortOrder = sortOrder === 'desc' ? 'asc' : sortOrder === 'asc' ? null : 'desc';
    setSortOrder(newSortOrder);
  };

  const handleRefresh = async () => {
    await Promise.all([refetchStatus(), refetchTrials()]);
  };

  const handleCopyParams = async () => {
    if (!bestParams) return;
    await navigator.clipboard.writeText(JSON.stringify(bestParams, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleStartOptimization = () => {
    toast.info('This feature is not implemented yet. Please use the CLI to start a new optimization.');
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <span className="ml-2 text-muted-foreground">Loading HPO data...</span>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <AlertCircle className="h-12 w-12 text-destructive" />
        <div className="text-center">
          <h2 className="text-lg font-semibold">Failed to load HPO data</h2>
          <p className="text-muted-foreground">
            {statusError?.message || trialsError?.message || 'Unknown error'}
          </p>
        </div>
        <Button variant="outline" onClick={handleRefresh}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Retry
        </Button>
      </div>
    );
  }

  const displayStatus = hpoStatus?.status || {
    study_name: 'N/A',
    status: 'unknown',
    current_trial: 0,
    total_trials: 0,
    best_value: null,
    elapsed_seconds: 0,
    model: 'N/A',
    objective_metric: 'N/A',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">HPO Monitor</h1>
          <p className="text-muted-foreground">
            Hyperparameter Optimization Status and Results
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          <Button onClick={handleStartOptimization}>
            <Play className="h-4 w-4 mr-2" />
            New Optimization
          </Button>
        </div>
      </div>

      {/* Status Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Badge variant={getStatusBadgeVariant(displayStatus.status)}>
                {getStatusLabel(displayStatus.status)}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Model: {displayStatus.model}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Trials
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {displayStatus.current_trial} / {displayStatus.total_trials}
            </div>
            <p className="text-xs text-muted-foreground">
              Objective: {displayStatus.objective_metric}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Best Value
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {displayStatus.best_value !== null ? displayStatus.best_value.toFixed(2) : 'N/A'}
            </div>
            <p className="text-xs text-muted-foreground">
              {bestTrialNumber >= 0 ? `Trial #${bestTrialNumber}` : 'No completed trials'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Elapsed Time
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatDuration(displayStatus.elapsed_seconds)}
            </div>
            <p className="text-xs text-muted-foreground">
              {displayStatus.elapsed_seconds > 60 ? `${(displayStatus.elapsed_seconds / 60).toFixed(1)} minutes` : 'Less than a minute'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Trial Results Table */}
      <Card>
        <CardHeader>
          <CardTitle>Trial Results ({trials.length} trials)</CardTitle>
        </CardHeader>
        <CardContent>
          {trials.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No trials available. Start an optimization to see results.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Trial #</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>
                    <button
                      onClick={handleSort}
                      className="flex items-center gap-1 hover:text-foreground transition-colors"
                    >
                      Value
                      {sortOrder && (
                        <span className="text-xs">{sortOrder === 'asc' ? '^' : 'v'}</span>
                      )}
                    </button>
                  </TableHead>
                  {trials.length > 0 && Object.keys(trials[0].params).slice(0, 3).map(param => (
                    <TableHead key={param}>{param}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {trials.map((trial) => (
                  <TableRow
                    key={trial.number}
                    className={trial.number === bestTrialNumber ? 'bg-green-50 dark:bg-green-950/30' : ''}
                  >
                    <TableCell className="font-medium">
                      {trial.number}
                      {trial.number === bestTrialNumber && (
                        <Badge variant="secondary" className="ml-2 text-xs">Best</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={trial.state === 'COMPLETE' ? 'secondary' : 'outline'}>
                        {trial.state}
                      </Badge>
                    </TableCell>
                    <TableCell className={trial.number === bestTrialNumber ? 'font-bold text-green-600' : ''}>
                      {trial.value !== null ? trial.value.toFixed(2) : 'N/A'}
                    </TableCell>
                    {Object.entries(trial.params).slice(0, 3).map(([key, value]) => (
                      <TableCell key={key}>
                        {typeof value === 'number' ? value.toFixed(4) : value}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Best Parameters */}
      {bestParams && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Best Parameters</CardTitle>
            <Button variant="outline" size="sm" onClick={handleCopyParams}>
              {copied ? (
                <>
                  <Check className="h-4 w-4 mr-2 text-green-500" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4 mr-2" />
                  Copy
                </>
              )}
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="p-4 rounded-lg bg-muted overflow-x-auto text-sm">
              {JSON.stringify(bestParams, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
