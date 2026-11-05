import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiGet, apiSend } from "../api";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import type { ScheduleSettings } from "../types";
import SettingsLayout from "./SettingsLayout";
import { useDraft } from "./useDraft";

const DAYS = [["L", "Lundi"], ["M", "Mardi"], ["M", "Mercredi"], ["J", "Jeudi"], ["V", "Vendredi"], ["S", "Samedi"], ["D", "Dimanche"]];
const INTERVALS = [15, 30, 60] as const;

export default function Schedule() {
  const client = useQueryClient();
  const toast = useToast();
  const server = useQuery({ queryKey: ["settings", "schedule"], queryFn: () => apiGet<ScheduleSettings>("/api/settings/schedule") });
  const [draft, setDraft] = useDraft(server.data);
  const [newTime, setNewTime] = useState("12:00");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: ScheduleSettings) => apiSend<ScheduleSettings>("PUT", "/api/settings/schedule", body),
    onSuccess: (saved) => {
      setDraft(saved);
      client.setQueryData(["settings", "schedule"], saved);
      void client.invalidateQueries({ queryKey: ["runs"] });
      setError(null);
      toast("Réglages enregistrés");
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Une erreur est survenue"),
  });

  const update = (patch: Partial<ScheduleSettings>) => { setError(null); setDraft((d) => (d ? { ...d, ...patch } : d)); };

  const addTime = () => {
    if (!draft || !newTime) return;
    if (draft.full_times.includes(newTime)) { setError("Cet horaire existe déjà"); return; }
    if (draft.full_times.length >= 8) { setError("8 horaires au maximum"); return; }
    update({ full_times: [...draft.full_times, newTime].sort() });
  };
  const toggleDay = (i: number) => {
    if (!draft) return;
    update({ days: draft.days.includes(i) ? draft.days.filter((d) => d !== i) : [...draft.days, i].sort() });
  };

  return (
    <SettingsLayout title="Planification" backLabel="Profil" backTo="/settings">
      {server.isError && <p className="form-error" role="alert">Impossible de charger la planification.</p>}
      {draft && (
        <>
          <section className="settings-group">
            <h2 className="settings-label">Tri complet</h2>
            <div className="settings-card pad-card">
              <div className="chips">
                {draft.full_times.map((t) => (
                  <span className="time-chip" key={t}>
                    {t}
                    <button type="button" aria-label={`Retirer l'horaire ${t}`} disabled={draft.full_times.length <= 1} onClick={() => update({ full_times: draft.full_times.filter((x) => x !== t) })}>
                      <Icon name="close" size={14} />
                    </button>
                  </span>
                ))}
              </div>
              <div className="inline-add">
                <input type="time" value={newTime} onChange={(e) => setNewTime(e.target.value)} aria-label="Nouvel horaire" />
                <button type="button" className="btn" onClick={addTime}>Ajouter</button>
              </div>
            </div>
          </section>
          <section className="settings-group">
            <h2 className="settings-label">Jours</h2>
            <div className="days">
              {DAYS.map(([short, name], i) => (
                <button key={name} type="button" className="day" aria-pressed={draft.days.includes(i)} aria-label={name} onClick={() => toggleDay(i)}>{short}</button>
              ))}
            </div>
          </section>
          <section className="settings-group">
            <h2 className="settings-label">Vérification légère</h2>
            <div className="settings-card pad-card">
              <p className="muted small">Repère vite les mails prioritaires entre deux tris complets.</p>
              <div className="segmented" role="group" aria-label="Intervalle de vérification">
                {INTERVALS.map((m) => (
                  <button key={m} type="button" aria-pressed={draft.light_interval_min === m} onClick={() => update({ light_interval_min: m })}>{m} min</button>
                ))}
              </div>
              <div className="inline-add">
                <label className="time-field">De <input type="time" aria-label="Début de la plage" value={draft.light_start} onChange={(e) => update({ light_start: e.target.value })} /></label>
                <label className="time-field">à <input type="time" aria-label="Fin de la plage" value={draft.light_end} onChange={(e) => update({ light_end: e.target.value })} /></label>
              </div>
            </div>
          </section>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="button" className="btn btn-primary" disabled={save.isPending || draft.days.length === 0} onClick={() => save.mutate(draft)}>Enregistrer</button>
          {draft.days.length === 0 && <p className="muted small">Choisis au moins un jour.</p>}
        </>
      )}
    </SettingsLayout>
  );
}

