import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../api";
import { ActionsButton, ProfileButton } from "../components/HeaderButtons";
import Icon from "../components/Icon";
import MailRow from "../components/MailRow";
import PriorityBox from "../components/PriorityBox";
import { CHIPS, ROLE_LABELS, isPriorityCategory, plural } from "../format";
import { useMailActions } from "../hooks/useMailActions";
import ActionsSheet from "../sheets/ActionsSheet";
import FolderSheet from "../sheets/FolderSheet";
import type { BoxSummary, Category, Folder, FolderRole, MessagePage } from "../types";

type Filter = "all" | "priority" | Category;
type Sheet = "none" | "folders" | "move" | "actions";

interface Props { account: string; folder: string; activeId: number | null }

const PAGE = 50;

export default function MailList({ account, folder, activeId }: Props) {
  const navigate = useNavigate();
  const { perform } = useMailActions();
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [sheet, setSheet] = useState<Sheet>("none");

  useEffect(() => {
    const t = setTimeout(() => setSearch(draft.trim()), 300);
    return () => clearTimeout(t);
  }, [draft]);

  const boxes = useQuery({ queryKey: ["boxes"], queryFn: () => apiGet<BoxSummary[]>("/api/boxes/summary") });
  const folders = useQuery({ queryKey: ["folders", account], queryFn: () => apiGet<Folder[]>(`/api/folders?account=${encodeURIComponent(account)}`) });
  const messages = useInfiniteQuery({
    queryKey: ["messages", account, folder, search],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams({ account, folder, limit: String(PAGE) });
      if (search) p.set("q", search);
      if (pageParam !== null) p.set("before_id", String(pageParam));
      return apiGet<MessagePage>(`/api/messages?${p}`);
    },
    getNextPageParam: (last) => last.next_before_id,
  });

  const boxLabel = boxes.data?.find((b) => String(b.id) === account)?.label ?? (account === "all" ? "Toutes les boîtes" : "Boîte");
  const folderLabel =
    folders.data?.find((f) => f.key === folder)?.label ?? ROLE_LABELS[folder as FolderRole] ?? "Dossier";

  const all = useMemo(() => messages.data?.pages.flatMap((p) => p.items) ?? [], [messages.data]);
  const priority = useMemo(() => all.filter((m) => isPriorityCategory(m.category)), [all]);
  const visible = useMemo(() => {
    if (filter === "all") return all;
    if (filter === "priority") return priority;
    return all.filter((m) => m.category === filter);
  }, [all, priority, filter]);

  const visibleIds = visible.map((m) => m.id);
  const selectedIds = selected.filter((id) => visibleIds.includes(id));
  const allSelected = visibleIds.length > 0 && selectedIds.length === visibleIds.length;
  const showPriority = !selecting && folder === "inbox" && (priority.length > 0 || filter === "priority");

  const stopSelect = () => { setSelecting(false); setSelected([]); };
  const openMail = (id: number) => navigate(`/box/${account}/${folder}/mail/${id}`);
  const act = async (ids: number[], action: Parameters<typeof perform>[0]["action"], target?: string) => {
    const ok = await perform({ ids, action, ...(target ? { target_folder: target } : {}) });
    if (ok) { setExpanded(null); stopSelect(); }
  };

  const tap = (id: number) => {
    if (selecting) setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
    else setExpanded((e) => (e === id ? null : id));
  };

  const barBtn = (label: string, icon: Parameters<typeof Icon>[0]["name"], onClick: () => void, danger = false) => (
    <button type="button" className={`bar-btn${danger ? " danger" : ""}`} disabled={selectedIds.length === 0} onClick={onClick}>
      <Icon name={icon} size={22} />
      {label}
    </button>
  );

  return (
    <div className="list-screen">
      <header className="list-header">
        <div className="bar">
          {selecting ? (
            <>
              <button type="button" className="text-btn" onClick={() => setSelected(allSelected ? [] : visibleIds)}>
                {allSelected ? "Tout désélect." : "Tout sélect."}
              </button>
              <button type="button" className="text-btn bold" onClick={stopSelect}>OK</button>
            </>
          ) : (
            <>
              <button type="button" className="text-btn back" onClick={() => navigate("/")}>
                <Icon name="back" size={20} width={2.2} />
                Boîtes
              </button>
              <div className="bar-actions">
                <button type="button" className="text-btn" onClick={() => { setSelecting(true); setSelected([]); setExpanded(null); }}>Sélectionner</button>
                <ActionsButton subtle onClick={() => setSheet("actions")} />
                <ProfileButton />
              </div>
            </>
          )}
        </div>

        {selecting ? (
          <div className="list-title">
            <span className="muted small strong">{boxLabel} · {folderLabel}</span>
            <h1 className="big-title">{selectedIds.length === 0 ? "Aucun sélectionné" : plural(selectedIds.length, "sélectionné", "sélectionnés")}</h1>
          </div>
        ) : (
          <div className="list-title">
            <span className="muted small strong">{boxLabel}</span>
            <h1 className="big-title">
              <button type="button" className="title-btn" aria-haspopup="dialog" onClick={() => setSheet("folders")}>
                {folderLabel}
                <Icon name="chevronDown" size={20} stroke="#1F6FEB" width={2.2} />
              </button>
            </h1>
          </div>
        )}

        <label className="search">
          <Icon name="search" size={16} stroke="#5F6672" width={2} />
          <input type="search" placeholder="Rechercher" aria-label="Rechercher" value={draft} onChange={(e) => setDraft(e.target.value)} />
        </label>

        <div className="chips">
          {CHIPS.map(([key, label]) => {
            const n = key === "all" ? 0 : all.filter((m) => m.category === key).length;
            return (
              <button key={key} type="button" className="chip" aria-pressed={filter === key} onClick={() => { setFilter(key); setExpanded(null); }}>
                {key === "all" ? label : `${label} ${n}`}
              </button>
            );
          })}
        </div>
      </header>

      <div className="list-scroll">
        {showPriority && (
          <PriorityBox items={priority} active={filter === "priority"} onToggle={() => { setFilter((f) => (f === "priority" ? "all" : "priority")); setExpanded(null); }} />
        )}
        {visible.map((m) => (
          <MailRow
            key={m.id}
            mail={m}
            selecting={selecting}
            selected={selectedIds.includes(m.id)}
            expanded={expanded === m.id}
            active={activeId === m.id}
            onTap={() => tap(m.id)}
            onOpen={() => openMail(m.id)}
            onArchive={() => void act([m.id], "archive")}
            onImportant={() => void act([m.id], "important")}
            onTrash={() => void act([m.id], "trash")}
          />
        ))}
        {messages.isPending && <p className="empty">Chargement…</p>}
        {messages.isError && (
          <p className="empty">
            Impossible de charger les mails.{" "}
            <button type="button" className="link-btn" onClick={() => void messages.refetch()}>Réessayer</button>
          </p>
        )}
        {messages.isSuccess && visible.length === 0 && <p className="empty">Aucun mail ici.</p>}
        {messages.hasNextPage && (
          <div className="load-more">
            <button type="button" className="btn" disabled={messages.isFetchingNextPage} onClick={() => void messages.fetchNextPage()}>
              {messages.isFetchingNextPage ? "Chargement…" : "Charger plus"}
            </button>
          </div>
        )}
      </div>

      {selecting && (
        <div className="select-bar">
          {barBtn("Lu", "read", () => void act(selectedIds, "read"))}
          {barBtn("Important", "star", () => void act(selectedIds, "important"))}
          {barBtn("Déplacer", "move", () => setSheet("move"))}
          {barBtn("Archiver", "archive", () => void act(selectedIds, "archive"))}
          {barBtn("Corbeille", "trash", () => void act(selectedIds, "trash"), true)}
        </div>
      )}

      {sheet === "folders" && (
        <FolderSheet
          account={account}
          boxLabel={boxLabel}
          mode="browse"
          current={folder}
          onClose={() => setSheet("none")}
          onPick={(key) => { setSheet("none"); navigate(`/box/${account}/${key}`); }}
        />
      )}
      {sheet === "move" && (
        <FolderSheet
          account={account}
          boxLabel={boxLabel}
          mode="move"
          onClose={() => setSheet("none")}
          onPick={(key) => { setSheet("none"); void act(selectedIds, "move", key); }}
        />
      )}
      {sheet === "actions" && <ActionsSheet account={account} onClose={() => setSheet("none")} />}
    </div>
  );
}
