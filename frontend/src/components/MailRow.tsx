import { CATEGORY_TAGS, formatRowDate } from "../format";
import Icon from "./Icon";
import type { Message } from "../types";

interface Props {
  mail: Message;
  selecting: boolean;
  selected: boolean;
  expanded: boolean;
  active: boolean;
  onTap: () => void;
  onOpen: () => void;
  onArchive: () => void;
  onImportant: () => void;
  onTrash: () => void;
}

export default function MailRow({ mail, selecting, selected, expanded, active, onTap, onOpen, onArchive, onImportant, onTrash }: Props) {
  const tag = mail.category ? CATEGORY_TAGS[mail.category] : undefined;
  const cls = ["mail-row-btn", selected ? "selected" : "", expanded || active ? "open" : ""].join(" ").trim();
  return (
    <div className="mail-row">
      <button type="button" className={cls} onClick={onTap} aria-pressed={selecting ? selected : undefined} aria-expanded={selecting ? undefined : expanded}>
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
      {expanded && !selecting && (
        <div className="mail-actions">
          <button type="button" onClick={onOpen}>Ouvrir</button>
          <button type="button" onClick={onArchive}>Archiver</button>
          <button type="button" onClick={onImportant}>Important</button>
          <button type="button" className="danger" onClick={onTrash}>Corbeille</button>
        </div>
      )}
    </div>
  );
}
