"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

/** Keeps inbox queries fresh from WebSocket events and surfaces new messages as toasts. */
export function useRealtime(enabled: boolean) {
  const qc = useQueryClient();
  const toast = useToast();
  useEffect(() => {
    if (!enabled) return;
    return api.connectRealtime((e) => {
      if (e.event === "message.new") {
        void qc.invalidateQueries({ queryKey: ["conversations"] });
        void qc.invalidateQueries({ queryKey: ["unread"] });
        void qc.invalidateQueries({ queryKey: ["messages", e.data.conversation_id] });
        toast(`New ${String(e.data.platform)} message: ${String(e.data.preview ?? "")}`);
      } else if (e.event === "notification.new") {
        void qc.invalidateQueries({ queryKey: ["notifications"] });
      } else if (e.event === "conversation.updated") {
        void qc.invalidateQueries({ queryKey: ["conversations"] });
        void qc.invalidateQueries({ queryKey: ["messages", e.data.conversation_id] });
      }
    });
  }, [enabled, qc, toast]);
}
