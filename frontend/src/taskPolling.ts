import { ApiError, loadTasks } from './api.ts';
import { isActive } from './model.ts';
import type { Task } from './model.ts';

type PollOptions = {
  token: string;
  onTasks: (tasks: Task[]) => void;
  onError: (message: string) => void;
  onExpired: (message: string) => void;
  onForbidden: (message: string) => void;
  onSettled: () => void;
  load?: (token: string, signal: AbortSignal) => Promise<Task[]>;
  schedule?: (run: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
};

export function startTaskPolling(options: PollOptions): () => void {
  const controller = new AbortController();
  const load = options.load ?? loadTasks;
  const schedule = options.schedule ?? setTimeout;
  const cancel = options.cancel ?? clearTimeout;
  let timer: ReturnType<typeof setTimeout> | undefined;
  async function update() {
    try {
      const tasks = await load(options.token, controller.signal);
      if (controller.signal.aborted) return;
      options.onTasks(tasks);
      if (tasks.some(isActive)) timer = schedule(() => { void update(); }, 5000);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) options.onExpired(error.message);
      else if (error instanceof ApiError && error.status === 403) options.onForbidden(error.message);
      else {
        options.onError((error as Error).message);
        // The last visible list may be stale; retry even if it had no active tasks.
        timer = schedule(() => { void update(); }, 5000);
      }
    } finally {
      if (!controller.signal.aborted) options.onSettled();
    }
  }
  void update();
  return () => { controller.abort(); if (timer !== undefined) cancel(timer); };
}
