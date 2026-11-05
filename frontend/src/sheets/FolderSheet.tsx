import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api";
import Icon, { type IconName } from "../components/Icon";
import Sheet from "../components/Sheet";
import type { Folder } from "../types";

interface Props {
  account: string;
  boxLabel: string;
  mode: "browse" | "move";
  current?: string;
  onPick: (folderKey: string) => void;
  onClose: () => void;
}

export default function FolderSheet({ account, boxLabel, mode, current, onPick, onClose }: Props) {
  const { data, isError, isPending } = useQuery({
    queryKey: ["folders", account],
    queryFn: () => apiGet<Folder[]>(`/api/folders?account=${encodeURIComponent(account)}`),
  });
  const system = (data ?? []).filter((f) => f.role !== "custom");
  const custom = (data ?? []).filter((f) => f.role === "custom");
  const title = mode === "move" ? `Déplacer vers · ${boxLabel}` : `Dossiers · ${boxLabel}`;

  const row = (f: Folder) => {
    const icon: IconName = f.role === "custom" ? "folder" : f.role;
    return (
      <button key={f.key} type="button" className={`folder-row${f.key === current ? " on" : ""}`} onClick={() => onPick(f.key)}>
        <span className="folder-icon"><Icon name={icon} size={17} stroke={f.role === "junk" ? "#A61B1B" : "#3F4652"} /></span>
        <span className="folder-label">{f.label}</span>
        <span className="folder-count">{f.unread > 0 ? f.unread : ""}</span>
        <span className="folder-check">{mode === "browse" && f.key === current && <Icon name="check" size={18} stroke="#1F6FEB" width={2.4} />}</span>
      </button>
    );
  };

  return (
    <Sheet label={title} onClose={onClose}>
      <span className="sheet-title">{title}</span>
      <span className="sheet-note">
        {account === "all" ? "Dossiers unifiés, récupérés automatiquement sur chaque boîte" : `Récupérés automatiquement depuis le serveur ${boxLabel}`}
      </span>
      <div className="sheet-scroll">
        {isPending && <p className="muted pad">Chargement…</p>}
        {isError && <p className="form-error">Impossible de charger les dossiers</p>}
        {system.map(row)}
        {custom.length > 0 && <span className="sheet-section">Dossiers personnels</span>}
        {custom.map(row)}
      </div>
    </Sheet>
  );
}
