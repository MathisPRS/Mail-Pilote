/** Icônes du mockup (tracés SVG inline, trait 1.9). */
export const ICONS = {
  zap: "M13 2L4 14h7l-1 8 9-12h-7l1-8z",
  mail: "M3 7l9 6 9-6 M3 5h18v14H3z",
  back: "M15 18l-6-6 6-6",
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  search: "M20 20l-3.5-3.5 M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0z",
  bell: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9 M10.3 21a1.9 1.9 0 0 0 3.4 0",
  check: "M5 12l5 5L20 7",
  read: "M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0z M8.5 12l2.5 2.5 4.5-5",
  star: "M12 3l2.7 5.6 6.1.8-4.4 4.3 1 6.1L12 17l-5.4 2.8 1-6.1-4.4-4.3 6.1-.8z",
  move: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M10 13h6 M13 10l3 3-3 3",
  plus: "M12 5v14 M5 12h14",
  inbox: "M3 13h5l2 3h4l2-3h5 M5 5h14l2 8v6H3v-6z",
  drafts: "M4 20h4L19 9l-4-4L4 16z M14 6l4 4",
  sent: "M22 2L11 13 M22 2l-7 20-4-9-9-4z",
  junk: "M12 8v5 M12 16h.01 M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9z",
  trash: "M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3",
  archive: "M3 4h18v4H3z M5 8v12h14V8 M10 12h4",
  folder: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  spark: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  close: "M6 6l12 12 M18 6L6 18",
  more: "M5 12h.01 M12 12h.01 M19 12h.01",
  paperclip: "M21 12l-8.5 8.5a5 5 0 0 1-7-7L14 5a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7",
} as const;

export type IconName = keyof typeof ICONS;

export default function Icon({ name, size = 20, stroke = "currentColor", width = 1.9 }: { name: IconName; size?: number; stroke?: string; width?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={ICONS[name]} />
    </svg>
  );
}
