import { ApiError } from './api.ts';
import type { Role } from './model.ts';
import { readWriteback, readWritebackTargets, validateWritebackStatus } from './writeback.ts';
import type { WritebackStatus, WritebackTarget } from './writeback.ts';

type PollOptions = {
  taskId: string;
  documentVersion: number;
  reviewVersion: number;
  role: Role;
  token: string;
  onStatus: (status: WritebackStatus) => void;
  onTargets: (targets: WritebackTarget[], boundId: string | null) => void;
  onError: (message: string, retrying: boolean) => void;
  onExpired: (message: string) => void;
  onStart: () => void;
  onSettled: () => void;
  load?: typeof readWriteback;
  loadTargets?: typeof readWritebackTargets;
  schedule?: (run: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
};

export function startWritebackPolling(options: PollOptions): () => void {
  const controller = new AbortController();
  const load = options.load ?? readWriteback;
  const loadTargets = options.loadTargets ?? readWritebackTargets;
  const schedule = options.schedule ?? setTimeout;
  const cancel = options.cancel ?? clearTimeout;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function update() {
    if (controller.signal.aborted) return;
    options.onStart();
    try {
      const response = await load(options.taskId, options.reviewVersion, options.token, controller.signal);
      if (controller.signal.aborted) return;
      let result: WritebackStatus;
      try {
        result = validateWritebackStatus(response, options.taskId, options.documentVersion, options.reviewVersion);
      } catch (cause) {
        options.onError((cause as Error).message, false);
        return;
      }
      options.onStatus(result);
      if (options.role === 'legal' && !result.mock_approval_id) {
        const targets = await loadTargets(options.token, controller.signal);
        if (controller.signal.aborted) return;
        options.onTargets(targets.items, null);
      } else {
        options.onTargets([], result.mock_approval_id);
      }
      if (result.state === 'writing') timer = schedule(() => { void update(); }, 5000);
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
