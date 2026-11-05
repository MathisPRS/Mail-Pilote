import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import Toggle from "../components/Toggle";
import { useToast } from "../components/Toast";
import { formatClock } from "../format";
import type { Account, AccountPatch } from "../types";
import SettingsLayout from "./SettingsLayout";

type Panel = { kind: "password" | "delete"; account: Account } | null;

const msg = (e: unknown) => (e instanceof ApiError ? e.detail : "Une erreur est survenue");

function statusOf(a: Account): { text: string; ok: boolean } {
  if (a.status !== "ok") return { text: a.status_message || "Connexion impossible", ok: false };
  if (!a.enabled) return { text: "Analyse désactivée", ok: true };
  return { text: a.last_sync_at ? `Synchronisée à ${formatClock(a.last_sync_at)}` : "En attente de la première synchronisation", ok: true };
}

export default function Boxes() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const toast = useToast();
  const [panel, setPanel] = useState<Panel>(null);
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => apiGet<Account[]>("/api/accounts") });
  const refresh = () => client.invalidateQueries({ queryKey: ["accounts"] });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: AccountPatch }) => apiSend<Account>("PATCH", `/api/accounts/${id}`, body),
    onSuccess: refresh,
    onError: (e) => toast(msg(e)),
  });

  return (
    <SettingsLayout title="Boîtes mail" backLabel="Profil" backTo="/settings">
      {accounts.isError && <p className="form-error" role="alert">Impossible de charger les boîtes.</p>}
      {accounts.data?.map((a) => {
        const st = statusOf(a);
        return (
          <div className="settings-card box-card" key={a.id} data-testid="settings-box">
            <div className="box-head">
              <span className="row-icon" style={{ background: a.color }}><Icon name="mail" size={18} stroke="#fff" /></span>
              <span className="user-text">
                <span className="user-name">{a.label}</span>
                <span className="muted small ellipsis">{a.email}</span>
              </span>
              <Toggle label="Analyser cette boîte" checked={a.enabled} disabled={patch.isPending} onChange={(enabled) => patch.mutate({ id: a.id, body: { enabled } })} />
            </div>
            <span className={`box-status ${st.ok ? "ok" : "err"}`}>
              <span className="dot" style={{ background: st.ok ? "#15803D" : "#C2410C" }} />
              {st.text}
            </span>
            {!st.ok && (
              <button type="button" className="btn" onClick={() => setPanel({ kind: "password", account: a })}>Mettre à jour le mot de passe</button>
            )}
            <button type="button" className="link-danger" onClick={() => setPanel({ kind: "delete", account: a })}>Supprimer cette boîte</button>
          </div>
        );
      })}
      <button type="button" className="btn add-btn" onClick={() => navigate("/settings/boxes/new")}>
        <Icon name="plus" size={18} />
        Ajouter une boîte mail
      </button>
      {panel?.kind === "password" && (
        <PasswordSheet account={panel.account} onClose={() => setPanel(null)} onDone={() => { setPanel(null); toast("Mot de passe mis à jour"); void refresh(); }} />
      )}
      {panel?.kind === "delete" && (
        <DeleteSheet account={panel.account} onClose={() => setPanel(null)} onDone={() => { setPanel(null); toast("Boîte supprimée de Mail Pilot"); void refresh(); void client.invalidateQueries({ queryKey: ["boxes"] }); }} />
      )}
    </SettingsLayout>
  );
}

function PasswordSheet({ account, onClose, onDone }: { account: Account; onClose: () => void; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const label = account.provider === "imap" ? "Nouveau mot de passe" : "Nouveau mot de passe d'application";
  const save = useMutation({
    mutationFn: () => apiSend<Account>("PATCH", `/api/accounts/${account.id}`, { password }),
    onSuccess: () => { setPassword(""); onDone(); },
    onError: (e) => setError(msg(e)),
  });
  return (
    <Sheet label={`Mot de passe de ${account.label}`} onClose={onClose}>
      <form className="sheet-form" onSubmit={(e) => { e.preventDefault(); setError(null); save.mutate(); }}>
        <p className="sheet-title">{account.email}</p>
        <div className="field">
          <label htmlFor="new-pwd">{label}</label>
          <input id="new-pwd" type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={!password || save.isPending}>Tester et enregistrer</button>
        <button type="button" className="text-btn" onClick={onClose}>Annuler</button>
      </form>
    </Sheet>
  );
}

function DeleteSheet({ account, onClose, onDone }: { account: Account; onClose: () => void; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const del = useMutation({
    mutationFn: () => apiSend<void>("DELETE", `/api/accounts/${account.id}`),
    onSuccess: onDone,
    onError: (e) => setError(msg(e)),
  });
  return (
    <Sheet label={`Supprimer ${account.label}`} onClose={onClose}>
      <div className="sheet-form">
        <p className="sheet-title">Supprimer cette boîte ?</p>
        <p className="muted">
          {account.email} sera retirée uniquement de Mail Pilot : tes mails restent chez ton fournisseur, rien n'y est effacé.
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="button" className="btn danger-btn" disabled={del.isPending} onClick={() => del.mutate()}>Supprimer</button>
        <button type="button" className="text-btn" onClick={onClose}>Annuler</button>
      </div>
    </Sheet>
  );
}
