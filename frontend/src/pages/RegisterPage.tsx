import React, { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";

const USERNAME_PATTERN = /^[A-Za-z0-9_.-]{3,32}$/;

/** Invite-only account registration page with automatic post-signup login. */
export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [inviteCode, setInviteCode] = useState(() => (searchParams.get("code") || "").toUpperCase());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const codeParam = searchParams.get("code");
    if (codeParam) {
      setInviteCode(codeParam.trim().toUpperCase());
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const cleanUser = username.trim();
    const cleanCode = inviteCode.trim().toUpperCase();

    if (!USERNAME_PATTERN.test(cleanUser)) {
      setError("用户名需为 3-32 位字母、数字、下划线、点或短横线");
      return;
    }
    if (password.length < 8) {
      setError("密码长度至少为 8 位");
      return;
    }
    if (password !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }
    if (!cleanCode) {
      setError("请填写管理员提供的邀请码");
      return;
    }

    setSubmitting(true);
    try {
      await register(cleanUser, password, cleanCode);
      navigate("/platforms", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败，请检查信息后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-background px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <div className="mb-1 flex items-center gap-2">
            <span className="inline-flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
              TR
            </span>
            <CardTitle className="text-lg">注册 TrendRadar 账号</CardTitle>
          </div>
          <CardDescription>本站采用邀请制注册，请填写管理员签发的邀请码</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit}>
            <FieldGroup>
              {error && <Alert variant="destructive">{error}</Alert>}
              <Field>
                <FieldLabel htmlFor="register-username">用户名</FieldLabel>
                <FieldDescription>3-32 位字母、数字、下划线、点或短横线</FieldDescription>
                <Input
                  id="register-username"
                  autoComplete="username"
                  placeholder="例如：alice_01"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="register-password">登录密码</FieldLabel>
                <FieldDescription>至少 8 个字符</FieldDescription>
                <Input
                  id="register-password"
                  type="password"
                  autoComplete="new-password"
                  placeholder="请输入密码（至少 8 位）"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="register-confirm-password">确认密码</FieldLabel>
                <Input
                  id="register-confirm-password"
                  type="password"
                  autoComplete="new-password"
                  placeholder="请再次输入密码"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="register-invite-code">邀请码</FieldLabel>
                <Input
                  id="register-invite-code"
                  placeholder="例如：TR-XXXX-XXXX"
                  className="font-mono uppercase tracking-wider"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                  required
                />
              </Field>
              <Button type="submit" disabled={submitting} className="w-full">
                {submitting ? "正在注册..." : "注册并登录"}
              </Button>
              <p className="text-center text-sm text-muted-foreground">
                已有账号？
                <Link to="/login" className="ml-1 font-medium text-primary hover:underline">
                  返回登录
                </Link>
              </p>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
