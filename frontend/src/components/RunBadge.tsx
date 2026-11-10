import type { Run } from "../types";

/** Statut d'une analyse terminée (partagé par le suivi de l'éclair et « Pendant ton absence »). */
export default function RunBadge({ run }: { run: Run }) {
  if (run.status === "ok") return <span className="run-badge ok">Terminée</span>;
  if (run.status === "queued") return <span className="run-badge warn">En attente : Claude indisponible, reprise au prochain tri</span>;
  if (run.status === "error") return <span className="run-badge err">Échec{run.error ? ` : ${run.error}` : ""}</span>;
  return null;
}
