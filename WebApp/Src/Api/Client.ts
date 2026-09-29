export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly requestId: string | null,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function requestFailure(failure: unknown, fallback: string): string {
  const message = failure instanceof Error ? failure.message : fallback;
  return failure instanceof ApiError && failure.requestId
    ? `${message} 请求编号：${failure.requestId}` : message;
}

export interface RequestOptions {
  token?: string;
  body?: unknown;
  signal?: AbortSignal;
  onUnauthorized?: () => void;
  onRequestId?: (requestId: string | null) => void;
}

export async function requestJson<T>(
  path: `/api/${string}` | "/health",
  method: "GET" | "POST",
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch {
    throw new ApiError(0, null, method === "POST"
      ? "连接中断，无法确认提交结果。请先查询研究、任务或审核状态，勿直接重复提交。"
      : "网络不可用，请检查后端服务后重新查询。");
  }

  const requestId = response.headers.get("X-Request-ID");
  options.onRequestId?.(requestId);
  if (response.status === 401) options.onUnauthorized?.();
  if (!response.ok) {
    const message = response.status === 401
      ? "身份已失效，请重新登录。"
      : response.status === 403
        ? "没有权限访问该资源。请确认账号、工作空间与知识库授权，反复提交不会获得权限。"
        : response.status === 404
          ? "未找到可访问的记录，请核对编号和数据范围；不能据此判断其他空间是否存在该记录。"
        : response.status === 409
          ? "当前状态或提交内容存在冲突，请先读取最新记录，勿直接重复提交。"
        : response.status === 429
          ? "请求过于频繁或预算已达上限，请稍后查询；勿连续重复提交。"
        : response.status >= 500
          ? method === "POST" ? "服务处理异常，提交结果可能不确定。请先核查研究、任务或审核状态，勿直接重复提交。" : "服务暂时不可用，请稍后重试。"
          : "请求内容无效，请检查输入。";
    throw new ApiError(response.status, requestId, message);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(response.status, requestId, method === "POST"
      ? "服务返回的数据格式不正确，无法确认提交结果。请先查询记录，勿直接重复提交。"
      : "服务返回的数据格式不正确，请保留请求编号并核查服务状态。");
  }
}
