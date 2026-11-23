import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { chatApi, settingsApi } from "@/api/endpoints";
import type { DomainInfoDTO, ReportDTO } from "@/api/types";
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

interface SaveReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionId: number | null;
  defaultTitle: string;
  providerSlotId?: number;
}

export function SaveReportDialog({
  open,
  onOpenChange,
  sessionId,
  defaultTitle,
  providerSlotId,
}: SaveReportDialogProps) {
  const [title, setTitle] = useState(defaultTitle);
  const [domain, setDomain] = useState("");
  const [domains, setDomains] = useState<DomainInfoDTO[]>([]);
  const [autoSummarize, setAutoSummarize] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedReport, setSavedReport] = useState<ReportDTO | null>(null);

  useEffect(() => {
    if (open) {
      setTitle(defaultTitle ? `对话研判：${defaultTitle}` : "对话研判归档报告");
      setError("");
      setSavedReport(null);
      settingsApi
        .getSection<{ items?: DomainInfoDTO[] }>("domains")
        .then((res) => setDomains(res.payload.items || []))
        .catch(() => {});
    }
  }, [open, defaultTitle]);

  const handleSave = async () => {
    if (!sessionId) return;
    setSaving(true);
    setError("");
    try {
      const rep = await chatApi.saveReport(sessionId, {
        title: title.trim() || undefined,
        domain: domain.trim(),
        auto_summarize: autoSummarize,
        provider_slot_id: providerSlotId,
      });
      setSavedReport(rep);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存报告失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>将本次对话生成并存为报告</DialogTitle>
          <DialogDescription>
            报告将直接写入后端 SQLite 报告归档库，可在“报告与词频”页面回溯查看。
          </DialogDescription>
        </DialogHeader>

        {savedReport ? (
          <div className="flex flex-col gap-3">
            <Alert variant="success">
              已保存报告《{savedReport.title}》（日期：{savedReport.report_date}）。
            </Alert>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                关闭
              </Button>
              <Button asChild onClick={() => onOpenChange(false)}>
                <Link to={`/reports?id=${savedReport.id}`}>前往报告页查看</Link>
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <FieldGroup>
            {error && <Alert variant="destructive">{error}</Alert>}
            <Field>
              <FieldLabel htmlFor="save-rep-title">报告标题</FieldLabel>
              <Input
                id="save-rep-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="输入归档标题"
              />
            </Field>
            <Field>
              <FieldLabel>归属领域（可选）</FieldLabel>
              {domains.length > 0 ? (
                <Select
                  value={domain || "__NONE__"}
                  onValueChange={(v) => setDomain(v === "__NONE__" ? "" : v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="不指定领域" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="__NONE__">不指定领域</SelectItem>
                      {domains.map((d) => (
                        <SelectItem key={d.id} value={d.id}>
                          {d.name}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id="save-rep-domain"
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="例如：AI大模型、科技互联网"
                />
              )}
            </Field>
            <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5">
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">由 AI 提炼结构化报告</span>
                <FieldDescription>关闭时直接按当前对话记录归档</FieldDescription>
              </div>
              <Switch checked={autoSummarize} onCheckedChange={setAutoSummarize} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
                取消
              </Button>
              <Button onClick={handleSave} disabled={saving || !sessionId}>
                {saving ? "正在生成归档..." : "确认保存"}
              </Button>
            </DialogFooter>
          </FieldGroup>
        )}
      </DialogContent>
    </Dialog>
  );
}
