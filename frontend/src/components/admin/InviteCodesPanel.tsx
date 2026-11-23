import { useCallback, useEffect, useState } from "react";
import { Copy, Link2, Pencil, Plus, Trash2 } from "lucide-react";
import { adminApi } from "@/api/endpoints";
import type {
  InviteCodeCreatePayload,
  InviteCodeDTO,
  InviteCodeStatus,
  InviteCodeUpdatePayload,
} from "@/api/types";
import { InviteCodeDialog } from "@/components/admin/InviteCodeDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { Switch } from "@/components/ui/switch";
import { formatShortTime } from "@/lib/utils";

const STATUS_META: Record<
  InviteCodeStatus,
  { label: string; variant: "success" | "secondary" | "warning" | "outline" }
> = {
  active: { label: "有效", variant: "success" },
  exhausted: { label: "已用完", variant: "secondary" },
  expired: { label: "已过期", variant: "warning" },
  disabled: { label: "已停用", variant: "outline" },
};

function buildRegisterUrl(code: string): string {
  const base = (import.meta.env.BASE_URL || "/").replace(/\/+$/, "");
  return `${window.location.origin}${base}/register?code=${encodeURIComponent(code)}`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Admin panel listing, creating, updating, and revoking registration invite codes. */
export function InviteCodesPanel() {
  const [codes, setCodes] = useState<InviteCodeDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<InviteCodeDTO | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadCodes = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCodes(await adminApi.listInviteCodes());
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载邀请码列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCodes();
  }, [loadCodes]);

  const handleSave = async (
    payload: InviteCodeCreatePayload | InviteCodeUpdatePayload,
    editId?: number,
  ) => {
    setNotice("");
    if (editId !== undefined) {
      const updated = await adminApi.updateInviteCode(editId, payload as InviteCodeUpdatePayload);
      setCodes((prev) => prev.map((item) => (item.id === editId ? updated : item)));
      setNotice(`已更新邀请码 ${updated.code}`);
      return;
    }
    const created = await adminApi.createInviteCode(payload as InviteCodeCreatePayload);
    setCodes((prev) => [created, ...prev]);
    setNotice(`已创建邀请码 ${created.code}`);
  };

  const handleToggleActive = async (item: InviteCodeDTO, checked: boolean) => {
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      const updated = await adminApi.updateInviteCode(item.id, { is_active: checked });
      setCodes((prev) => prev.map((c) => (c.id === item.id ? updated : c)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新邀请码状态失败");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (item: InviteCodeDTO) => {
    if (!window.confirm(`确定删除邀请码 ${item.code} 吗？已通过该邀请码注册的账号不受影响。`)) {
      return;
    }
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      await adminApi.deleteInviteCode(item.id);
      setCodes((prev) => prev.filter((c) => c.id !== item.id));
      setNotice(`已删除邀请码 ${item.code}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除邀请码失败");
    } finally {
      setBusyId(null);
    }
  };

  const activeCount = codes.filter((c) => c.status === "active").length;

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert variant="destructive">{error}</Alert>}
      {notice && <Alert variant="success">{notice}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm text-muted-foreground tabular-nums">
          共 {codes.length} 个邀请码，其中有效 {activeCount} 个
        </span>
        <Button
          size="sm"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus data-icon="inline-start" />
          <span>新建邀请码</span>
        </Button>
      </div>

      {loading ? (
        <Skeleton className="h-56 w-full" />
      ) : codes.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          暂无邀请码，请点击右上角「新建邀请码」发放注册资格。
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {codes.map((item) => {
            const meta = STATUS_META[item.status];
            const usageText =
              item.max_uses === 0
                ? `已用 ${item.used_count} 次（不限上限）`
                : `已用 ${item.used_count} / ${item.max_uses} 次`;
            const expiryText = item.expires_at
              ? `有效期至 ${formatShortTime(item.expires_at)}`
              : "永不过期";

            return (
              <Card key={item.id} className="flex flex-col gap-3 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-col gap-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="rounded bg-muted px-2 py-0.5 font-mono text-sm font-semibold tracking-wider text-foreground">
                        {item.code}
                      </code>
                      <Badge variant={meta.variant}>{meta.label}</Badge>
                      {item.note && (
                        <span className="text-sm font-medium text-foreground">{item.note}</span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground tabular-nums">
                      <span>{usageText}</span>
                      <span>{expiryText}</span>
                      <span>创建于 {formatShortTime(item.created_at)}</span>
                      {item.created_by_username && <span>签发人：{item.created_by_username}</span>}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {item.is_active ? "启用" : "停用"}
                    </span>
                    <Switch
                      checked={item.is_active}
                      disabled={busyId === item.id}
                      onCheckedChange={(checked) => void handleToggleActive(item, checked)}
                      aria-label={`切换邀请码 ${item.code} 状态`}
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      void copyText(item.code).then((ok) =>
                        setNotice(ok ? `已复制邀请码 ${item.code}` : "复制失败，请手动选中复制"),
                      );
                    }}
                  >
                    <Copy data-icon="inline-start" />
                    <span>复制邀请码</span>
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      void copyText(buildRegisterUrl(item.code)).then((ok) =>
                        setNotice(
                          ok ? `已复制 ${item.code} 的注册链接` : "复制链接失败，请手动复制",
                        ),
                      );
                    }}
                  >
                    <Link2 data-icon="inline-start" />
                    <span>复制注册链接</span>
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditing(item);
                      setDialogOpen(true);
                    }}
                  >
                    <Pencil data-icon="inline-start" />
                    <span>调整次数/时间</span>
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    disabled={busyId === item.id}
                    onClick={() => void handleDelete(item)}
                  >
                    <Trash2 data-icon="inline-start" />
                    <span>删除</span>
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <InviteCodeDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        onSubmit={handleSave}
      />
    </div>
  );
}
