import React, { useEffect, useState } from "react";
import type {
  InviteCodeCreatePayload,
  InviteCodeDTO,
  InviteCodeUpdatePayload,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

/** Props for creating or editing an admin invite code. */
export interface InviteCodeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: InviteCodeDTO | null;
  onSubmit: (
    payload: InviteCodeCreatePayload | InviteCodeUpdatePayload,
    editId?: number,
  ) => Promise<void>;
}

const USE_PRESETS = [
  { label: "1 次", value: "1" },
  { label: "5 次", value: "5" },
  { label: "10 次", value: "10" },
  { label: "不限次", value: "0" },
] as const;

const HOURS_PRESET_MAP: Record<string, number> = {
  "1h": 1,
  "24h": 24,
  "168h": 168,
  "720h": 720,
};

function defaultCustomExpiryLocal(): string {
  const dt = new Date(Date.now() + 24 * 3600 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

function resolveExpiryFields(
  preset: string,
  customExpiry: string,
): { expires_in_hours?: number; expires_at?: string; clear_expires_at?: boolean } {
  if (preset === "keep") return {};
  if (preset === "never") return { clear_expires_at: true };
  if (preset === "custom") return { expires_at: customExpiry };
  const hours = HOURS_PRESET_MAP[preset];
  return hours ? { expires_in_hours: hours } : {};
}

/** Modal form allowing administrators to create or reconfigure invite quotas and expiry. */
export function InviteCodeDialog({
  open,
  onOpenChange,
  editing,
  onSubmit,
}: InviteCodeDialogProps) {
  const [customCode, setCustomCode] = useState("");
  const [note, setNote] = useState("");
  const [maxUses, setMaxUses] = useState("1");
  const [expiryPreset, setExpiryPreset] = useState("24h");
  const [customExpiry, setCustomExpiry] = useState(defaultCustomExpiryLocal);
  const [isActive, setIsActive] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    if (editing) {
      setCustomCode(editing.code);
      setNote(editing.note);
      setMaxUses(String(editing.max_uses));
      setExpiryPreset("keep");
      setCustomExpiry(defaultCustomExpiryLocal());
      setIsActive(editing.is_active);
    } else {
      setCustomCode("");
      setNote("");
      setMaxUses("1");
      setExpiryPreset("24h");
      setCustomExpiry(defaultCustomExpiryLocal());
      setIsActive(true);
    }
  }, [open, editing]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const parsedMax = Number(maxUses);
    if (!Number.isInteger(parsedMax) || parsedMax < 0 || parsedMax > 10000) {
      setError("有效次数需为 0 至 10000 的整数（0 表示不限次）");
      return;
    }
    if (editing && parsedMax > 0 && parsedMax < editing.used_count) {
      setError(`最大有效次数不能小于已使用次数 (${editing.used_count})`);
      return;
    }
    if (expiryPreset === "custom" && !customExpiry) {
      setError("请选择具体的截止日期与时间");
      return;
    }

    const expiryFields = resolveExpiryFields(expiryPreset, customExpiry);
    setSubmitting(true);
    try {
      if (editing) {
        await onSubmit(
          {
            note: note.trim(),
            max_uses: parsedMax,
            is_active: isActive,
            ...expiryFields,
          },
          editing.id,
        );
      } else {
        await onSubmit({
          code: customCode.trim() || undefined,
          note: note.trim(),
          max_uses: parsedMax,
          expires_in_hours: expiryFields.expires_in_hours,
          expires_at: expiryFields.expires_at,
        });
      }
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存邀请码失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? `调整邀请码 ${editing.code}` : "新建注册邀请码"}</DialogTitle>
          <DialogDescription>
            设置邀请码的可使用次数（0 代表不限次数）和有效期截止时间。
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <FieldGroup>
            {error && <Alert variant="destructive">{error}</Alert>}

            {!editing && (
              <Field>
                <FieldLabel htmlFor="invite-custom-code">自定义邀请码（可选）</FieldLabel>
                <FieldDescription>留空则自动生成 8 位易读随机码（如 TR-XXXX-XXXX）</FieldDescription>
                <Input
                  id="invite-custom-code"
                  placeholder="留空自动生成"
                  className="font-mono uppercase"
                  value={customCode}
                  onChange={(e) => setCustomCode(e.target.value.toUpperCase())}
                />
              </Field>
            )}

            <Field>
              <FieldLabel htmlFor="invite-note">用途备注（可选）</FieldLabel>
              <Input
                id="invite-note"
                placeholder="例如：投研组新成员试用"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="invite-max-uses">最大有效次数</FieldLabel>
              <FieldDescription>填 0 表示不限制次数，仅受过期时间约束</FieldDescription>
              <div className="flex flex-wrap gap-1.5 pb-1">
                {USE_PRESETS.map((preset) => (
                  <Button
                    key={preset.value}
                    type="button"
                    size="sm"
                    variant={maxUses === preset.value ? "default" : "outline"}
                    onClick={() => setMaxUses(preset.value)}
                  >
                    {preset.label}
                  </Button>
                ))}
              </div>
              <Input
                id="invite-max-uses"
                type="number"
                min={0}
                max={10000}
                value={maxUses}
                onChange={(e) => setMaxUses(e.target.value)}
              />
            </Field>

            <Field>
              <FieldLabel>有效期设置</FieldLabel>
              <Select value={expiryPreset} onValueChange={setExpiryPreset}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {editing && <SelectItem value="keep">保持当前有效期不变</SelectItem>}
                    <SelectItem value="1h">1 小时内有效</SelectItem>
                    <SelectItem value="24h">24 小时内有效</SelectItem>
                    <SelectItem value="168h">7 天内有效</SelectItem>
                    <SelectItem value="720h">30 天内有效</SelectItem>
                    <SelectItem value="never">永不过期</SelectItem>
                    <SelectItem value="custom">自定义截止时间</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>

            {expiryPreset === "custom" && (
              <Field>
                <FieldLabel htmlFor="invite-custom-expiry">截止日期与时间</FieldLabel>
                <Input
                  id="invite-custom-expiry"
                  type="datetime-local"
                  value={customExpiry}
                  onChange={(e) => setCustomExpiry(e.target.value)}
                  required
                />
              </Field>
            )}

            {editing && (
              <div className="flex items-center justify-between gap-3 pt-1">
                <span className="text-sm font-medium">启用该邀请码</span>
                <Switch checked={isActive} onCheckedChange={setIsActive} />
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={submitting}
              >
                取消
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "正在保存..." : editing ? "保存调整" : "创建邀请码"}
              </Button>
            </DialogFooter>
          </FieldGroup>
        </form>
      </DialogContent>
    </Dialog>
  );
}
