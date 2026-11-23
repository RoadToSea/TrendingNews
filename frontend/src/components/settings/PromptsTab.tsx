import { useCallback, useEffect, useState } from "react";
import { Plus, Star, Trash2 } from "lucide-react";
import { aiConfigApi } from "@/api/endpoints";
import type { PromptTemplateDTO } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

export function PromptsTab() {
  const [templates, setTemplates] = useState<PromptTemplateDTO[]>([]);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<PromptTemplateDTO | null>(null);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadPrompts = useCallback(async () => {
    try {
      setTemplates(await aiConfigApi.listPrompts());
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载提示词模板失败");
    }
  }, []);

  useEffect(() => {
    void loadPrompts();
  }, [loadPrompts]);

  const openNew = () => {
    setEditing(null);
    setName("");
    setContent("");
    setIsDefault(false);
    setModalOpen(true);
  };

  const openEdit = (tpl: PromptTemplateDTO) => {
    setEditing(tpl);
    setName(tpl.name);
    setContent(tpl.content);
    setIsDefault(tpl.is_default);
    setModalOpen(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      if (editing) {
        await aiConfigApi.updatePrompt(editing.id, {
          name: name.trim(),
          content: content.trim(),
          is_default: isDefault,
        });
      } else {
        await aiConfigApi.createPrompt({
          name: name.trim(),
          content: content.trim(),
          is_default: isDefault,
          is_enabled: true,
        });
      }
      setModalOpen(false);
      await loadPrompts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存提示词模板失败");
    } finally {
      setSaving(false);
    }
  };

  const handleSetDefault = async (tpl: PromptTemplateDTO) => {
    try {
      await aiConfigApi.updatePrompt(tpl.id, { is_default: true });
      await loadPrompts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "设默认失败");
    }
  };

  const handleDelete = async (tpl: PromptTemplateDTO) => {
    if (!window.confirm(`确定删除提示词模板「${tpl.name}」吗？`)) return;
    try {
      await aiConfigApi.deletePrompt(tpl.id);
      await loadPrompts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert variant="destructive">{error}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          定义 AI 助手开启新对话时默认带入的开场分析要求与角色指令。
        </p>
        <Button size="sm" onClick={openNew}>
          <Plus data-icon="inline-start" />
          <span>新增模板</span>
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {templates.map((tpl) => (
          <Card key={tpl.id} className="flex flex-col justify-between gap-3 p-4">
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{tpl.name}</span>
                {tpl.is_default && <Badge variant="default">默认模板</Badge>}
              </div>
              <p className="line-clamp-4 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                {tpl.content}
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-border pt-2.5">
              {!tpl.is_default && (
                <Button size="sm" variant="outline" onClick={() => void handleSetDefault(tpl)}>
                  <Star data-icon="inline-start" />
                  <span>设为默认</span>
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => openEdit(tpl)}>
                编辑
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="size-9 text-muted-foreground hover:text-destructive"
                aria-label={`删除提示词 ${tpl.name}`}
                onClick={() => void handleDelete(tpl)}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          </Card>
        ))}
      </div>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "编辑提示词模板" : "新增开场提示词模板"}</DialogTitle>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="tpl-name">模板名称</FieldLabel>
              <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field>
              <FieldLabel htmlFor="tpl-content">系统提示词内容</FieldLabel>
              <Textarea
                id="tpl-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                className="min-h-32"
              />
            </Field>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">设为默认开场模板</span>
              <Switch checked={isDefault} onCheckedChange={setIsDefault} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setModalOpen(false)}>
                取消
              </Button>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "保存中..." : "保存"}
              </Button>
            </DialogFooter>
          </FieldGroup>
        </DialogContent>
      </Dialog>
    </div>
  );
}
