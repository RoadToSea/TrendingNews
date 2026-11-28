import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Code2,
  ListFilter,
  Plus,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import {
  createEmptySimpleGroup,
  getSimpleGroupTitle,
  parseSimpleKeywordDocument,
  parseTermDisplay,
  serializeSimpleKeywordDocument,
  validateRegexLiteral,
  type SimpleKeywordConfig,
  type SimpleKeywordGroup,
  type SimpleKeywordTerm,
} from "@/lib/keywords";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

interface KeywordsEditorCardProps {
  rawText: string;
  includeRss: boolean;
  onRawTextChange: (next: string, immediate?: boolean) => void;
  onKeepaliveFlush?: (nextRawText: string) => void;
  onIncludeRssChange: (next: boolean) => void;
}

interface SimpleTermEditorProps {
  label: string;
  terms: SimpleKeywordTerm[];
  placeholder: string;
  addButtonText: string;
  allowExactToggle?: boolean;
  badgeVariant?: "outline" | "secondary" | "destructive" | "warning" | "default";
  onChange: (next: SimpleKeywordTerm[], immediate?: boolean) => void;
  onUnloadCommit?: (next: SimpleKeywordTerm[]) => void;
}

function buildNextTermsFromDraft(
  cleanDraft: string,
  currentTerms: SimpleKeywordTerm[],
  allowExactToggle: boolean,
  exactWord: boolean,
): { terms: SimpleKeywordTerm[]; error: string } | null {
  if (!cleanDraft) return null;

  if (cleanDraft.startsWith("/")) {
    const regexErr = validateRegexLiteral(cleanDraft);
    if (regexErr) {
      return { terms: currentTerms, error: regexErr };
    }
  }

  const pieces =
    cleanDraft.startsWith("/") && cleanDraft.lastIndexOf("/") > 0
      ? [cleanDraft]
      : cleanDraft
          .split(/[,，、\n\s]+/)
          .map((s) => s.trim())
          .filter(Boolean);

  const existingKeys = new Set(
    currentTerms.map((t) =>
      t.rawRegex ? `raw:${t.rawRegex}` : `${t.exactWord ? "1" : "0"}:${t.text.toLowerCase()}`,
    ),
  );
  const next = [...currentTerms];
  for (const token of pieces) {
    let term: SimpleKeywordTerm;
    if (token.startsWith("/") && token.lastIndexOf("/") > 0) {
      const regexErr = validateRegexLiteral(token);
      if (regexErr) {
        return { terms: currentTerms, error: regexErr };
      }
      const parsed = parseTermDisplay(token);
      term = {
        text: parsed.displayAlias || parsed.expression,
        exactWord: false,
        rawRegex: parsed.raw,
      };
    } else {
      term = { text: token, exactWord: allowExactToggle && exactWord };
    }

    const key = term.rawRegex
      ? `raw:${term.rawRegex}`
      : `${term.exactWord ? "1" : "0"}:${term.text.toLowerCase()}`;
    if (!existingKeys.has(key)) {
      existingKeys.add(key);
      next.push(term);
    }
  }
  return { terms: next, error: "" };
}

function SimpleTermEditor({
  label,
  terms,
  placeholder,
  addButtonText,
  allowExactToggle = false,
  badgeVariant = "outline",
  onChange,
  onUnloadCommit,
}: SimpleTermEditorProps) {
  const [draft, setDraft] = useState("");
  const [exactWord, setExactWord] = useState(false);
  const [draftError, setDraftError] = useState("");

  const draftRef = useRef(draft);
  draftRef.current = draft;
  const termsRef = useRef(terms);
  termsRef.current = terms;
  const exactWordRef = useRef(exactWord);
  exactWordRef.current = exactWord;
  const allowExactRef = useRef(allowExactToggle);
  allowExactRef.current = allowExactToggle;
  const onUnloadCommitRef = useRef(onUnloadCommit);
  onUnloadCommitRef.current = onUnloadCommit;

  useEffect(() => {
    const handleUnload = () => {
      const clean = draftRef.current.trim();
      if (!clean) return;
      const built = buildNextTermsFromDraft(
        clean,
        termsRef.current,
        allowExactRef.current,
        exactWordRef.current,
      );
      if (built && !built.error) {
        onUnloadCommitRef.current?.(built.terms);
      }
    };
    window.addEventListener("beforeunload", handleUnload);
    return () => window.removeEventListener("beforeunload", handleUnload);
  }, []);

  const commitDraft = () => {
    const clean = draft.trim();
    if (!clean) {
      setDraftError("");
      return;
    }

    const built = buildNextTermsFromDraft(clean, terms, allowExactToggle, exactWord);
    if (!built) return;
    if (built.error) {
      setDraftError(built.error);
      return;
    }

    setDraftError("");
    setDraft("");
    draftRef.current = "";
    onChange(built.terms, true);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="text-base sm:text-[15px] font-semibold leading-snug text-foreground">{label}</span>
      </div>

      {terms.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {terms.map((term, idx) => {
            const hasLatin = /[a-zA-Z]/.test(term.text);
            return (
              <Badge
                key={`${term.rawRegex || term.text}-${idx}`}
                variant={badgeVariant}
                className="max-w-full gap-1.5 overflow-hidden px-3 py-1.5 text-sm font-normal"
              >
                <span className="truncate">{term.text}</span>
                {allowExactToggle && !term.rawRegex && hasLatin && (
                  <button
                    type="button"
                    title={term.exactWord ? "当前为英文整词匹配，点击切换为普通匹配" : "点击切换为英文整词精确匹配"}
                    onClick={() =>
                      onChange(
                        terms.map((t, i) => (i === idx ? { ...t, exactWord: !t.exactWord } : t)),
                        true,
                      )
                    }
                    className={cn(
                      "min-h-7 shrink-0 rounded px-2 py-0.5 text-xs font-medium cursor-pointer transition-colors",
                      term.exactWord
                        ? "bg-primary/15 text-primary hover:bg-primary/25"
                        : "bg-muted text-muted-foreground hover:bg-foreground/15 hover:text-foreground",
                    )}
                  >
                    {term.exactWord ? "整词" : "模糊"}
                  </button>
                )}
                {term.rawRegex && (
                  <span className="shrink-0 rounded bg-foreground/10 px-1.5 py-0.5 text-xs font-medium">
                    高级规则
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`移除 ${term.text}`}
                  onClick={() => onChange(terms.filter((_, i) => i !== idx), true)}
                  className="ml-1 inline-flex size-7 shrink-0 items-center justify-center rounded-full hover:bg-foreground/10 cursor-pointer"
                >
                  <X className="size-3.5" />
                </button>
              </Badge>
            );
          })}
        </div>
      )}

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            if (draftError) setDraftError("");
          }}
          onBlur={commitDraft}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft();
            }
          }}
          placeholder={placeholder}
          className="flex-1"
        />
        <Button
          type="button"
          variant="outline"
          onMouseDown={(e) => e.preventDefault()}
          onClick={commitDraft}
          className="h-10 shrink-0 px-4"
        >
          <Plus data-icon="inline-start" />
          <span>{addButtonText}</span>
        </Button>
      </div>

      {draftError && <p className="text-sm text-destructive">{draftError}</p>}

      {allowExactToggle && (
        <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={exactWord}
            onChange={(e) => setExactWord(e.target.checked)}
            className="size-4 rounded border-input accent-primary cursor-pointer"
          />
          <span>英文整词匹配</span>
        </label>
      )}
    </div>
  );
}

export function KeywordsEditorCard({
  rawText,
  includeRss,
  onRawTextChange,
  onKeepaliveFlush,
  onIncludeRssChange,
}: KeywordsEditorCardProps) {
  const [mode, setMode] = useState<"visual" | "raw">("visual");
  const [simpleConfig, setSimpleConfig] = useState<SimpleKeywordConfig>(() =>
    parseSimpleKeywordDocument(rawText),
  );
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});
  const [advancedGroupIds, setAdvancedGroupIds] = useState<Record<string, boolean>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [undoStack, setUndoStack] = useState<string[]>([]);
  const [lastEmitted, setLastEmitted] = useState<string | null>(null);
  const [rawDirtyInTextarea, setRawDirtyInTextarea] = useState(false);

  const simpleConfigRef = useRef(simpleConfig);
  simpleConfigRef.current = simpleConfig;
  const onKeepaliveFlushRef = useRef(onKeepaliveFlush);
  onKeepaliveFlushRef.current = onKeepaliveFlush;

  useEffect(() => {
    if (lastEmitted !== null && rawText === lastEmitted) return;
    setSimpleConfig(parseSimpleKeywordDocument(rawText));
  }, [rawText, lastEmitted]);

  const flushUnloadDoc = (nextDoc: SimpleKeywordConfig) => {
    const serialized = serializeSimpleKeywordDocument(nextDoc);
    onKeepaliveFlushRef.current?.(serialized);
  };

  const commitConfig = (next: SimpleKeywordConfig, immediate = false) => {
    setUndoStack((prev) => {
      if (prev[prev.length - 1] === rawText) return prev;
      return [...prev.slice(-9), rawText];
    });
    setSimpleConfig(next);
    const serialized = serializeSimpleKeywordDocument(next);
    setLastEmitted(serialized);
    onRawTextChange(serialized, immediate);
  };

  const handleUndo = () => {
    if (undoStack.length === 0) return;
    const prevRaw = undoStack[undoStack.length - 1];
    setUndoStack((prev) => prev.slice(0, -1));

    const openTitles = new Set(
      simpleConfig.groups.filter((g) => expandedIds[g.id]).map(getSimpleGroupTitle),
    );
    const openIndices = new Set(
      simpleConfig.groups.map((g, i) => (expandedIds[g.id] ? i : -1)).filter((i) => i >= 0),
    );

    const reparsed = parseSimpleKeywordDocument(prevRaw);
    const nextExpanded: Record<string, boolean> = {};
    reparsed.groups.forEach((g, idx) => {
      if (openTitles.has(getSimpleGroupTitle(g)) || (openTitles.size > 0 && openIndices.has(idx))) {
        nextExpanded[g.id] = true;
      }
    });
    setExpandedIds(nextExpanded);
    setSimpleConfig(reparsed);
    setLastEmitted(prevRaw);
    onRawTextChange(prevRaw, true);
  };

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const toggleAdvanced = (id: string) => {
    setAdvancedGroupIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const updateGroup = (
    id: string,
    patch: Partial<SimpleKeywordGroup>,
    immediate = false,
  ) => {
    commitConfig(
      {
        ...simpleConfig,
        groups: simpleConfig.groups.map((grp) =>
          grp.id === id ? { ...grp, ...patch, dirty: true } : grp,
        ),
      },
      immediate,
    );
  };

  const handleCreateGroup = () => {
    const fresh = createEmptySimpleGroup();
    setExpandedIds((prev) => ({ ...prev, [fresh.id]: true }));
    setSearchQuery("");
    setSimpleConfig((prev) => ({ ...prev, groups: [fresh, ...prev.groups] }));
  };

  const handleDeleteGroup = (id: string) => {
    const target = simpleConfig.groups.find((g) => g.id === id);
    const displayTitle = target ? getSimpleGroupTitle(target) : "该话题";
    if (!window.confirm(`确定删除关注话题「${displayTitle}」吗？`)) return;

    const idx = simpleConfig.groups.findIndex((g) => g.id === id);
    const nextGroups = simpleConfig.groups.filter((grp) => grp.id !== id).map((g) => ({ ...g }));
    let nextTrailing = [...(simpleConfig.trailingComments || [])];
    if (target?.leadingComments?.length) {
      if (idx < nextGroups.length) {
        nextGroups[idx] = {
          ...nextGroups[idx],
          leadingComments: [...target.leadingComments, ...(nextGroups[idx].leadingComments || [])],
        };
      } else {
        nextTrailing = [...target.leadingComments, ...nextTrailing];
      }
    }

    commitConfig(
      {
        ...simpleConfig,
        groups: nextGroups,
        trailingComments: nextTrailing,
      },
      true,
    );
  };

  const handleModeSwitch = (nextMode: "visual" | "raw") => {
    if (nextMode === "visual") {
      if (rawDirtyInTextarea) {
        setSimpleConfig(parseSimpleKeywordDocument(rawText));
        setRawDirtyInTextarea(false);
      }
    } else {
      setRawDirtyInTextarea(false);
      if (lastEmitted !== null && rawText !== lastEmitted) {
        onRawTextChange(lastEmitted, false);
      }
    }
    setMode(nextMode);
  };

  const visibleGroups = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return simpleConfig.groups;
    return simpleConfig.groups.filter((grp) => {
      if (getSimpleGroupTitle(grp).toLowerCase().includes(q)) return true;
      return [...grp.keywords, ...grp.required, ...grp.excludes].some((t) =>
        t.text.toLowerCase().includes(q),
      );
    });
  }, [simpleConfig.groups, searchQuery]);

  return (
    <Card className="p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold">关注话题与屏蔽词</h3>
          <Badge variant="outline">
            {simpleConfig.groups.length} 个话题 · 屏蔽词 {simpleConfig.globalFilters.length} 个
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {undoStack.length > 0 && mode === "visual" && (
            <Button type="button" size="sm" variant="outline" onClick={handleUndo} className="h-9 px-3">
              <RotateCcw data-icon="inline-start" />
              <span>撤销上一步</span>
            </Button>
          )}
          <Button
            type="button"
            variant={mode === "raw" ? "default" : "outline"}
            onClick={() => handleModeSwitch(mode === "visual" ? "raw" : "visual")}
            className="h-10 px-4 text-sm"
          >
            {mode === "visual" ? (
              <>
                <Code2 data-icon="inline-start" />
                <span>专业文本模式</span>
              </>
            ) : (
              <>
                <ListFilter data-icon="inline-start" />
                <span>退出专业模式，回到简单填表</span>
              </>
            )}
          </Button>
        </div>
      </div>

      <FieldGroup>
        <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-muted/15 px-4 py-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-base sm:text-[15px] font-semibold">统计范围包含 RSS 订阅文章</span>
            <span className="text-sm text-muted-foreground">关闭后仅统计国内热榜与海外平台榜单标题</span>
          </div>
          <Switch checked={includeRss} onCheckedChange={onIncludeRssChange} />
        </div>

        {mode === "raw" ? (
          <Field>
            <FieldLabel>专业规则文本（兼容原 frequency_words.txt）</FieldLabel>
            <Textarea
              value={rawText}
              onChange={(e) => {
                setRawDirtyInTextarea(true);
                setLastEmitted(null);
                onRawTextChange(e.target.value, false);
              }}
              className="min-h-72 font-mono text-sm"
            />
            <div className="flex flex-wrap items-center justify-end gap-3 pt-2">
              <Button type="button" onClick={() => handleModeSwitch("visual")} className="h-10 px-4 text-sm">
                <ListFilter data-icon="inline-start" />
                <span>退出专业模式，回到简单填表</span>
              </Button>
            </div>
          </Field>
        ) : (
          <div className="flex flex-col gap-6">
            <div className="rounded-xl border border-border bg-muted/20 p-4 sm:p-5">
              <SimpleTermEditor
                label="全局屏蔽词"
                terms={simpleConfig.globalFilters}
                placeholder="输入不想看到的词，多个词可用逗号、顿号或空格隔开"
                addButtonText="添加屏蔽词"
                badgeVariant="destructive"
                onChange={(nextFilters, immediate) =>
                  commitConfig(
                    { ...simpleConfig, globalFilters: nextFilters, globalDirty: true },
                    immediate,
                  )
                }
                onUnloadCommit={(nextFilters) =>
                  flushUnloadDoc({
                    ...simpleConfigRef.current,
                    globalFilters: nextFilters,
                    globalDirty: true,
                  })
                }
              />
            </div>

            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
                <div className="relative flex-1 sm:max-w-sm">
                  <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="搜索关注的话题或关键词..."
                    className="pl-9"
                  />
                </div>
                <Button type="button" variant="outline" onClick={handleCreateGroup} className="h-10 shrink-0 px-4">
                  <Plus data-icon="inline-start" />
                  <span>添加关注话题</span>
                </Button>
              </div>

              {visibleGroups.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  暂无匹配的话题，点击「添加关注话题」即可新增。
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  {visibleGroups.map((group) => {
                    const isOpen = Boolean(expandedIds[group.id]);
                    const displayTitle = getSimpleGroupTitle(group);
                    const isEmptyDraft = group.keywords.length === 0 && group.required.length === 0;
                    const combinedPreview = [...group.keywords, ...group.required];
                    const previewSlice = combinedPreview.slice(0, 5);
                    const overflowCount = combinedPreview.length - previewSlice.length;
                    const showAdvanced =
                      Boolean(advancedGroupIds[group.id]) ||
                      group.required.length > 0 ||
                      group.maxCount > 0;

                    return (
                      <div key={group.id} className="min-w-0 overflow-hidden rounded-xl border border-border bg-card">
                        <div className="flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5">
                          <button
                            type="button"
                            onClick={() => toggleExpand(group.id)}
                            className="flex min-w-0 flex-1 flex-col gap-2 text-left cursor-pointer"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-base font-semibold break-words">{displayTitle}</span>
                              {isEmptyDraft && <Badge variant="warning">待添加关键词（未添词不生效）</Badge>}
                              {group.required.length > 0 && (
                                <Badge variant="secondary">必须含 {group.required.length} 个词</Badge>
                              )}
                              {group.excludes.length > 0 && (
                                <Badge variant="destructive">排除 {group.excludes.length} 个词</Badge>
                              )}
                              {group.maxCount > 0 && (
                                <Badge variant="outline">最多 {group.maxCount} 条</Badge>
                              )}
                            </div>

                            {previewSlice.length > 0 && (
                              <div className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5">
                                {previewSlice.map((term, idx) => (
                                  <Badge
                                    key={`${term.rawRegex || term.text}-${idx}`}
                                    variant="outline"
                                    className="max-w-full overflow-hidden px-2.5 py-0.5 text-sm font-normal"
                                  >
                                    <span className="truncate">{term.text}</span>
                                  </Badge>
                                ))}
                                {overflowCount > 0 && (
                                  <span className="text-sm text-muted-foreground">等 {combinedPreview.length} 个词</span>
                                )}
                              </div>
                            )}
                          </button>

                          <div className="flex shrink-0 items-center gap-1.5">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => toggleExpand(group.id)}
                            >
                              {isOpen ? (
                                <>
                                  <ChevronUp data-icon="inline-start" />
                                  <span>收起</span>
                                </>
                              ) : (
                                <>
                                  <ChevronDown data-icon="inline-start" />
                                  <span>修改</span>
                                </>
                              )}
                            </Button>
                            <Button
                              type="button"
                              size="icon"
                              variant="ghost"
                              className="size-9 text-muted-foreground hover:text-destructive"
                              aria-label={`删除话题 ${displayTitle}`}
                              onClick={() => handleDeleteGroup(group.id)}
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>
                        </div>

                        {isOpen && (
                          <div className="flex flex-col gap-6 border-t border-border bg-muted/15 p-5 sm:p-6">
                            <Field>
                              <FieldLabel>话题名称</FieldLabel>
                              <Input
                                value={group.title}
                                onChange={(e) => updateGroup(group.id, { title: e.target.value }, false)}
                                placeholder="例如：胖东来、人工智能、新能源汽车"
                              />
                            </Field>

                            <SimpleTermEditor
                              label="想关注的关键词"
                              terms={group.keywords}
                              placeholder="例如：胖东来 于东来"
                              addButtonText="添加关键词"
                              allowExactToggle
                              badgeVariant="outline"
                              onChange={(nextKeywords, immediate) =>
                                updateGroup(group.id, { keywords: nextKeywords }, immediate)
                              }
                              onUnloadCommit={(nextKeywords) => {
                                const cur = simpleConfigRef.current;
                                flushUnloadDoc({
                                  ...cur,
                                  groups: cur.groups.map((grp) =>
                                    grp.id === group.id
                                      ? { ...grp, keywords: nextKeywords, dirty: true }
                                      : grp,
                                  ),
                                });
                              }}
                            />

                            <SimpleTermEditor
                              label="排除词（可选）"
                              terms={group.excludes}
                              placeholder="例如：水果 果园"
                              addButtonText="添加排除词"
                              badgeVariant="destructive"
                              onChange={(nextExcludes, immediate) =>
                                updateGroup(group.id, { excludes: nextExcludes }, immediate)
                              }
                              onUnloadCommit={(nextExcludes) => {
                                const cur = simpleConfigRef.current;
                                flushUnloadDoc({
                                  ...cur,
                                  groups: cur.groups.map((grp) =>
                                    grp.id === group.id
                                      ? { ...grp, excludes: nextExcludes, dirty: true }
                                      : grp,
                                  ),
                                });
                              }}
                            />

                            <div className="flex flex-col gap-4 border-t border-border pt-4">
                              <div>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => toggleAdvanced(group.id)}
                                >
                                  <SlidersHorizontal data-icon="inline-start" />
                                  <span>
                                    {showAdvanced
                                      ? "收起更多筛选条件"
                                      : "更多筛选条件（必须同时包含 / 限制条数）"}
                                  </span>
                                </Button>
                              </div>

                              {showAdvanced && (
                                <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-4 sm:p-5">
                                  <SimpleTermEditor
                                    label="必须同时出现的词（可选）"
                                    terms={group.required}
                                    placeholder="输入必须同时包含的词"
                                    addButtonText="添加必含词"
                                    badgeVariant="secondary"
                                    onChange={(nextReq, immediate) =>
                                      updateGroup(group.id, { required: nextReq }, immediate)
                                    }
                                    onUnloadCommit={(nextReq) => {
                                      const cur = simpleConfigRef.current;
                                      flushUnloadDoc({
                                        ...cur,
                                        groups: cur.groups.map((grp) =>
                                          grp.id === group.id
                                            ? { ...grp, required: nextReq, dirty: true }
                                            : grp,
                                        ),
                                      });
                                    }}
                                  />

                                  <Field className="sm:max-w-xs">
                                    <FieldLabel>该话题最多展示几条</FieldLabel>
                                    <Input
                                      type="text"
                                      inputMode="numeric"
                                      value={group.maxCount === 0 ? "" : String(group.maxCount)}
                                      onChange={(e) => {
                                        const cleaned = e.target.value.replace(/[^\d]/g, "");
                                        updateGroup(
                                          group.id,
                                          { maxCount: cleaned ? Number.parseInt(cleaned, 10) : 0 },
                                          false,
                                        );
                                      }}
                                      placeholder="0（不限制）"
                                    />
                                  </Field>
                                </div>
                              )}
                            </div>

                            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
                              <Button type="button" size="sm" variant="outline" onClick={() => toggleExpand(group.id)}>
                                收起当前话题
                              </Button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </FieldGroup>
    </Card>
  );
}
