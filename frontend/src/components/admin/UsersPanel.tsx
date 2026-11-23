import { useCallback, useEffect, useState } from "react";
import { adminApi } from "@/api/endpoints";
import type { AdminUserDTO, UserRole } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/context/AuthContext";
import { formatShortTime } from "@/lib/utils";

/** Admin panel listing registered users with inline role and active-state controls. */
export function UsersPanel() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUserDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setUsers(await adminApi.listUsers());
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载用户列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const handlePatch = async (
    target: AdminUserDTO,
    patch: { is_active?: boolean; role?: UserRole },
  ) => {
    setSavingId(target.id);
    setError("");
    setNotice("");
    try {
      const updated = await adminApi.updateUser(target.id, patch);
      setUsers((prev) => prev.map((u) => (u.id === target.id ? updated : u)));
      setNotice(`已更新账号 ${updated.username} 的权限状态`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新账号状态失败");
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert variant="destructive">{error}</Alert>}
      {notice && <Alert variant="success">{notice}</Alert>}

      <p className="text-sm text-muted-foreground tabular-nums">
        共 {users.length} 个账号，停用账号将立即使对方当前登录会话失效。
      </p>

      {loading ? (
        <Skeleton className="h-56 w-full" />
      ) : (
        <div className="flex flex-col gap-3">
          {users.map((u) => {
            const isSelf = currentUser?.id === u.id;
            return (
              <Card
                key={u.id}
                className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-foreground">{u.username}</span>
                    {isSelf && <Badge variant="outline">当前账号</Badge>}
                    <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                      {u.role === "admin" ? "管理员" : "普通成员"}
                    </Badge>
                    <Badge variant={u.is_active ? "success" : "warning"}>
                      {u.is_active ? "已启用" : "已停用"}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground tabular-nums">
                    <span>
                      来源：
                      {u.invited_by_code ? `邀请码 ${u.invited_by_code}` : "初始 / 系统创建"}
                    </span>
                    <span>注册：{formatShortTime(u.created_at)}</span>
                    <span>
                      最近登录：{u.last_login_at ? formatShortTime(u.last_login_at) : "尚未登录"}
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <div className="w-32">
                    <Select
                      value={u.role}
                      disabled={isSelf || savingId === u.id}
                      onValueChange={(val) => void handlePatch(u, { role: val as UserRole })}
                    >
                      <SelectTrigger aria-label={`设置 ${u.username} 角色`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value="user">普通成员</SelectItem>
                          <SelectItem value="admin">管理员</SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {u.is_active ? "启用" : "停用"}
                    </span>
                    <Switch
                      checked={u.is_active}
                      disabled={isSelf || savingId === u.id}
                      onCheckedChange={(checked) => void handlePatch(u, { is_active: checked })}
                      aria-label={`切换账号 ${u.username} 启用状态`}
                    />
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
