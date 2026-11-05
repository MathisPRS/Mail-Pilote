import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiSend } from "../api";
import { useToast } from "../components/Toast";
import type { Account, AccountCreate, Provider } from "../types";
import SettingsLayout, { Group } from "./SettingsLayout";

const PROVIDERS: { id: Provider; label: string; color: string; help: string }[] = [
  { id: "gmail", label: "Gmail", color: "#D93025", help: "Active la validation en deux étapes sur ton compte Google, crée un mot de passe d'application, puis colle-le ici." },
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

  const current = PROVIDERS.find((p) => p.id === provider);
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

  return (
    <SettingsLayout title="Nouvelle boîte" backLabel="Boîtes mail" backTo="/settings/boxes">
      <section className="settings-group">
        <h2 className="settings-label">Fournisseur</h2>
        <div className="provider-grid">
          {PROVIDERS.map((p) => (
            <button key={p.id} type="button" className={`provider${p.id === provider ? " on" : ""}`} aria-pressed={p.id === provider}
              onClick={() => { setProvider(p.id); setError(null); }}>
              <span className="dot" style={{ background: p.color }} />
              {p.label}
            </button>
          ))}
        </div>
      </section>
      {current && (
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
      )}
    </SettingsLayout>
  );
}
