export interface KeywordRuleGroup {
  id: string;
  alias: string;
  normal: string[];
  required: string[];
  excludes: string[];
  maxCount: number;
}

export interface ParsedKeywordConfig {
  globalFilters: string[];
  groups: KeywordRuleGroup[];
}

export interface ParsedTermDisplay {
  raw: string;
  expression: string;
  displayAlias: string | null;
  isRegex: boolean;
  regexFlags: string;
}

export interface SimpleKeywordTerm {
  text: string;
  exactWord: boolean;
  rawRegex?: string;
}

export interface SimpleKeywordGroup {
  id: string;
  title: string;
  keywords: SimpleKeywordTerm[];
  required: SimpleKeywordTerm[];
  excludes: SimpleKeywordTerm[];
  maxCount: number;
  leadingComments?: string[];
  originalBlock?: string;
  dirty?: boolean;
}

export interface SimpleKeywordConfig {
  globalFilters: SimpleKeywordTerm[];
  groups: SimpleKeywordGroup[];
  preambleComments?: string[];
  wordGroupsHeaderComments?: string[];
  trailingComments?: string[];
  globalComments?: string[];
  originalGlobalBlock?: string;
  globalDirty?: boolean;
  hasGlobalSection?: boolean;
  hasWordGroupsSection?: boolean;
}

let groupSeq = 0;

function nextGroupId(): string {
  groupSeq += 1;
  return `kw-grp-${groupSeq}`;
}

export function createEmptyKeywordGroup(): KeywordRuleGroup {
  return {
    id: nextGroupId(),
    alias: "",
    normal: [],
    required: [],
    excludes: [],
    maxCount: 0,
  };
}

export function createEmptySimpleGroup(): SimpleKeywordGroup {
  return {
    id: nextGroupId(),
    title: "",
    keywords: [],
    required: [],
    excludes: [],
    maxCount: 0,
    dirty: true,
  };
}

/**
 * Parse a single keyword expression (supports optional `/regex/` and `=> alias`).
 */
export function parseTermDisplay(raw: string): ParsedTermDisplay {
  const trimmed = raw.trim();
  const arrowIdx = trimmed.indexOf("=>");
  let wordConfig = trimmed;
  let displayAlias: string | null = null;

  if (arrowIdx !== -1) {
    wordConfig = trimmed.slice(0, arrowIdx).trim();
    const aliasPart = trimmed.slice(arrowIdx + 2).trim();
    if (aliasPart) {
      displayAlias = aliasPart;
    }
  }

  const regexMatch = /^\/(.+)\/([a-z]*)$/i.exec(wordConfig);
  return {
    raw: trimmed,
    expression: regexMatch ? regexMatch[1] : wordConfig,
    displayAlias,
    isRegex: regexMatch !== null,
    regexFlags: regexMatch ? regexMatch[2] || "" : "",
  };
}

/**
 * Validate `/regex/flags` (optionally with `=> alias`) syntax before persisting.
 */
export function validateRegexLiteral(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/")) return null;
  const parsed = parseTermDisplay(trimmed);
  if (!parsed.isRegex) {
    return "正则表达式需以 / 结束（例如 /关键词1|关键词2/）";
  }
  const arrowIdx = trimmed.indexOf("=>");
  const wordConfig = (arrowIdx !== -1 ? trimmed.slice(0, arrowIdx) : trimmed).trim();
  const match = /^\/(.+)\/([a-z]*)$/i.exec(wordConfig);
  if (!match || !match[1]) {
    return "正则表达式内容不能为空";
  }
  try {
    new RegExp(match[1], match[2] || "");
  } catch {
    return "正则表达式语法有误，请检查括号或转义符号";
  }
  return null;
}

const WORD_BOUNDARY_RE = /^\\b([A-Za-z0-9][A-Za-z0-9 _.-]*)\\b$/;
const LOOKAROUND_BOUNDARY_RE = /^\(\?<!\[a-zA-Z\]\)([A-Za-z0-9][A-Za-z0-9 _.-]*)\(\?!\[a-zA-Z\]\)$/;
const PLAIN_TEXT_ONLY_RE = /^[^\\^$.*+?()[\]{}|]+$/;

function parseRegexBranchToSimple(branch: string): SimpleKeywordTerm | null {
  const clean = branch.trim();
  if (!clean) return null;

  const wbMatch = WORD_BOUNDARY_RE.exec(clean);
  if (wbMatch) {
    return { text: wbMatch[1], exactWord: true };
  }

  const laMatch = LOOKAROUND_BOUNDARY_RE.exec(clean);
  if (laMatch) {
    return { text: laMatch[1], exactWord: true };
  }

  if (PLAIN_TEXT_ONLY_RE.test(clean)) {
    return { text: clean, exactWord: false };
  }

  return null;
}

/**
 * Unpack simple OR/word-boundary regex rules into plain human-editable terms.
 */
export function unpackRawTermToSimple(raw: string): {
  terms: SimpleKeywordTerm[];
  inlineAlias: string | null;
} {
  const parsed = parseTermDisplay(raw);
  if (!parsed.isRegex) {
    return {
      terms: parsed.expression ? [{ text: parsed.expression, exactWord: false }] : [],
      inlineAlias: parsed.displayAlias,
    };
  }

  if (parsed.regexFlags.length > 0) {
    return {
      terms: [
        {
          text: parsed.displayAlias || parsed.expression,
          exactWord: false,
          rawRegex: parsed.raw,
        },
      ],
      inlineAlias: parsed.displayAlias,
    };
  }

  const parts = parsed.expression.split("|");
  const unpacked: SimpleKeywordTerm[] = [];
  let allSimple = parts.length > 0;

  for (const part of parts) {
    const simple = parseRegexBranchToSimple(part);
    if (!simple) {
      allSimple = false;
      break;
    }
    unpacked.push(simple);
  }

  if (allSimple && unpacked.length > 0) {
    return { terms: unpacked, inlineAlias: parsed.displayAlias };
  }

  return {
    terms: [
      {
        text: parsed.displayAlias || parsed.expression,
        exactWord: false,
        rawRegex: parsed.raw,
      },
    ],
    inlineAlias: parsed.displayAlias,
  };
}

function escapeRegexLiteral(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Pack a simplified keyword term back into TrendRadar `frequency_words.txt` syntax.
 */
export function packSimpleTermToRaw(term: SimpleKeywordTerm): string {
  if (term.rawRegex) return term.rawRegex.trim();
  const clean = term.text.trim();
  if (!clean) return "";
  if (term.exactWord) {
    return `/(?<![a-zA-Z])${escapeRegexLiteral(clean)}(?![a-zA-Z])/`;
  }
  return clean;
}

function dedupeSimpleTerms(terms: SimpleKeywordTerm[]): SimpleKeywordTerm[] {
  const seen = new Set<string>();
  const out: SimpleKeywordTerm[] = [];
  for (const t of terms) {
    const cleanText = t.text.trim();
    if (!cleanText && !t.rawRegex) continue;
    const key = t.rawRegex ? `raw:${t.rawRegex}` : `${t.exactWord ? "1" : "0"}:${cleanText.toLowerCase()}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(t.rawRegex ? t : { text: cleanText, exactWord: t.exactWord });
    }
  }
  return out;
}

function convertRuleGroupToSimple(grp: KeywordRuleGroup): SimpleKeywordGroup {
  const lineLabels: string[] = [];
  let hasInlineAlias = false;
  const keywords: SimpleKeywordTerm[] = [];
  const required: SimpleKeywordTerm[] = [];
  const excludes: SimpleKeywordTerm[] = [];

  for (const raw of grp.normal) {
    const { terms, inlineAlias } = unpackRawTermToSimple(raw);
    keywords.push(...terms);
    if (inlineAlias) {
      hasInlineAlias = true;
      lineLabels.push(inlineAlias);
    } else if (terms.length > 0) {
      lineLabels.push(terms.map((t) => t.text).join(" / "));
    }
  }
  for (const raw of grp.required) {
    const { terms, inlineAlias } = unpackRawTermToSimple(raw);
    required.push(...terms);
    if (inlineAlias) {
      hasInlineAlias = true;
      lineLabels.push(inlineAlias);
    } else if (terms.length > 0) {
      lineLabels.push(terms.map((t) => t.text).join(" / "));
    }
  }
  for (const raw of grp.excludes) {
    excludes.push(...unpackRawTermToSimple(raw).terms);
  }

  const liftedTitle =
    grp.alias.trim() ||
    (hasInlineAlias && lineLabels.length > 0 ? Array.from(new Set(lineLabels)).join(" / ") : "");

  return {
    id: grp.id,
    title: liftedTitle,
    keywords: dedupeSimpleTerms(keywords),
    required: dedupeSimpleTerms(required),
    excludes: dedupeSimpleTerms(excludes),
    maxCount: grp.maxCount,
  };
}

/**
 * Convert structured raw-rule config to simplified jargon-free topic groups.
 */
export function toSimpleKeywordConfig(parsed: ParsedKeywordConfig): SimpleKeywordConfig {
  const globalFilters = dedupeSimpleTerms(
    parsed.globalFilters.flatMap((raw) => unpackRawTermToSimple(raw).terms),
  );
  const groups: SimpleKeywordGroup[] = parsed.groups.map(convertRuleGroupToSimple);
  return { globalFilters, groups };
}

/**
 * Convert simplified topic groups back to raw rule groups for serialization.
 */
export function fromSimpleKeywordConfig(simple: SimpleKeywordConfig): ParsedKeywordConfig {
  return {
    globalFilters: simple.globalFilters.map(packSimpleTermToRaw).filter(Boolean),
    groups: simple.groups.map((grp) => ({
      id: grp.id,
      alias: grp.title.trim(),
      normal: grp.keywords.map(packSimpleTermToRaw).filter(Boolean),
      required: grp.required.map(packSimpleTermToRaw).filter(Boolean),
      excludes: grp.excludes.map(packSimpleTermToRaw).filter(Boolean),
      maxCount: grp.maxCount,
    })),
  };
}

function serializeGroupRulesBlock(group: KeywordRuleGroup): string | null {
  const normal = group.normal.map((w) => w.trim()).filter(Boolean);
  const required = group.required.map((w) => w.trim()).filter(Boolean);
  const excludes = group.excludes.map((w) => w.trim()).filter(Boolean);
  if (normal.length === 0 && required.length === 0) return null;

  const lines: string[] = [];
  const alias = group.alias.trim();
  if (alias) {
    lines.push(`[${alias}]`);
  }
  for (const term of normal) {
    lines.push(term);
  }
  for (const term of required) {
    lines.push(`+${term}`);
  }
  for (const term of excludes) {
    lines.push(`!${term}`);
  }
  if (group.maxCount > 0 && Number.isFinite(group.maxCount)) {
    lines.push(`@${Math.floor(group.maxCount)}`);
  }
  return lines.join("\n");
}

/**
 * Losslessly parse `frequency_words.txt` into simplified form state while retaining
 * `#` section comments and original blocks for untouched groups.
 */
export function parseSimpleKeywordDocument(rawText: string): SimpleKeywordConfig {
  const normalized = (rawText || "").replace(/\r\n/g, "\n");
  if (!normalized.trim()) {
    return {
      globalFilters: [],
      groups: [],
      preambleComments: [],
      wordGroupsHeaderComments: [],
      trailingComments: [],
      globalComments: [],
      globalDirty: false,
    };
  }

  const rawBlocks = normalized
    .trim()
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .filter(Boolean);

  const preambleComments: string[] = [];
  const wordGroupsHeaderComments: string[] = [];
  const globalComments: string[] = [];
  const rawGlobalFilters: string[] = [];
  const originalGlobalParts: string[] = [];
  let hasGlobalSection = false;
  let hasWordGroupsSection = false;
  let seenWordGroupsTag = false;
  let pendingGroupComments: string[] = [];
  let currentSection: "NONE" | "GLOBAL_FILTER" | "WORD_GROUPS" = "NONE";

  const groups: SimpleKeywordGroup[] = [];

  for (const block of rawBlocks) {
    const lines = block.split("\n").map((ln) => ln.trim());
    const nonEmpty = lines.filter(Boolean);
    if (nonEmpty.length === 0) continue;

    if (nonEmpty.every((ln) => ln.startsWith("#"))) {
      if (currentSection === "NONE") {
        preambleComments.push(block);
      } else if (currentSection === "GLOBAL_FILTER" && !seenWordGroupsTag) {
        wordGroupsHeaderComments.push(block);
      } else {
        pendingGroupComments.push(block);
      }
      continue;
    }

    const firstCodeIdx = nonEmpty.findIndex((ln) => !ln.startsWith("#"));
    const leadingInBlock = nonEmpty.slice(0, firstCodeIdx);
    const firstCode = nonEmpty[firstCodeIdx];
    let tag: "GLOBAL_FILTER" | "WORD_GROUPS" | null = null;
    if (firstCode.startsWith("[") && firstCode.endsWith("]")) {
      const upper = firstCode.slice(1, -1).trim().toUpperCase();
      if (upper === "GLOBAL_FILTER" || upper === "WORD_GROUPS") {
        tag = upper;
      }
    }

    if (tag === "GLOBAL_FILTER") {
      if (leadingInBlock.length > 0) {
        preambleComments.push(leadingInBlock.join("\n"));
      }
      currentSection = "GLOBAL_FILTER";
      hasGlobalSection = true;
      const tail = nonEmpty.slice(firstCodeIdx + 1);
      for (const ln of tail) {
        if (ln.startsWith("#")) {
          globalComments.push(ln);
        } else if (!ln.startsWith("!") && !ln.startsWith("+") && !ln.startsWith("@")) {
          rawGlobalFilters.push(ln);
        }
      }
      originalGlobalParts.push(["[GLOBAL_FILTER]", ...tail].join("\n"));
      continue;
    }

    if (tag === "WORD_GROUPS") {
      if (leadingInBlock.length > 0) {
        if (!seenWordGroupsTag && currentSection === "GLOBAL_FILTER") {
          wordGroupsHeaderComments.push(leadingInBlock.join("\n"));
        } else {
          pendingGroupComments.push(leadingInBlock.join("\n"));
        }
      }
      currentSection = "WORD_GROUPS";
      hasWordGroupsSection = true;
      seenWordGroupsTag = true;
      const tail = nonEmpty.slice(firstCodeIdx + 1);
      const tailRuleLines = tail.filter((ln) => !ln.startsWith("#"));
      if (tailRuleLines.length > 0) {
        const parsed = parseGroupBlock(tailRuleLines);
        if (parsed !== null) {
          groups.push({
            ...convertRuleGroupToSimple(parsed),
            leadingComments: pendingGroupComments,
            originalBlock: tail.join("\n"),
            dirty: false,
          });
          pendingGroupComments = [];
        }
      }
      continue;
    }

    if (currentSection === "NONE") {
      currentSection = "WORD_GROUPS";
    }

    if (currentSection === "GLOBAL_FILTER") {
      if (wordGroupsHeaderComments.length > 0) {
        globalComments.push(...wordGroupsHeaderComments.splice(0));
      }
      for (const ln of nonEmpty) {
        if (ln.startsWith("#")) {
          globalComments.push(ln);
        } else if (!ln.startsWith("!") && !ln.startsWith("+") && !ln.startsWith("@")) {
          rawGlobalFilters.push(ln);
        }
      }
      originalGlobalParts.push(block);
      continue;
    }

    const ruleLines = nonEmpty.filter((ln) => !ln.startsWith("#"));
    const parsed = parseGroupBlock(ruleLines);
    if (parsed !== null) {
      groups.push({
        ...convertRuleGroupToSimple(parsed),
        leadingComments: pendingGroupComments,
        originalBlock: block,
        dirty: false,
      });
      pendingGroupComments = [];
    }
  }

  return {
    globalFilters: dedupeSimpleTerms(rawGlobalFilters.flatMap((raw) => unpackRawTermToSimple(raw).terms)),
    groups,
    preambleComments,
    wordGroupsHeaderComments,
    trailingComments: pendingGroupComments,
    globalComments,
    originalGlobalBlock: originalGlobalParts.length > 0 ? originalGlobalParts.join("\n\n") : undefined,
    globalDirty: false,
    hasGlobalSection,
    hasWordGroupsSection,
  };
}

/**
 * Serialize a `SimpleKeywordConfig` back to `frequency_words.txt`, keeping untouched
 * groups' original syntax and `#` section banners verbatim.
 */
export function serializeSimpleKeywordDocument(doc: SimpleKeywordConfig): string {
  const sections: string[] = [];

  if (doc.preambleComments && doc.preambleComments.length > 0) {
    sections.push(...doc.preambleComments);
  }

  if (!doc.globalDirty && doc.originalGlobalBlock) {
    sections.push(doc.originalGlobalBlock);
  } else {
    const packedFilters = doc.globalFilters.map(packSimpleTermToRaw).filter(Boolean);
    if (packedFilters.length > 0) {
      sections.push(["[GLOBAL_FILTER]", ...(doc.globalComments || []), ...packedFilters].join("\n"));
    } else if (doc.hasGlobalSection && doc.globalComments && doc.globalComments.length > 0) {
      sections.push(["[GLOBAL_FILTER]", ...doc.globalComments].join("\n"));
    }
  }

  if (doc.wordGroupsHeaderComments && doc.wordGroupsHeaderComments.length > 0) {
    sections.push(...doc.wordGroupsHeaderComments);
  }

  const groupChunks: string[] = [];
  for (const grp of doc.groups) {
    const serialized =
      !grp.dirty && grp.originalBlock
        ? grp.originalBlock
        : serializeGroupRulesBlock({
            id: grp.id,
            alias: grp.title.trim(),
            normal: grp.keywords.map(packSimpleTermToRaw).filter(Boolean),
            required: grp.required.map(packSimpleTermToRaw).filter(Boolean),
            excludes: grp.excludes.map(packSimpleTermToRaw).filter(Boolean),
            maxCount: grp.maxCount,
          });
    if (!serialized) continue;
    if (grp.leadingComments && grp.leadingComments.length > 0) {
      groupChunks.push(...grp.leadingComments);
    }
    groupChunks.push(serialized);
  }

  if (groupChunks.length > 0 || doc.hasWordGroupsSection) {
    sections.push("[WORD_GROUPS]");
    sections.push(...groupChunks);
  }

  if (doc.trailingComments && doc.trailingComments.length > 0) {
    sections.push(...doc.trailingComments);
  }

  return sections.join("\n\n");
}

export function getSimpleGroupTitle(group: SimpleKeywordGroup): string {
  const cleanTitle = group.title.trim();
  if (cleanTitle) return cleanTitle;
  const combined = [...group.keywords, ...group.required];
  if (combined.length === 0) return "未命名话题";
  return combined.map((t) => t.text).join(" / ");
}

/**
 * Compute concise UI display title matching backend `keyword_service.py` priority.
 */
export function getGroupDisplayTitle(group: KeywordRuleGroup): string {
  const alias = group.alias.trim();
  if (alias) return alias;

  const combined = [...group.normal, ...group.required];
  if (combined.length === 0) return "未命名词组";

  return combined
    .map((term) => {
      const parsed = parseTermDisplay(term);
      return parsed.displayAlias || parsed.expression;
    })
    .filter(Boolean)
    .join(" / ");
}

function parseGroupBlock(lines: string[]): KeywordRuleGroup | null {
  let words = [...lines];
  let alias = "";

  if (words.length > 0 && words[0].startsWith("[") && words[0].endsWith("]")) {
    const potential = words[0].slice(1, -1).trim();
    const upper = potential.toUpperCase();
    if (upper !== "GLOBAL_FILTER" && upper !== "WORD_GROUPS") {
      alias = potential;
      words = words.slice(1);
    }
  }

  const normal: string[] = [];
  const required: string[] = [];
  const excludes: string[] = [];
  let maxCount = 0;

  for (const token of words) {
    if (token.startsWith("@")) {
      const numStr = token.slice(1).trim();
      if (/^\d+$/.test(numStr)) {
        const parsed = Number.parseInt(numStr, 10);
        if (parsed > 0) {
          maxCount = parsed;
        }
      }
    } else if (token.startsWith("!")) {
      const body = token.slice(1).trim();
      if (body) excludes.push(body);
    } else if (token.startsWith("+")) {
      const body = token.slice(1).trim();
      if (body) required.push(body);
    } else {
      normal.push(token);
    }
  }

  if (normal.length === 0 && required.length === 0) {
    return null;
  }

  return {
    id: nextGroupId(),
    alias,
    normal,
    required,
    excludes,
    maxCount,
  };
}

/**
 * Parse `frequency_words.txt` formatted text into structured global filters and groups.
 */
export function parseKeywordsText(rawText: string): ParsedKeywordConfig {
  if (!rawText || !rawText.trim()) {
    return { globalFilters: [], groups: [] };
  }

  const blocks = rawText
    .trim()
    .split(/\r?\n\s*\r?\n/)
    .map((block) => block.trim())
    .filter(Boolean);

  const globalFilters: string[] = [];
  const groups: KeywordRuleGroup[] = [];
  let currentSection: "WORD_GROUPS" | "GLOBAL_FILTER" = "WORD_GROUPS";

  for (const block of blocks) {
    let lines = block
      .split(/\r?\n/)
      .map((ln) => ln.trim())
      .filter((ln) => ln.length > 0 && !ln.startsWith("#"));

    if (lines.length === 0) continue;

    if (lines[0].startsWith("[") && lines[0].endsWith("]")) {
      const tag = lines[0].slice(1, -1).trim().toUpperCase();
      if (tag === "GLOBAL_FILTER" || tag === "WORD_GROUPS") {
        currentSection = tag;
        lines = lines.slice(1);
      }
    }

    if (currentSection === "GLOBAL_FILTER") {
      for (const ln of lines) {
        if (!ln.startsWith("!") && !ln.startsWith("+") && !ln.startsWith("@")) {
          globalFilters.push(ln);
        }
      }
      continue;
    }

    const parsedGroup = parseGroupBlock(lines);
    if (parsedGroup !== null) {
      groups.push(parsedGroup);
    }
  }

  return { globalFilters, groups };
}

/**
 * Serialize structured keyword groups and global filters back to exact `frequency_words.txt` syntax.
 */
export function serializeKeywordsConfig(config: ParsedKeywordConfig): string {
  const sections: string[] = [];

  const filters = config.globalFilters.map((f) => f.trim()).filter(Boolean);
  if (filters.length > 0) {
    sections.push(["[GLOBAL_FILTER]", ...filters].join("\n"));
  }

  const serializedGroups: string[] = [];
  for (const group of config.groups) {
    const chunk = serializeGroupRulesBlock(group);
    if (chunk) {
      serializedGroups.push(chunk);
    }
  }

  if (serializedGroups.length > 0) {
    sections.push(["[WORD_GROUPS]", serializedGroups.join("\n\n")].join("\n\n"));
  } else if (sections.length === 0) {
    return "";
  } else {
    sections.push("[WORD_GROUPS]");
  }

  return sections.join("\n\n");
}
