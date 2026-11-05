import { useSyncExternalStore } from "react";

/** `useMediaQuery("(min-width: 900px)")` ; false quand matchMedia n'existe pas (jsdom). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mql = window.matchMedia?.(query);
      mql?.addEventListener?.("change", notify);
      return () => mql?.removeEventListener?.("change", notify);
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  );
}

export const WIDE_QUERY = "(min-width: 900px)";
