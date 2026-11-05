import { useEffect, useState } from "react";

/** Copie locale éditable d'une valeur serveur ; recopiée une fois au chargement, puis seulement via `reset`. */
export function useDraft<T>(server: T | undefined) {
  const [draft, setDraft] = useState<T | null>(null);
  useEffect(() => {
    if (server !== undefined) setDraft((d) => d ?? server);
  }, [server]);
  return [draft, setDraft] as const;
}
