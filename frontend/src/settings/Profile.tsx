import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { authLogout, getMe, apiGet } from "../api";
import Icon, { type IconName } from "../components/Icon";
import { plural } from "../format";
import type { Account } from "../types";
import SettingsLayout, { Group } from "./SettingsLayout";

const ENTRIES: { to: string; label: string; icon: IconName; color: string }[] = [
  { to: "/settings/boxes", label: "Boîtes mail", icon: "mail", color: "#3A9BDC" },
  { to: "/settings/claude", label: "Claude", icon: "spark", color: "#B4532A" },
  { to: "/settings/schedule", label: "Planification", icon: "clock", color: "#6D28D9" },
  { to: "/settings/alerts", label: "Alertes", icon: "bell", color: "#DC2626" },
];

export default function Profile() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => apiGet<Account[]>("/api/accounts") });
  const logout = useMutation({
    mutationFn: authLogout,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["auth-status"] });
      navigate("/login", { replace: true });
    },
  });
  const name = me.data?.display_name || me.data?.username || "";
  const count = accounts.data?.length;

  return (
    <SettingsLayout title="Profil" backLabel="Mails">
      <div className="settings-card user-card">
        <span className="user-avatar" aria-hidden="true">{(name || "M").trim().charAt(0).toUpperCase()}</span>
        <span className="user-text">
          <span className="user-name">{name}</span>
          {count !== undefined && <span className="muted small">{count === 0 ? "Aucune boîte connectée" : `${plural(count, "boîte connectée", "boîtes connectées")}`}</span>}
        </span>
      </div>
      <Group>
        {ENTRIES.map((e) => (
          <button key={e.to} type="button" className="settings-row" onClick={() => navigate(e.to)}>
            <span className="row-icon" style={{ background: e.color }}><Icon name={e.icon} size={18} stroke="#fff" /></span>
            <span className="row-label">{e.label}</span>
            <Icon name="chevronRight" size={18} stroke="#9aa1ac" />
          </button>
        ))}
      </Group>
      <button type="button" className="btn danger-btn" disabled={logout.isPending} onClick={() => logout.mutate()}>
        Se déconnecter
      </button>
      <span className="settings-foot">Mail Pilot · auto-hébergé</span>
    </SettingsLayout>
  );
}
