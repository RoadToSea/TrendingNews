import { useState } from "react";
import { authApi } from "@/api/endpoints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";

export function AccountTab() {
  const { user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const handleChangePassword = async () => {
    setError("");
    setNotice("");
    try {
      await authApi.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setNotice("登录密码已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改密码失败");
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {error && <Alert variant="destructive">{error}</Alert>}
      {notice && <Alert variant="success">{notice}</Alert>}

      <Card className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">当前登录账号：</span>
          <span className="font-semibold text-foreground">{user?.username}</span>
          <Badge variant={user?.role === "admin" ? "default" : "secondary"}>
            {user?.role === "admin" ? "管理员" : "普通成员"}
          </Badge>
        </div>
      </Card>

      <Card className="p-4 sm:p-5">
        <h3 className="mb-3 text-base font-semibold">修改登录密码</h3>
        <FieldGroup>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field>
              <FieldLabel>当前密码</FieldLabel>
              <Input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel>新密码（至少 8 位）</FieldLabel>
              <Input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </Field>
          </div>
          <div>
            <Button
              size="sm"
              variant="outline"
              onClick={handleChangePassword}
              disabled={!currentPassword || newPassword.length < 8}
            >
              更新密码
            </Button>
          </div>
        </FieldGroup>
      </Card>
    </div>
  );
}
