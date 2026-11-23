import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { GripVertical } from "lucide-react";
import { cn } from "@/lib/utils";

/** Props for a desktop horizontal split pane with a draggable divider and mobile stacking. */
export interface ResizableSplitPaneProps {
  /** Content rendered inside the left resizable sidebar slot. */
  left: ReactNode;
  /** Content rendered inside the right fluid primary slot. */
  right: ReactNode;
  /** Default desktop sidebar width in pixels. */
  defaultLeftWidth?: number;
  /** Minimum allowable desktop sidebar width in pixels. */
  minLeftWidth?: number;
  /** Maximum allowable desktop sidebar width in pixels. */
  maxLeftWidth?: number;
  /** Maximum fraction of total container width the sidebar may occupy (0–1). */
  maxLeftRatio?: number;
  /** Optional localStorage key used to persist user-adjusted sidebar width. */
  storageKey?: string;
  /** Accessible label for the vertical separator handle. */
  handleLabel?: string;
  className?: string;
  leftClassName?: string;
  rightClassName?: string;
}

interface DragOrigin {
  startX: number;
  startWidth: number;
}

const KEY_STEP_PX = 16;

function clampWidth(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredWidth(
  storageKey: string | undefined,
  fallback: number,
  min: number,
  max: number,
): number {
  if (!storageKey || typeof window === "undefined") {
    return clampWidth(fallback, min, max);
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw !== null ? Number(raw) : Number.NaN;
    if (Number.isFinite(parsed)) {
      return clampWidth(parsed, min, max);
    }
  } catch {
    // Storage access can throw in restricted browser contexts.
  }
  return clampWidth(fallback, min, max);
}

function persistWidth(storageKey: string | undefined, width: number): void {
  if (!storageKey || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey, String(Math.round(width)));
  } catch {
    // Ignore persistence failures when storage quota or privacy mode blocks writes.
  }
}

function computeEffectiveMax(
  containerWidth: number,
  minLeftWidth: number,
  maxLeftWidth: number,
  maxLeftRatio: number,
): number {
  if (containerWidth <= 0) return maxLeftWidth;
  const ratioCap = Math.floor(containerWidth * maxLeftRatio);
  return Math.max(minLeftWidth, Math.min(maxLeftWidth, ratioCap));
}

function nextWidthFromKey(
  key: string,
  current: number,
  fallback: number,
  min: number,
  max: number,
): number | null {
  if (key === "ArrowLeft") return clampWidth(current - KEY_STEP_PX, min, max);
  if (key === "ArrowRight") return clampWidth(current + KEY_STEP_PX, min, max);
  if (key === "Home") return min;
  if (key === "End") return max;
  if (key === "Enter" || key === " ") return clampWidth(fallback, min, max);
  return null;
}

/** Responsive split pane: stacked on mobile, horizontally draggable on `lg` viewports. */
export function ResizableSplitPane({
  left,
  right,
  defaultLeftWidth = 260,
  minLeftWidth = 190,
  maxLeftWidth = 460,
  maxLeftRatio = 0.45,
  storageKey,
  handleLabel = "左右拖动调节宽度",
  className,
  leftClassName,
  rightClassName,
}: ResizableSplitPaneProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragOrigin | null>(null);

  const [containerWidth, setContainerWidth] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [leftWidth, setLeftWidth] = useState(() =>
    readStoredWidth(storageKey, defaultLeftWidth, minLeftWidth, maxLeftWidth),
  );
  const latestWidthRef = useRef(leftWidth);
  latestWidthRef.current = leftWidth;

  const effectiveMax = computeEffectiveMax(
    containerWidth,
    minLeftWidth,
    maxLeftWidth,
    maxLeftRatio,
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const syncWidth = () => {
      const nextContainer = el.clientWidth;
      setContainerWidth(nextContainer);
      const nextMax = computeEffectiveMax(
        nextContainer,
        minLeftWidth,
        maxLeftWidth,
        maxLeftRatio,
      );
      setLeftWidth((prev) => clampWidth(prev, minLeftWidth, nextMax));
    };
    syncWidth();
    const ro = new ResizeObserver(syncWidth);
    ro.observe(el);
    return () => ro.disconnect();
  }, [minLeftWidth, maxLeftWidth, maxLeftRatio]);

  const handlePointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      dragRef.current = { startX: e.clientX, startWidth: latestWidthRef.current };
      setDragging(true);
    },
    [],
  );

  const handlePointerMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      const delta = e.clientX - dragRef.current.startX;
      const next = clampWidth(dragRef.current.startWidth + delta, minLeftWidth, effectiveMax);
      latestWidthRef.current = next;
      setLeftWidth(next);
    },
    [minLeftWidth, effectiveMax],
  );

  const finishDrag = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setDragging(false);
      try {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) {
          e.currentTarget.releasePointerCapture(e.pointerId);
        }
      } catch {
        // Ignore if pointer capture already ended.
      }
      persistWidth(storageKey, latestWidthRef.current);
    },
    [storageKey],
  );

  const handleDoubleClick = useCallback(() => {
    const reset = clampWidth(defaultLeftWidth, minLeftWidth, effectiveMax);
    latestWidthRef.current = reset;
    setLeftWidth(reset);
    persistWidth(storageKey, reset);
  }, [defaultLeftWidth, minLeftWidth, effectiveMax, storageKey]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const next = nextWidthFromKey(
        e.key,
        latestWidthRef.current,
        defaultLeftWidth,
        minLeftWidth,
        effectiveMax,
      );
      if (next === null) return;
      e.preventDefault();
      latestWidthRef.current = next;
      setLeftWidth(next);
      persistWidth(storageKey, next);
    },
    [defaultLeftWidth, minLeftWidth, effectiveMax, storageKey],
  );

  const splitStyle = {
    "--split-left-width": `${Math.round(leftWidth)}px`,
  } as CSSProperties;

  return (
    <div
      ref={containerRef}
      style={splitStyle}
      className={cn(
        "flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-0",
        dragging && "select-none",
        className,
      )}
    >
      <div className={cn("w-full min-w-0 lg:w-[var(--split-left-width)] lg:shrink-0", leftClassName)}>
        {left}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={handleLabel}
        aria-valuenow={Math.round(leftWidth)}
        aria-valuemin={minLeftWidth}
        aria-valuemax={maxLeftWidth}
        tabIndex={0}
        title="左右拖动调节宽度，双击恢复默认"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onDoubleClick={handleDoubleClick}
        onKeyDown={handleKeyDown}
        className="group relative hidden w-4 shrink-0 cursor-col-resize select-none touch-none items-center justify-center self-stretch focus-visible:outline-none lg:flex"
      >
        <div
          className={cn(
            "pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors",
            dragging ? "bg-primary" : "bg-border/60 group-hover:bg-primary/50",
          )}
        />
        <div
          className={cn(
            "relative z-10 flex h-8 w-3.5 items-center justify-center rounded-full border bg-card shadow-xs transition-colors group-focus-visible:ring-2 group-focus-visible:ring-ring",
            dragging
              ? "border-primary text-primary"
              : "border-border text-muted-foreground/70 group-hover:border-primary/40 group-hover:text-primary",
          )}
        >
          <GripVertical className="size-3" />
        </div>
      </div>

      <div className={cn("min-w-0 flex-1", rightClassName)}>{right}</div>
    </div>
  );
}
