import React, { createContext, useCallback, useContext, useState } from "react";
import type { ChatContextItem } from "@/api/types";

interface SelectionContextValue {
  isPicking: boolean;
  setIsPicking: (val: boolean) => void;
  togglePicking: () => void;
  selectedItems: ChatContextItem[];
  isSelected: (kind: ChatContextItem["kind"], id: number) => boolean;
  toggleItem: (item: ChatContextItem) => void;
  addItem: (item: ChatContextItem) => void;
  removeItem: (kind: ChatContextItem["kind"], id: number) => void;
  clearItems: () => void;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
  requestedSessionId: number | null;
  openChatSession: (sessionId: number) => void;
  clearRequestedSession: () => void;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function SelectionProvider({ children }: { children: React.ReactNode }) {
  const [isPicking, setIsPicking] = useState(false);
  const [selectedItems, setSelectedItems] = useState<ChatContextItem[]>([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [requestedSessionId, setRequestedSessionId] = useState<number | null>(null);

  const togglePicking = useCallback(() => setIsPicking((prev) => !prev), []);

  const isSelected = useCallback(
    (kind: ChatContextItem["kind"], id: number) =>
      selectedItems.some((item) => item.kind === kind && item.id === id),
    [selectedItems],
  );

  const addItem = useCallback((item: ChatContextItem) => {
    setSelectedItems((prev) => {
      if (prev.some((x) => x.kind === item.kind && x.id === item.id)) return prev;
      return [...prev, item];
    });
  }, []);

  const removeItem = useCallback((kind: ChatContextItem["kind"], id: number) => {
    setSelectedItems((prev) => prev.filter((x) => !(x.kind === kind && x.id === id)));
  }, []);

  const toggleItem = useCallback((item: ChatContextItem) => {
    setSelectedItems((prev) => {
      const exists = prev.some((x) => x.kind === item.kind && x.id === item.id);
      if (exists) return prev.filter((x) => !(x.kind === item.kind && x.id === item.id));
      return [...prev, item];
    });
  }, []);

  const clearItems = useCallback(() => setSelectedItems([]), []);

  const openChatSession = useCallback((sessionId: number) => {
    setRequestedSessionId(sessionId);
    setChatOpen(true);
  }, []);

  const clearRequestedSession = useCallback(() => {
    setRequestedSessionId(null);
  }, []);

  return (
    <SelectionContext.Provider
      value={{
        isPicking,
        setIsPicking,
        togglePicking,
        selectedItems,
        isSelected,
        toggleItem,
        addItem,
        removeItem,
        clearItems,
        chatOpen,
        setChatOpen,
        requestedSessionId,
        openChatSession,
        clearRequestedSession,
      }}
    >
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used inside SelectionProvider");
  return ctx;
}
