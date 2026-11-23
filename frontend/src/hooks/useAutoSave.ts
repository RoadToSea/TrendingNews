import { useCallback, useEffect, useRef, useState } from "react";

export type AutoSaveStatus = "idle" | "pending" | "saving" | "saved" | "error";

interface UseAutoSaveOptions<T> {
  delayMs?: number;
  onSave: (payload: T) => Promise<void>;
  keepaliveFlush?: (payload: T) => void;
  validate?: (payload: T) => string | null;
}

export interface UseAutoSaveResult<T> {
  status: AutoSaveStatus;
  error: string;
  dirty: boolean;
  lastSavedPayload: T | null;
  hydrate: (initialPayload: T) => void;
  queueSave: (nextPayload: T, options?: { immediate?: boolean }) => void;
  flushNow: () => Promise<void>;
}

/**
 * Race-free debounced auto-save hook with immediate discrete save and keepalive page-unload flush.
 */
export function useAutoSave<T>({
  delayMs = 450,
  onSave,
  keepaliveFlush,
  validate,
}: UseAutoSaveOptions<T>): UseAutoSaveResult<T> {
  const [status, setStatus] = useState<AutoSaveStatus>("idle");
  const [error, setError] = useState("");
  const [lastSavedPayload, setLastSavedPayload] = useState<T | null>(null);

  const loadedRef = useRef(false);
  const lastSavedJsonRef = useRef("");
  const pendingJsonRef = useRef("");
  const latestPayloadRef = useRef<T | null>(null);
  const inFlightRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const keepaliveFlushRef = useRef(keepaliveFlush);
  keepaliveFlushRef.current = keepaliveFlush;
  const validateRef = useRef(validate);
  validateRef.current = validate;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const executeSave = useCallback(async () => {
    clearTimer();
    if (inFlightRef.current) return;

    const payload = latestPayloadRef.current;
    const targetJson = pendingJsonRef.current;
    if (!loadedRef.current || payload === null || targetJson === lastSavedJsonRef.current) {
      if (mountedRef.current) {
        setStatus((prev) => (prev === "pending" || prev === "saving" ? "saved" : prev));
      }
      return;
    }

    const validationMsg = validateRef.current?.(payload);
    if (validationMsg) {
      if (mountedRef.current) {
        setStatus("error");
        setError(validationMsg);
      }
      return;
    }

    inFlightRef.current = true;
    if (mountedRef.current) {
      setStatus("saving");
      setError("");
    }

    let succeeded = false;
    try {
      await onSaveRef.current(payload);
      lastSavedJsonRef.current = targetJson;
      succeeded = true;
      if (mountedRef.current) {
        setLastSavedPayload(payload);
        if (pendingJsonRef.current === targetJson) {
          setStatus("saved");
          setError("");
        }
      }
    } catch (err) {
      if (mountedRef.current) {
        setStatus("error");
        setError(err instanceof Error ? err.message : "自动保存失败");
      }
    } finally {
      inFlightRef.current = false;
      const newerEditQueued = targetJson !== pendingJsonRef.current;
      if (
        (succeeded || newerEditQueued) &&
        latestPayloadRef.current !== null &&
        pendingJsonRef.current !== lastSavedJsonRef.current
      ) {
        void executeSave();
      }
    }
  }, [clearTimer]);

  const hydrate = useCallback(
    (initialPayload: T) => {
      clearTimer();
      const snap = JSON.stringify(initialPayload);
      lastSavedJsonRef.current = snap;
      pendingJsonRef.current = snap;
      latestPayloadRef.current = initialPayload;
      loadedRef.current = true;
      setLastSavedPayload(initialPayload);
      if (mountedRef.current) {
        setStatus("idle");
        setError("");
      }
    },
    [clearTimer],
  );

  const queueSave = useCallback(
    (nextPayload: T, options?: { immediate?: boolean }) => {
      if (!loadedRef.current) return;
      const nextJson = JSON.stringify(nextPayload);
      latestPayloadRef.current = nextPayload;
      pendingJsonRef.current = nextJson;

      if (nextJson === lastSavedJsonRef.current) {
        clearTimer();
        if (mountedRef.current) {
          setError("");
          setStatus((prev) => (prev === "saved" ? "saved" : "idle"));
        }
        return;
      }

      clearTimer();
      if (options?.immediate) {
        void executeSave();
        return;
      }

      if (mountedRef.current) {
        setStatus("pending");
        setError("");
      }
      timerRef.current = window.setTimeout(() => {
        void executeSave();
      }, delayMs);
    },
    [clearTimer, delayMs, executeSave],
  );

  const flushNow = useCallback(async () => {
    clearTimer();
    await executeSave();
  }, [clearTimer, executeSave]);

  useEffect(() => {
    mountedRef.current = true;
    const handleBeforeUnload = () => {
      const pendingPayload = latestPayloadRef.current;
      if (
        loadedRef.current &&
        pendingPayload !== null &&
        pendingJsonRef.current !== lastSavedJsonRef.current
      ) {
        const validationMsg = validateRef.current?.(pendingPayload);
        if (!validationMsg) {
          if (keepaliveFlushRef.current) {
            keepaliveFlushRef.current(pendingPayload);
          } else {
            void onSaveRef.current(pendingPayload).catch(() => {});
          }
        }
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      mountedRef.current = false;
      clearTimer();
      const pendingPayload = latestPayloadRef.current;
      if (
        loadedRef.current &&
        pendingPayload !== null &&
        pendingJsonRef.current !== lastSavedJsonRef.current &&
        !inFlightRef.current
      ) {
        const validationMsg = validateRef.current?.(pendingPayload);
        if (!validationMsg) {
          void onSaveRef.current(pendingPayload).catch(() => {});
        }
      }
    };
  }, [clearTimer]);

  return {
    status,
    error,
    dirty: status === "pending" || status === "saving" || status === "error",
    lastSavedPayload,
    hydrate,
    queueSave,
    flushNow,
  };
}
