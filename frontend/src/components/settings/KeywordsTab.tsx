import { useEffect, useState } from "react";
import { settingsApi } from "@/api/endpoints";
import { KeywordsEditorCard } from "@/components/settings/KeywordsEditorCard";
import { Alert } from "@/components/ui/feedback";
import { useAutoSave } from "@/hooks/useAutoSave";

interface KeywordsTabProps {
  onDirtyChange?: (dirty: boolean) => void;
}

export function KeywordsTab({ onDirtyChange }: KeywordsTabProps = {}) {
  const [kwText, setKwText] = useState("");
  const [includeRss, setIncludeRss] = useState(true);
  const [error, setError] = useState("");

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
    settingsApi
      .getSection<{ raw_text?: string; include_rss?: boolean }>("keywords")
      .then((res) => {
        const rawText = String(res.payload.raw_text || "");
        const incRss = Boolean(res.payload.include_rss ?? true);
        setKwText(rawText);
        setIncludeRss(incRss);
        keywordsAuto.hydrate({ raw_text: rawText, include_rss: incRss });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载关注话题配置失败"));
    // Run once on initial mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    onDirtyChange?.(keywordsAuto.dirty);
  }, [keywordsAuto.dirty, onDirtyChange]);

  const handleRawTextChange = (nextText: string, immediate = false) => {
    setKwText(nextText);
    keywordsAuto.queueSave({ raw_text: nextText, include_rss: includeRss }, { immediate });
  };

  const handleIncludeRssChange = (nextInclude: boolean) => {
    setIncludeRss(nextInclude);
    keywordsAuto.queueSave({ raw_text: kwText, include_rss: nextInclude }, { immediate: true });
  };

  return (
    <div className="flex flex-col gap-5">
      {(error || keywordsAuto.error) && (
        <Alert variant="destructive">{error || keywordsAuto.error}</Alert>
      )}

      <KeywordsEditorCard
        rawText={kwText}
        includeRss={includeRss}
        onRawTextChange={handleRawTextChange}
        onKeepaliveFlush={(nextRaw) =>
          settingsApi.keepaliveUpdateSection("keywords", {
            raw_text: nextRaw,
            include_rss: includeRss,
          })
        }
        onIncludeRssChange={handleIncludeRssChange}
      />
    </div>
  );
}
