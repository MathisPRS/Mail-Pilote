import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../api";
import type { LatestRuns } from "../types";

/** Intervalle de sondage de /api/runs/latest tant qu'une analyse tourne. */
export const RUN_POLL_MS = 3000;

export const isRunning = (r?: LatestRuns | null) => r?.light?.status === "running" || r?.full?.status === "running";

/** Derniers runs ; sondés toutes les 3 s tant qu'un run est « running ». */
export function useLatestRuns() {
  return useQuery({
    queryKey: ["runs", "latest"],
    queryFn: () => apiGet<LatestRuns>("/api/runs/latest"),
    refetchInterval: (q) => (isRunning(q.state.data) ? RUN_POLL_MS : false),
  });
}

/** Monté une fois (sous la garde d'authentification) : quand une analyse se termine, rafraîchit
 * les boîtes, dossiers, listes de mails et l'état de Claude. */
export function RunWatcher() {
  const qc = useQueryClient();
  const running = isRunning(useLatestRuns().data);
  const was = useRef(running);
  useEffect(() => {
    if (was.current && !running) {
      for (const k of ["boxes", "folders", "messages", "claude-status", "activity"]) void qc.invalidateQueries({ queryKey: [k] });
    }
    was.current = running;
  }, [running, qc]);
  return null;
}
