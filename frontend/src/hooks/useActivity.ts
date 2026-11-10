import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiGet, apiSend } from "../api";
import { useToast } from "../components/Toast";
import type { Activity } from "../types";

/** « Pendant ton absence » : ce que l'appli a fait depuis la dernière visite. */
export function useActivity() {
  return useQuery({ queryKey: ["activity"], queryFn: () => apiGet<Activity>("/api/activity") });
}

/** Marque l'activité comme vue ; renvoie true si le serveur a répondu. */
export function useMarkSeen() {
  const qc = useQueryClient();
  const toast = useToast();
  return useCallback(async (): Promise<boolean> => {
    try {
      await apiSend<void>("POST", "/api/activity/seen");
      await qc.invalidateQueries({ queryKey: ["activity"] });
      return true;
    } catch (e) {
      toast(e instanceof ApiError ? e.detail : "Une erreur est survenue");
      return false;
    }
  }, [qc, toast]);
}
