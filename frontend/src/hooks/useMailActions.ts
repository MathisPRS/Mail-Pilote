import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, apiSend } from "../api";
import { useToast } from "../components/Toast";
import { plural } from "../format";
import type { ActionRequest, BatchResult, MessageAction, Run } from "../types";

const errorText = (e: unknown) => (e instanceof ApiError ? e.detail : "Une erreur est survenue");

function doneMessage(action: MessageAction, n: number): string {
  switch (action) {
    case "archive": return n > 1 ? `${n} mails archivés` : "Archivé";
    case "trash": return n > 1 ? `${n} mails mis à la corbeille` : "Mis à la corbeille";
    case "read": return n > 1 ? `${n} mails marqués comme lus` : "Marqué comme lu";
    case "unread": return n > 1 ? `${n} mails marqués comme non lus` : "Marqué comme non lu";
    case "important": return n > 1 ? `${n} mails marqués comme importants` : "Marqué comme important";
    case "move": return n > 1 ? `${n} mails déplacés` : "1 mail déplacé";
  }
}

/** Actions sur les mails, annulation et lancement manuel, avec toasts et rafraîchissement des listes. */
export function useMailActions() {
  const qc = useQueryClient();
  const toast = useToast();

  const refresh = useCallback(
    () => Promise.all(["messages", "boxes", "folders", "activity"].map((k) => qc.invalidateQueries({ queryKey: [k] }))),
    [qc],
  );

  const undo = useCallback(
    async (batchId: string) => {
      try {
        await apiSend<BatchResult>("POST", `/api/actions/${batchId}/undo`);
        toast("Action annulée");
      } catch (e) {
        toast(e instanceof ApiError && e.status === 409 ? "Ce mail ne peut plus être restauré" : errorText(e));
      } finally {
        await refresh();
      }
    },
    [refresh, toast],
  );

  const announce = useCallback(
    (res: BatchResult, message: string) => {
      toast(message, { actionLabel: "Annuler", onAction: () => void undo(res.batch_id) });
    },
    [toast, undo],
  );

  /** Renvoie true si l'action a réussi. */
  const perform = useCallback(
    async (req: ActionRequest): Promise<boolean> => {
      try {
        const res = await apiSend<BatchResult>("POST", "/api/messages/actions", req);
        if (res.count === 0) toast("Rien à faire");
        else announce(res, doneMessage(req.action, res.count));
        await refresh();
        return true;
      } catch (e) {
        toast(errorText(e));
        return false;
      }
    },
    [announce, refresh, toast],
  );

  const cleanup = useCallback(
    async (account: string) => {
      try {
        const res = await apiSend<BatchResult>("POST", `/api/cleanup?account=${encodeURIComponent(account)}`);
        if (res.count === 0) toast("Rien à nettoyer");
        else announce(res, `${plural(res.count, "pub ou spam mis", "pubs et spams mis")} à la corbeille`);
        await refresh();
      } catch (e) {
        toast(errorText(e));
      }
    },
    [announce, refresh, toast],
  );

  const runAnalysis = useCallback(async () => {
    try {
      await apiSend<Run>("POST", "/api/runs", { kind: "full" });
      toast("Analyse lancée…");
      await qc.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      toast(errorText(e));
    }
  }, [qc, toast]);

  const runSync = useCallback(async () => {
    try {
      await apiSend<Run>("POST", "/api/runs", { kind: "sync" });
      toast("Synchronisation lancée…");
      await qc.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      toast(errorText(e));
    }
  }, [qc, toast]);

  return { perform, cleanup, runAnalysis, runSync, undo };
}
