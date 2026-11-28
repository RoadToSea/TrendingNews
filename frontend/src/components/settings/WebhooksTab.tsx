import { useEffect, useState } from "react";
import { Send } from "lucide-react";
import { settingsApi } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

const WEBHOOK_FIELDS: { key: string; label: string; secret?: boolean }[] = [
  { key: "feishu_webhook_url", label: "飞书机器人地址 (Webhook)", secret: true },
  { key: "dingtalk_webhook_url", label: "钉钉机器人地址 (Webhook)", secret: true },
  { key: "wework_webhook_url", label: "企业微信机器人地址 (Webhook)", secret: true },
  { key: "generic_webhook_url", label: "通用推送地址 (Webhook)", secret: true },
];

export function WebhooksTab() {
  const [webhooks, setWebhooks] = useState<Record<string, unknown>>({});
  const [savedJson, setSavedJson] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    settingsApi
      .getSection("webhooks")
      .then((res) => {
        setWebhooks(res.payload);
        setSavedJson(JSON.stringify(res.payload));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载消息推送配置失败"));
  }, []);

  const persistWebhooks = async (nextPayload: Record<string, unknown>) => {
    setError("");
    try {
      const saved = await settingsApi.updateSection("webhooks", nextPayload);
      setWebhooks(saved.payload);
      setSavedJson(JSON.stringify(saved.payload));
      return saved.payload;
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存消息推送配置失败");
      return null;
    }
  };

  const handleToggleEnabled = async (enabled: boolean) => {
    const next = { ...webhooks, enabled };
    setWebhooks(next);
    await persistWebhooks(next);
  };

  const handleFieldBlur = async () => {
    if (!savedJson || JSON.stringify(webhooks) === savedJson) return;
    await persistWebhooks(webhooks);
  };

  const handleTestWebhook = async () => {
    setTesting(true);
    setError("");
    setNotice("");
    try {
      if (savedJson && JSON.stringify(webhooks) !== savedJson) {
        const saved = await persistWebhooks(webhooks);
        if (!saved) return;
      }
      const res = await settingsApi.testWebhook();
      setNotice(
        "测试结果：" +
          res.results.map((r) => `${r.channel}: ${r.success ? "成功" : r.message}`).join("；"),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送测试通知失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {error && <Alert variant="destructive">{error}</Alert>}
      {notice && <Alert variant="success">{notice}</Alert>}

      <Card className="p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-semibold">个人增量消息推送</h3>
            <p className="text-sm text-muted-foreground">
              仅推送您「关注话题」中新命中的热点增量（支持飞书、钉钉、企业微信与通用 Webhook，不重复推送）
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={handleTestWebhook} disabled={testing}>
            <Send data-icon="inline-start" />
            <span>{testing ? "发送中..." : "测试推送"}</span>
          </Button>
        </div>

        <FieldGroup>
          <div className="flex items-center justify-between rounded-lg border border-border bg-muted/15 px-4 py-3">
            <span className="text-sm font-medium">开启个人消息推送</span>
            <Switch
              checked={Boolean(webhooks.enabled)}
              onCheckedChange={(v) => void handleToggleEnabled(v)}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {WEBHOOK_FIELDS.map((f) => (
              <Field key={f.key}>
                <FieldLabel>{f.label}</FieldLabel>
                <Input
                  type={f.secret ? "password" : "text"}
                  value={String(webhooks[f.key] || "")}
                  onChange={(e) => setWebhooks({ ...webhooks, [f.key]: e.target.value })}
                  onBlur={() => void handleFieldBlur()}
                  placeholder="填写后离开输入框自动加密保存"
                />
              </Field>
            ))}
          </div>
        </FieldGroup>
      </Card>
    </div>
  );
}
