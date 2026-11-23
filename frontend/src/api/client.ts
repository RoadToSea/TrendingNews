import type {
  CrawlClusterDoneEvent,
  CrawlSourceDoneEvent,
  CrawlStartEvent,
  CrawlTriggerResponse,
} from "@/api/types";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, message: string, code = "api_error") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function apiUrl(path: string): string {
  const base = (import.meta.env.BASE_URL || "/").replace(/\/+$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}/api${cleanPath}`;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const resp = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });

  if (resp.status === 401 && !path.startsWith("/auth/")) {
    window.dispatchEvent(new CustomEvent("trendradar:unauthorized"));
  }

  const text = await resp.text();
  let parsed: Record<string, unknown> | null = null;
  if (text) {
    try {
      parsed = JSON.parse(text) as Record<string, unknown>;
    } catch {
      parsed = null;
    }
  }

  if (!resp.ok) {
    const detail =
      (parsed && typeof parsed.detail === "string" && parsed.detail) ||
      `请求失败 (${resp.status})`;
    const code = (parsed && typeof parsed.code === "string" && parsed.code) || "http_error";
    throw new ApiError(resp.status, detail, code);
  }

  return (parsed ?? {}) as T;
}

async function consumeSSEStream(
  path: string,
  body: Record<string, unknown>,
  onEvent: (eventName: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
    signal,
  });

  if (!resp.ok) {
    if (resp.status === 401) {
      window.dispatchEvent(new CustomEvent("trendradar:unauthorized"));
    }
    const errText = await resp.text();
    let msg = `流式连接失败 (${resp.status})`;
    try {
      const json = JSON.parse(errText) as { detail?: string };
      if (json.detail) msg = json.detail;
    } catch {
      // ignore non-json error text
    }
    throw new ApiError(resp.status, msg);
  }

  const reader = resp.body?.getReader();
  if (!reader) {
    throw new Error("浏览器不支持流式响应读取");
  }

  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const processFrame = (rawFrame: string) => {
    const lines = rawFrame.split(/\r?\n/);
    let eventName = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (!line || line.startsWith(":")) continue;
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }

    if (dataLines.length === 0) return;
    try {
      const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      onEvent(eventName, data);
    } catch {
      // ignore malformed frame payload
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sepIdx = buffer.indexOf("\n\n");
    while (sepIdx !== -1) {
      const frame = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);
      processFrame(frame);
      sepIdx = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) {
    processFrame(buffer);
  }
}

export interface SSECallbacks {
  onInit?: (data: { session_id: number; external_conversation_id: string }) => void;
  onDelta: (text: string) => void;
  onDone: (data: { message_id: number; usage: Record<string, unknown> }) => void;
  onError: (message: string) => void;
}

export async function streamChatSSE(
  sessionId: number,
  body: Record<string, unknown>,
  callbacks: SSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  await consumeSSEStream(
    `/chat/sessions/${sessionId}/stream`,
    body,
    (eventName, data) => {
      if (eventName === "init") {
        callbacks.onInit?.(data as { session_id: number; external_conversation_id: string });
      } else if (eventName === "delta" && typeof data.text === "string") {
        callbacks.onDelta(data.text);
      } else if (eventName === "done") {
        callbacks.onDone(data as { message_id: number; usage: Record<string, unknown> });
      } else if (eventName === "error") {
        callbacks.onError(String(data.message || "AI 响应异常"));
      }
    },
    signal,
  );
}

export interface CrawlSSECallbacks {
  onStart?: (data: CrawlStartEvent) => void;
  onSourceDone: (data: CrawlSourceDoneEvent) => void;
  onClusterDone?: (data: CrawlClusterDoneEvent) => void;
  onDone: (summary: CrawlTriggerResponse) => void;
  onError: (message: string) => void;
}

export async function streamCrawlSSE(
  runCluster: boolean,
  callbacks: CrawlSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  await consumeSSEStream(
    "/jobs/crawl/stream",
    { run_cluster: runCluster },
    (eventName, data) => {
      if (eventName === "start") {
        callbacks.onStart?.(data as unknown as CrawlStartEvent);
      } else if (eventName === "source_done") {
        callbacks.onSourceDone(data as unknown as CrawlSourceDoneEvent);
      } else if (eventName === "cluster_done") {
        callbacks.onClusterDone?.(data as unknown as CrawlClusterDoneEvent);
      } else if (eventName === "done") {
        callbacks.onDone(data as unknown as CrawlTriggerResponse);
      } else if (eventName === "error") {
        callbacks.onError(String(data.message || "更新数据失败"));
      }
    },
    signal,
  );
}
