import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { DomainItemCfg } from "@/components/settings/authoritativePresets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface DomainsManagerCardProps {
  domains: DomainItemCfg[];
  onChange: (next: DomainItemCfg[], immediate?: boolean) => void;
  onError: (msg: string) => void;
}

export function DomainsManagerCard({
  domains,
  onChange,
  onError,
}: DomainsManagerCardProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState("");
  const [descInput, setDescInput] = useState("");

  const openCreate = () => {
    onError("");
    setEditingId(null);
    setNameInput("");
    setDescInput("");
    setCreateOpen((v) => !v);
  };

  const toggleEdit = (item: DomainItemCfg) => {
    onError("");
    setCreateOpen(false);
    if (editingId === item.id) {
      setEditingId(null);
      return;
    }
    setEditingId(item.id);
    setNameInput(item.name);
    setDescInput(item.description);
  };

  const handleConfirm = (targetId: string | null) => {
    const cleanName = nameInput.trim();
    const cleanDesc = descInput.trim();
    if (!cleanName) {
      onError("请填写领域名称");
      return;
    }

    if (targetId === null) {
      if (domains.some((d) => d.id === cleanName || d.name === cleanName)) {
        onError(`领域 "${cleanName}" 已存在`);
        return;
      }
      onError("");
      onChange([...domains, { id: cleanName, name: cleanName, description: cleanDesc }], true);
      setCreateOpen(false);
    } else {
      onError("");
      onChange(
        domains.map((d) => (d.id === targetId ? { ...d, name: cleanName, description: cleanDesc } : d)),
        true,
      );
      setEditingId(null);
    }

    setNameInput("");
    setDescInput("");
  };

  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">领域分类字典</h3>
            <Badge variant="outline">{domains.length} 个领域</Badge>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">用于 RSS 归类、热点事件自动归并和趋势页分组查看</p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button size="sm" variant="outline" onClick={openCreate}>
            <Plus data-icon="inline-start" />
            <span>{createOpen ? "取消新增" : "新增领域"}</span>
          </Button>
        </div>
      </div>

      <FieldGroup>
        {createOpen && (
          <div className="flex flex-col gap-5 rounded-lg border border-primary/40 bg-muted/30 p-4 sm:p-5">
            <span className="text-base font-semibold">新增领域分类</span>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel>领域名称 *</FieldLabel>
                <Input
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  placeholder="例如：能源双碳 / 产业制造"
                />
              </Field>
              <Field className="sm:col-span-2">
                <FieldLabel>领域描述与归类提示</FieldLabel>
                <Textarea
                  value={descInput}
                  onChange={(e) => setDescInput(e.target.value)}
                  placeholder="说明该领域涵盖的核心主题或新闻范围，供 AI 自动归类参考"
                  className="min-h-16"
                />
              </Field>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setCreateOpen(false)}>
                取消
              </Button>
              <Button size="sm" onClick={() => handleConfirm(null)}>
                确认添加
              </Button>
            </div>
          </div>
        )}

        <div className="grid gap-2.5 sm:grid-cols-2">
          {domains.map((item) => {
            const isFallback = item.id === "其他";
            const isEditing = editingId === item.id;
            return (
              <div
                key={item.id}
                data-domain-id={item.id}
                className={cn(
                  "rounded-md border bg-card transition-colors",
                  isEditing
                    ? "sm:col-span-2 border-primary/60 ring-1 ring-primary/20"
                    : "border-border",
                )}
              >
                <div className="flex items-start justify-between gap-2 p-3">
                  <button
                    type="button"
                    aria-expanded={isEditing}
                    onClick={() => toggleEdit(item)}
                    className="flex min-w-0 flex-1 flex-col gap-1 text-left cursor-pointer"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-semibold">{item.name}</span>
                      {isFallback && <Badge variant="secondary">兜底分类</Badge>}
                    </div>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {item.description || "暂无描述"}
                    </p>
                  </button>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      type="button"
                      size="icon"
                      variant={isEditing ? "secondary" : "ghost"}
                      className="size-9"
                      aria-label={`编辑领域 ${item.name}`}
                      aria-expanded={isEditing}
                      onClick={() => toggleEdit(item)}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-9 text-muted-foreground hover:text-destructive"
                      disabled={isFallback}
                      title={isFallback ? "兜底分类不可删除" : `删除领域 ${item.name}`}
                      aria-label={`删除领域 ${item.name}`}
                      onClick={() => {
                        if (!window.confirm(`确定删除领域「${item.name}」吗？`)) return;
                        onChange(domains.filter((d) => d.id !== item.id), true);
                        if (isEditing) setEditingId(null);
                      }}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>

                {isEditing && (
                  <div
                    className="flex flex-col gap-5 border-t border-border bg-muted/20 p-4 sm:p-5"
                    data-inline-edit-domain={item.id}
                  >
                    <span className="text-base font-semibold">编辑领域：{item.name}</span>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field>
                        <FieldLabel>领域名称 *</FieldLabel>
                        <Input
                          value={nameInput}
                          onChange={(e) => setNameInput(e.target.value)}
                          placeholder="领域显示名称"
                        />
                      </Field>
                      <Field className="sm:col-span-2">
                        <FieldLabel>领域描述与归类提示</FieldLabel>
                        <Textarea
                          value={descInput}
                          onChange={(e) => setDescInput(e.target.value)}
                          placeholder="说明该领域涵盖的核心主题或新闻范围"
                          className="min-h-16"
                        />
                      </Field>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => setEditingId(null)}>
                        取消
                      </Button>
                      <Button size="sm" onClick={() => handleConfirm(item.id)}>
                        确认更新
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </FieldGroup>
    </Card>
  );
}
