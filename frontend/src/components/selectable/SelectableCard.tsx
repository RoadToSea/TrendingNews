import React from "react";
import { Check, Plus } from "lucide-react";
import type { ChatContextItem } from "@/api/types";
import { useSelection } from "@/context/SelectionContext";
import { cn } from "@/lib/utils";

interface SelectableCardProps {
  item: ChatContextItem;
  children: React.ReactNode;
  className?: string;
}

export function SelectableCard({ item, children, className }: SelectableCardProps) {
  const { isPicking, isSelected, toggleItem } = useSelection();
  const selected = isSelected(item.kind, item.id);

  const handleCaptureClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isPicking) return;
    e.preventDefault();
    e.stopPropagation();
    toggleItem(item);
  };

  return (
    <div
      onClickCapture={handleCaptureClick}
      className={cn(
        "relative min-w-0 max-w-full rounded-lg transition-all",
        isPicking && "cursor-pointer select-none",
        isPicking && !selected && "ring-1 ring-dashed ring-primary/45 hover:ring-2 hover:ring-primary/80",
        selected && "ring-2 ring-primary bg-accent/35",
        className,
      )}
    >
      {children}
      {(isPicking || selected) && (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            toggleItem(item);
          }}
          className={cn(
            "absolute right-2.5 top-2.5 z-10 inline-flex min-h-7 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium shadow-xs transition-colors cursor-pointer",
            selected
              ? "bg-primary text-primary-foreground"
              : "border border-primary/40 bg-card text-primary hover:bg-accent",
          )}
        >
          {selected ? <Check className="size-3" /> : <Plus className="size-3" />}
          <span>{selected ? "已选" : "选择"}</span>
        </button>
      )}
    </div>
  );
}
