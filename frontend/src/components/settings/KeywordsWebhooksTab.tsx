import { useEffect, useState } from "react";
import { Send } from "lucide-react";
import { settingsApi } from "@/api/endpoints";
import { KeywordsEditorCard } from "@/components/settings/KeywordsEditorCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useAutoSave } from "@/hooks/useAutoSave";

const WEBHOOK_FIELDS: { key: string; label: string; secret?: boolean }[] = [
  { key: "feishu_webhook_url", label: "飞书机器人地址 (Webhook)", secret: true },
  { key: "dingtalk_webhook_url", label: "钉钉机器人地址 (Webhook)", secret: true },
  { key: "wework_webhook_url", label: "企业微信机器人地址 (Webhook)", secret: true },
  { key: "telegram_bot_token", label: "Telegram 机器人令牌 (Token)", secret: true },
  { key: "telegram_chat_id", label: "Telegram 接收会话 ID" },
  { key: "email_from", label: "发件邮箱 (From)" },
  { key: "email_password", label: "邮箱密码/授权码", secret: true },
  { key: "email_to", label: "收件邮箱 (To)" },
  { key: "email_smtp_server", label: "SMTP 邮件服务器" },
  { key: "email_smtp_port", label: "SMTP 端口" },
  { key: "ntfy_server_url", label: "ntfy 服务地址" },
  { key: "ntfy_topic", label: "ntfy 订阅主题 (Topic)" },
  { key: "ntfy_token", label: "ntfy 访问令牌", secret: true },
  { key: "bark_url", label: "Bark 推送地址", secret: true },
  { key: "slack_webhook_url", label: "Slack 机器人地址 (Webhook)", secret: true },
  { key: "generic_webhook_url", label: "通用推送地址 (Webhook)", secret: true },
];

interface KeywordsWebhooksTabProps {
  onDirtyChange?: (dirty: boolean) => void;
}

export function KeywordsWebhooksTab({ onDirtyChange }: KeywordsWebhooksTabProps = {}) {
  const [kwText, setKwText] = useState("");
  const [includeRss, setIncludeRss] = useState(true);
  const [webhooks, setWebhooks] = useState<Record<string, unknown>>({});
  const [savedWebhooksJson, setSavedWebhooksJson] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);

  const keywordsAuto = useAutoSave<{ raw_text: string; include_rss: boolean }>({
    delayMs: 450,
    onSave: async (payload) => {
      await settingsApi.updateSection("keywords", payload);
    },
    keepaliveFlush: (payload) => {
      settingsApi.keepaliveUpdateSection("keywords", payload);
    },
  });

  useEffect(() => {
    Promise.all([settingsApi.getSection("keywords"), settingsApi.getSection("webhooks")])
      .then(([kw, wh]) => {
        const rawText = String(kw.payload.raw_text || "");
        const incRss = Boolean(kw.payload.include_rss ?? true);
        setKwText(rawText);
        setIncludeRss(incRss);
        keywordsAuto.hydrate({ raw_text: rawText, include_rss: incRss });
        setWebhooks(wh.payload);
        setSavedWebhooksJson(JSON.stringify(wh.payload));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载关键词与推送配置失败"));
    // Run once on initial mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const webhooksDirty =
    savedWebhooksJson !== "" && JSON.stringify(webhooks) !== savedWebhooksJson;

  useEffect(() => {
    onDirtyChange?.(keywordsAuto.dirty || webhooksDirty);
  }, [keywordsAuto.dirty, webhooksDirty, onDirtyChange]);

  useEffect(() => {
    if (!webhooksDirty) return;
    const warnBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [webhooksDirty]);

  const handleRawTextChange = (nextText: string, immediate = false) => {
    setKwText(nextText);
    keywordsAuto.queueSave({ raw_text: nextText, include_rss: includeRss }, { immediate });
  };

  const handleIncludeRssChange = (nextInclude: boolean) => {
    setIncludeRss(nextInclude);
    keywordsAuto.queueSave({ raw_text: kwText, include_rss: nextInclude }, { immediate: true });
  };

  const handleSaveWebhooks = async () => {
    setError("");
    setNotice("");
    try {
      const res = await settingsApi.updateSection("webhooks", webhooks);
      setWebhooks(res.payload);
      setSavedWebhooksJson(JSON.stringify(res.payload));
      setNotice("消息推送配置已加密保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存推送配置失败");
    }
  };

  const handleTestWebhook = async () => {
    setTesting(true);
    setError("");
    setNotice("");
    try {
      let autoSavedNotice = "";
      if (webhooksDirty) {
        const saved = await settingsApi.updateSection("webhooks", webhooks);
        setWebhooks(saved.payload);
        setSavedWebhooksJson(JSON.stringify(saved.payload));
        autoSavedNotice = "已先自动保存推送配置 · ";
      }
      const res = await settingsApi.testWebhook();
      setNotice(
        `${autoSavedNotice}测试结果：` +
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
      {(error || keywordsAuto.error) && (
        <Alert variant="destructive">{error || keywordsAuto.error}</Alert>
      )}
      {notice && <Alert variant="success">{notice}</Alert>}

      <KeywordsEditorCard
        rawText={kwText}
        includeRss={includeRss}
        saveStatus={keywordsAuto.status}
        onRawTextChange={handleRawTextChange}
        onKeepaliveFlush={(nextRaw) =>
          settingsApi.keepaliveUpdateSection("keywords", {
            raw_text: nextRaw,
            include_rss: includeRss,
          })
        }
        onIncludeRssChange={handleIncludeRssChange}
        onSave={() => void keywordsAuto.flushNow()}
      />

      <Card className="p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold">消息推送通知（飞书 / 钉钉 / 企业微信 / 邮箱等）</h3>
              {webhooksDirty && <Badge variant="warning">有未保存的推送修改</Badge>}
            </div>
            <p className="text-sm text-muted-foreground">
              支持 9 种常见通知渠道；涉及账号密钥，修改后请点击「保存推送配置」加密写入
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={handleTestWebhook} disabled={testing}>
              <Send data-icon="inline-start" />
              <span>{testing ? "发送中..." : "测试推送"}</span>
            </Button>
            <Button size="sm" onClick={handleSaveWebhooks}>
              保存推送配置
            </Button>
          </div>
        </div>

        <FieldGroup>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">开启消息推送通知</span>
            <Switch
              checked={Boolean(webhooks.enabled)}
              onCheckedChange={(v) => setWebhooks({ ...webhooks, enabled: v })}
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
                />
              </Field>
            ))}
          </div>
        </FieldGroup>
      </Card>
    </div>
  );
}
