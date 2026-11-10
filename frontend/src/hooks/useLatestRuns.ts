import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../api";
import type { LatestRuns, Run } from "../types";

/** Intervalle de sondage de /api/runs/latest tant qu'une analyse tourne. */
export const RUN_POLL_MS = 3000;

/** Session en cours (vérification rapide, tri complet ou synchronisation). */
export const runningRun = (r?: LatestRuns | null): Run | null =>
  [r?.light, r?.full, r?.sync].find((x): x is Run => x?.status === "running") ?? null;

export const isRunning = (r?: LatestRuns | null) => runningRun(r) !== null;

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
