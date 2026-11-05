import { PRIORITY_DOT } from "../format";
import Icon from "./Icon";
import type { Message } from "../types";

export const priorityLabel = (m: Message) => (m.category === "tt" ? "TT+" : m.from_name || m.from_addr);

/** « À ne pas manquer » : défile avec la liste, bascule le filtre prioritaire. */
export default function PriorityBox({ items, active, onToggle }: { items: Message[]; active: boolean; onToggle: () => void }) {
  return (
    <div className="prio-wrap">
      <button type="button" className={`prio-box${active ? " active" : ""}`} aria-pressed={active} onClick={onToggle}>
        <span className="prio-head">
          <span className="prio-title">
            <Icon name="bell" size={15} stroke="#C2410C" width={2} />
            À ne pas manquer
            <span className="prio-count">{items.length}</span>
          </span>
          <span className="prio-action">{active ? "Tout afficher" : "Voir"}</span>
        </span>
        {items.slice(0, 3).map((m) => (
          <span key={m.id} className="prio-line">
            <span className="dot" style={{ background: (m.category && PRIORITY_DOT[m.category]) || "#A0A6B1" }} />
            <strong>{priorityLabel(m)}</strong>
            <span className="ellipsis">{m.subject}</span>
          </span>
        ))}
      </button>
    </div>
  );
}
