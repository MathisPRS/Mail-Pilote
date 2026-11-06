import { PRIORITY_DOT } from "../format";
import Icon from "./Icon";
import type { BoxSummary } from "../types";

export default function BoxCard({ box, onPick }: { box: BoxSummary; onPick: () => void }) {
  return (
    <button type="button" className="box-card" data-testid="box-card" onClick={onPick}>
      <span className="box-card-head">
        <span className="box-card-icon" style={{ background: box.color }}><Icon name="mail" size={18} stroke="#fff" width={2} /></span>
        <span className="box-card-name">
          <strong className="ellipsis">{box.label}</strong>
          <span className="ellipsis">{box.email}</span>
        </span>
        {box.unread > 0 && <span className="badge" aria-label={`${box.unread} non lus`}>{box.unread}</span>}
        <Icon name="chevronRight" size={16} stroke="#A0A6B1" width={2.2} />
      </span>
      <span className="box-card-prio">
        {box.priority.map((p) => (
          <span key={p.id} className="prio-line">
            <span className="dot" style={{ background: PRIORITY_DOT[p.category] ?? "#A0A6B1" }} />
            <strong>{p.label}</strong>
            <span className="ellipsis">{p.subject}</span>
          </span>
        ))}
        {box.priority.length === 0 && <span className="muted small">Rien d'important à signaler</span>}
      </span>
    </button>
  );
}
