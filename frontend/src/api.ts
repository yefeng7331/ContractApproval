import type { Task } from './model.ts';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export async function fetchResponse(path: string, token: string | null, signal?: AbortSignal, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    const timeout = AbortSignal.timeout(15000);
    response = await fetch(`/api/v1${path}`, { ...init, headers, signal: signal ? AbortSignal.any([signal, timeout]) : timeout, cache: 'no-store', credentials: 'omit' });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, '无法连接服务，请确认后端已启动后重试。');
  }
  if (!response.ok) {
    const messages: Record<number, string> = { 401: '登录已失效，请重新登录。', 403: '当前账号无权访问此内容。', 404: '任务不存在或当前账号不可见。', 422: '输入不符合要求，请检查后重试。' };
    let message = messages[response.status] ?? '服务暂时不可用，请稍后重试。';
    if ([409, 413, 415, 422].includes(response.status)) {
      const detail = await response.json().catch(() => null);
      if (typeof detail?.message === 'string') message = detail.message;
    }
    throw new ApiError(response.status, message);
  }
  return response;
}

export async function request<T>(path: string, token: string | null, signal?: AbortSignal, init: RequestInit = {}): Promise<T> {
  const response = await fetchResponse(path, token, signal, init);
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch { throw new ApiError(0, '服务响应无法读取，请确认 API 地址正确。'); }
}

// ponytail: collect visible summaries for the local demo; use a server aggregate
// endpoint when task volume makes full-list reads too costly. Never count one page as all tasks.
export async function loadTasks(token: string, signal: AbortSignal): Promise<Task[]> {
  const tasks = new Map<string, Task>();
  let offset = 0;
  while (true) {
    const page = await request<{ items: Task[]; total: number }>(`/tasks?limit=100&offset=${offset}`, token, signal);
    for (const task of page.items) tasks.set(task.task_id, task);
    offset += page.items.length;
    if (offset >= page.total) return [...tasks.values()];
    if (!page.items.length) throw new ApiError(0, '任务列表发生变化，请刷新后重试。');
  }
}
