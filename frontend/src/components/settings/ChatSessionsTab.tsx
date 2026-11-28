import { useCallback, useEffect, useState } from "react";
import { MessageSquare, Trash2 } from "lucide-react";
import { chatApi } from "@/api/endpoints";
import type { ChatSessionDTO } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { useSelection } from "@/context/SelectionContext";
import { formatShortTime } from "@/lib/utils";

export function ChatSessionsTab() {
  const { openChatSession } = useSelection();
  const [sessions, setSessions] = useState<ChatSessionDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSessions(await chatApi.listSessions());
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载对话会话列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const handleDelete = async (session: ChatSessionDTO) => {
    if (!window.confirm(`确定删除对话「${session.title}」吗？`)) return;
    setBusyId(session.id);
    setError("");
    try {
      await chatApi.deleteSession(session.id);
      setSessions((prev) => prev.filter((item) => item.id !== session.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除会话失败");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert variant="destructive">{error}</Alert>}

      <p className="text-sm text-muted-foreground tabular-nums">
        共 {sessions.length} 个个人历史对话会话。
      </p>

      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : sessions.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          暂无历史对话会话，可在任意热点页面打开右下角「AI 研判助手」发起对话。
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {sessions.map((session) => (
            <Card
              key={session.id}
              className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate font-semibold text-foreground">{session.title}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  最近更新：{formatShortTime(session.updated_at)} · 创建：{formatShortTime(session.created_at)}
                </span>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => openChatSession(session.id)}
                >
                  <MessageSquare data-icon="inline-start" />
                  <span>打开对话</span>
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground hover:text-destructive"
                  disabled={busyId === session.id}
                  onClick={() => void handleDelete(session)}
                >
                  <Trash2 data-icon="inline-start" />
                  <span>删除</span>
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
