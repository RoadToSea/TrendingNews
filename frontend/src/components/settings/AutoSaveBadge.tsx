import { AlertCircle, Check, Loader2 } from "lucide-react";
import type { AutoSaveStatus } from "@/hooks/useAutoSave";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface AutoSaveBadgeProps {
  status?: AutoSaveStatus;
  onFlush?: () => void;
}

export function AutoSaveBadge({ status = "idle", onFlush }: AutoSaveBadgeProps) {
  if (status === "saving") {
    return (
      <Badge variant="secondary" className="px-2.5 py-1 text-sm">
        <Loader2 className="size-3.5 animate-spin" />
        <span>自动保存中...</span>
      </Badge>
    );
  }

  if (status === "saved") {
    return (
      <Badge variant="success" className="px-2.5 py-1 text-sm">
        <Check className="size-3.5" />
        <span>已自动保存</span>
      </Badge>
    );
  }

  if (status === "error") {
    return (
      <Button type="button" size="sm" variant="destructive" onClick={onFlush} className="h-9 text-sm">
        <AlertCircle data-icon="inline-start" />
        <span>保存失败，点击重试</span>
      </Button>
    );
  }

  if (status === "pending") {
    return (
      <div className="flex items-center gap-1.5">
        <Badge variant="warning" className="px-2.5 py-1 text-sm">
          待自动保存...
        </Badge>
        {onFlush && (
          <Button type="button" size="sm" variant="outline" onClick={onFlush} className="h-9 px-3 text-sm">
            立即保存
          </Button>
        )}
      </div>
    );
  }

  return <span className="text-sm text-muted-foreground">修改自动保存</span>;
}
