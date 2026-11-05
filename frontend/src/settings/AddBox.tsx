import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend, startOAuth } from "../api";
import { useToast } from "../components/Toast";
import { nav } from "../navigation";
import type { Account, AccountCreate, OAuthProvider, OAuthProviders, Provider } from "../types";
import SettingsLayout, { Group } from "./SettingsLayout";

const NO_OAUTH: OAuthProviders = { google: false, microsoft: false };

const PROVIDERS: { id: Provider; label: string; color: string; help: string }[] = [
  { id: "gmail", label: "Gmail", color: "#D93025", help: "Active la validation en deux étapes sur ton compte Google, crée un mot de passe d'application, puis colle-le ici." },
  { id: "outlook", label: "Outlook", color: "#0F6CBD", help: "Outlook, Hotmail, Live : connecte-toi avec ton compte Microsoft. Mail Pilot ne voit jamais ton mot de passe." },
  { id: "icloud", label: "iCloud", color: "#3A9BDC", help: "Sur le site de ton identifiant Apple, génère un mot de passe pour app, puis colle-le ici." },
  { id: "imap", label: "Autre (IMAP)", color: "#5F6672", help: "Pour La Poste, Free, Orange… Renseigne le serveur IMAP indiqué par ton fournisseur." },
];

export default function AddBox() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const toast = useToast();
  const [provider, setProvider] = useState<Provider | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [error, setError] = useState<string | null>(null);
  const oauthQuery = useQuery({ queryKey: ["oauth-providers"], queryFn: () => apiGet<OAuthProviders>("/api/oauth/providers") });
  const oauth = oauthQuery.data ?? NO_OAUTH;

  const [oauthError, setOauthError] = useState<string | null>(null);
  const connect = useMutation({
    mutationFn: (p: OAuthProvider) => startOAuth(p),
    onSuccess: ({ url }) => nav.assign(url), // même onglet : retour sur /settings/boxes?oauth=…
    onError: (e) => setOauthError(e instanceof ApiError ? e.detail : "Une erreur est survenue"),
  });

  const add = useMutation({
    mutationFn: (body: AccountCreate) => apiSend<Account>("POST", "/api/accounts", body),
    onSuccess: async () => {
      setPassword("");
      await client.invalidateQueries({ queryKey: ["accounts"] });
      void client.invalidateQueries({ queryKey: ["boxes"] });
      void client.invalidateQueries({ queryKey: ["runs"] }); // synchro + analyse lancées côté serveur
      toast("Connexion réussie · boîte enregistrée");
      navigate("/settings/boxes", { replace: true });
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Une erreur est survenue"),
  });

  const visible = PROVIDERS.filter((p) => p.id !== "outlook" || oauth.microsoft);
  const current = visible.find((p) => p.id === provider);
  const oauthFor: OAuthProvider | null =
    provider === "gmail" && oauth.google ? "google" : provider === "outlook" && oauth.microsoft ? "microsoft" : null;
  const isIphone = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const redirecting = connect.isPending || connect.isSuccess;
  const isImap = provider === "imap";
  const pwdLabel = isImap ? "Mot de passe" : "Mot de passe d'application";
  const portNumber = port.trim() === "" ? 993 : Number(port);
  const portInvalid = isImap && (!Number.isInteger(portNumber) || portNumber < 1 || portNumber > 65535);
  const ready = !!provider && email.trim() !== "" && password !== "" && (!isImap || (host.trim() !== "" && !portInvalid));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!provider || !ready) return;
    setError(null);
    const body: AccountCreate = { provider, email: email.trim(), password };
    if (isImap) {
      body.imap_host = host.trim();
      body.imap_port = portNumber;
    }
    add.mutate(body);
  };

  const passwordForm = current && (
    <form className="settings-form" onSubmit={submit}>
      <p className="muted small">{current.help}</p>
      <Group>
        <div className="field-row">
          <input type="email" placeholder="Adresse e-mail" aria-label="Adresse e-mail" autoComplete="off" autoCapitalize="none" value={email} onChange={(e) => setEmail(e.target.value)} />
          {isImap && (
            <>
              <input placeholder="Serveur IMAP (ex. imap.laposte.net)" aria-label="Serveur IMAP" autoComplete="off" autoCapitalize="none" value={host} onChange={(e) => setHost(e.target.value)} />
              <input placeholder="Port (993)" aria-label="Port" inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value)} />
            </>
          )}
          <input type="password" placeholder={pwdLabel} aria-label={pwdLabel} autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
      </Group>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button type="submit" className="btn btn-primary" disabled={!ready || add.isPending}>
        {add.isPending ? "Connexion…" : "Tester et ajouter"}
      </button>
    </form>
  );

  return (
    <SettingsLayout title="Nouvelle boîte" backLabel="Boîtes mail" backTo="/settings/boxes">
      <section className="settings-group">
        <h2 className="settings-label">Fournisseur</h2>
        <div className="provider-grid">
          {visible.map((p) => (
            <button key={p.id} type="button" className={`provider${p.id === provider ? " on" : ""}`} aria-pressed={p.id === provider}
              onClick={() => { setProvider(p.id); setError(null); setOauthError(null); }}>
              <span className="dot" style={{ background: p.color }} />
              {p.label}
            </button>
          ))}
        </div>
      </section>
      {current && oauthFor && (
        <div className="settings-form">
          {oauthFor === "google"
            ? <p className="muted small">Connecte-toi avec ton compte Google : Mail Pilot ne voit jamais ton mot de passe.</p>
            : <p className="muted small">{current.help}</p>}
          {oauthFor === "google" && isIphone && (
            <p className="muted small">Google peut afficher “application non validée” : choisis Paramètres avancés › Continuer</p>
          )}
          {oauthError && <p className="form-error" role="alert">{oauthError}</p>}
          <button type="button" className="btn btn-primary" disabled={redirecting} onClick={() => { setOauthError(null); connect.mutate(oauthFor); }}>
            {redirecting ? "Redirection…" : oauthFor === "google" ? "Se connecter avec Google" : "Se connecter avec Microsoft"}
          </button>
          {oauthFor === "google" && (
            <details className="alt-auth">
              <summary>Utiliser un mot de passe d'application</summary>
              {passwordForm}
            </details>
          )}
        </div>
      )}
      {current && !oauthFor && passwordForm}
    </SettingsLayout>
  );
}
