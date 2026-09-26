import { ApiError } from './api.ts';
import { readReportStatus } from './reports.ts';
import type { ReportStatus } from './reports.ts';

type PollOptions = {
  taskId: string;
  version: number;
  token: string;
  onStatus: (status: ReportStatus) => void;
  onError: (message: string, retrying: boolean) => void;
  onExpired: (message: string) => void;
  onSettled: () => void;
  load?: typeof readReportStatus;
  schedule?: (run: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
};

export function startReportPolling(options: PollOptions): () => void {
  const controller = new AbortController();
  const load = options.load ?? readReportStatus;
  const schedule = options.schedule ?? setTimeout;
  const cancel = options.cancel ?? clearTimeout;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function update() {
    try {
      const result = await load(options.taskId, options.version, options.token, controller.signal);
      if (controller.signal.aborted) return;
      if (result.task_id !== options.taskId || result.review_version !== options.version) {
        options.onError('报告版本与当前任务不一致，请刷新。', false);
        return;
      }
      options.onStatus(result);
      if (result.reports.some(item => item.state === 'pending')) {
        timer = schedule(() => { void update(); }, 5000);
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 401) {
        options.onExpired(cause.message);
      } else {
        const retrying = !(cause instanceof ApiError) || cause.status === 0 || cause.status === 429 || cause.status >= 500;
        options.onError((cause as Error).message, retrying);
        if (retrying) timer = schedule(() => { void update(); }, 5000);
      }
    } finally {
      if (!controller.signal.aborted) options.onSettled();
    }
  }

  void update();
  return () => { controller.abort(); if (timer !== undefined) cancel(timer); };
}
