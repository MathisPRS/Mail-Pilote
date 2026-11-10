import { CATEGORY_TAGS, formatRowDate } from "../format";
import { useLongPress } from "../hooks/useLongPress";
import Icon from "./Icon";
import type { Message } from "../types";

interface Props {
  mail: Message;
  selecting: boolean;
  selected: boolean;
  /** Rangée d'actions dépliée (appui long, clic droit ou bouton « Plus d'actions »). */
  expanded: boolean;
  active: boolean;
  /** Toucher / cliquer : ouvre le mail (ou coche en mode sélection). */
  onTap: () => void;
  /** Appui long, clic droit, bouton « Plus d'actions » : déplie ou replie les actions. */
  onToggleActions: () => void;
  onArchive: () => void;
  onImportant: () => void;
  onTrash: () => void;
}

export default function MailRow({ mail, selecting, selected, expanded, active, onTap, onToggleActions, onArchive, onImportant, onTrash }: Props) {
  const tag = mail.category ? CATEGORY_TAGS[mail.category] : undefined;
  const press = useLongPress(onToggleActions, !selecting);
  const cls = ["mail-row-btn", selected ? "selected" : "", expanded || active ? "open" : ""].join(" ").trim();
  const shown = expanded && !selecting;
  return (
    <div className={`mail-row${shown ? " expanded" : ""}`}>
      <button type="button" className={cls} onClick={onTap} aria-pressed={selecting ? selected : undefined} {...press}>
        <span className="mail-lead">
          {selecting ? (
            selected ? <span className="check on"><Icon name="check" size={13} stroke="#fff" width={3.2} /></span> : <span className="check" />
          ) : (
            !mail.seen && <span className="unread-dot" role="img" aria-label="Non lu" />
          )}
        </span>
        <span className="mail-main">
          <span className="mail-top">
            <span className="box-square" style={{ background: mail.account_color }} />
            <span className={`mail-from${mail.seen ? "" : " unread"}`}>{mail.from_name || mail.from_addr}</span>
            <span className="mail-time">{formatRowDate(mail.sent_at)}</span>
          </span>
          <span className="mail-subject">{mail.subject}</span>
          <span className="mail-preview">
            {tag && <span className={`tag tag-${mail.category}`}>{tag}</span>}
            {mail.preview}
          </span>
        </span>
      </button>
      {!selecting && (
        <button type="button" className="mail-more" aria-label={`Actions pour ${mail.subject}`} aria-expanded={expanded} onClick={onToggleActions}>
          <Icon name="more" size={18} width={2.6} />
        </button>
      )}
      {shown && (
        <div className="mail-actions">
          <button type="button" onClick={onArchive}>Archiver</button>
          <button type="button" onClick={onImportant}>Important</button>
          <button type="button" className="danger" onClick={onTrash}>Corbeille</button>
        </div>
      )}
    </div>
  );
}
