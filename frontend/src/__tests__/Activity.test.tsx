import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../App";
import { LONG_PRESS_MS } from "../hooks/useLongPress";
import { detail, emptyActivity, mockApi, msg, setViewportWide } from "../test-fixtures";
import { renderWithProviders } from "../test-utils";
import type { Activity } from "../types";

const RUN = { id: 9, kind: "full", trigger: "schedule", status: "ok", started_at: "2026-11-05T07:00:00Z", finished_at: "2026-11-05T07:01:00Z", mails_count: 34, error: null, step: null, total: 0 } as const;

const FULL: Activity = {
  since: "2026-11-05T06:00:00Z",
  summary: { runs: 2, analysed: 47, important: 1, tt: 1, ads: 12, alerts: 2, actions: 9 },
  runs: [RUN, { ...RUN, id: 8, kind: "light", status: "queued", mails_count: 0 }],
  important: [msg(11, { subject: "Avis important", category: "important", priority: true })],
  tt: [msg(12, { subject: "Ouverture TT+", category: "tt", priority: true })],
  alerts: [msg(13, { subject: "Alerte envoyée" })],
  ads: [msg(14, { subject: "Grosse promo", category: "pub" })],
  actions: [
    { batch_id: "b1", action: "trash", source: "app", at: "2026-11-05T11:12:00Z", count: 9, undone: false, messages: [msg(15, { subject: "Mail jeté" })] },
    { batch_id: "b2", action: "archive", source: "user", at: "2026-11-05T10:00:00Z", count: 1, undone: true, messages: [msg(16)] },
  ],
};

describe("Home « Pendant ton absence »", () => {
  beforeEach(() => setViewportWide(false));

  it("hidden when nothing happened", async () => {
    mockApi({});
    renderWithProviders(<App />, "/");
    await screen.findAllByTestId("box-card");
    expect(screen.queryByText("Pendant ton absence")).not.toBeInTheDocument();
  });

  it("shows only non-zero counters with plural agreement", async () => {
    mockApi({ "GET /api/activity": { ...emptyActivity, summary: { ...emptyActivity.summary, analysed: 47, important: 1, tt: 1, alerts: 2, actions: 1 } } });
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("Pendant ton absence")).toBeInTheDocument();
    for (const t of ["47 mails triés", "1 important", "1 TT+", "2 alertes", "1 action"]) expect(screen.getByText(t)).toBeInTheDocument();
    expect(screen.queryByText(/pub/)).not.toBeInTheDocument();
    expect(screen.getByText(/^depuis /)).toBeInTheDocument();
  });

  it("dismiss calls seen and hides the box", async () => {
    let seen = false;
    const calls = mockApi({
      "GET /api/activity": () => new Response(JSON.stringify(seen ? emptyActivity : FULL), { headers: { "Content-Type": "application/json" } }),
      "POST /api/activity/seen": () => { seen = true; return new Response(null, { status: 204 }); },
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("12 pubs/spams")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Masquer" }));
    await waitFor(() => expect(screen.queryByText("Pendant ton absence")).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/activity/seen")).toBe(true);
  });

  it("tap opens /activity", async () => {
    mockApi({ "GET /api/activity": FULL });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    await user.click(await screen.findByText("47 mails triés"));
    expect(await screen.findByRole("heading", { name: "Pendant ton absence" })).toBeInTheDocument();
    expect(screen.getByText("Avis important")).toBeInTheDocument();
  });
});

describe("Écran /activity", () => {
  beforeEach(() => setViewportWide(false));

  it("shows sections with mails, actions and analyses", async () => {
    mockApi({ "GET /api/activity": FULL });
    renderWithProviders(<App />, "/activity");
    for (const h of ["Importants", "TT+", "Alertes envoyées", "Pubs et spams détectés", "Actions", "Analyses"]) {
      expect(await screen.findByRole("heading", { name: h })).toBeInTheDocument();
    }
    for (const t of ["Avis important", "Ouverture TT+", "Alerte envoyée", "Grosse promo"]) expect(screen.getByText(t)).toBeInTheDocument();
    expect(screen.getByText("12:12 · 9 mails → corbeille")).toBeInTheDocument();
    expect(screen.getByText("par Mail Pilot")).toBeInTheDocument();
    expect(screen.getByText("11:00 · 1 mail → archivés")).toBeInTheDocument();
    expect(screen.getByText("par toi")).toBeInTheDocument();
    expect(screen.getByText("Annulé")).toBeInTheDocument();
    expect(screen.getByText("08:00 · Tri complet · 34 mails")).toBeInTheDocument();
    expect(screen.getByText(/Vérification rapide/)).toBeInTheDocument();
    expect(screen.getByText("En attente : Claude indisponible, reprise au prochain tri")).toBeInTheDocument();
  });

  it("hides empty sections", async () => {
    mockApi({ "GET /api/activity": { ...emptyActivity, ads: FULL.ads, summary: { ...emptyActivity.summary, ads: 1 } } });
    renderWithProviders(<App />, "/activity");
    expect(await screen.findByRole("heading", { name: "Pubs et spams détectés" })).toBeInTheDocument();
    for (const h of ["Importants", "TT+", "Alertes envoyées", "Actions", "Analyses"]) {
      expect(screen.queryByRole("heading", { name: h })).not.toBeInTheDocument();
    }
  });

  it("expands a batch to list its mails and undoes it", async () => {
    const calls = mockApi({ "GET /api/activity": FULL, "POST /api/actions/b1/undo": { batch_id: "b1", count: 9 } });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/activity");
    await user.click(await screen.findByText("12:12 · 9 mails → corbeille"));
    expect(screen.getByText("Mail jeté")).toBeInTheDocument();
    const before = calls.filter((c) => c.path === "/api/activity").length;
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/actions/b1/undo")).toBe(true));
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/activity").length).toBeGreaterThan(before));
  });

  it("opening a mail goes to the reader and back returns to /activity", async () => {
    mockApi({ "GET /api/activity": FULL, "GET /api/messages/11": detail(11, { subject: "Avis important" }) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/activity");
    await user.click(await screen.findByText("Avis important"));
    expect(await screen.findByTitle("Contenu du mail")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Retour" }));
    expect(await screen.findByRole("heading", { name: "Pendant ton absence" })).toBeInTheDocument();
  });

  it("long press on a mail shows actions without opening it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockApi({ "GET /api/activity": FULL });
      renderWithProviders(<App />, "/activity");
      const btn = (await screen.findByText("Grosse promo")).closest("button")!;
      fireEvent.pointerDown(btn, { clientX: 1, clientY: 1, pointerType: "touch" });
      await act(() => vi.advanceTimersByTimeAsync(LONG_PRESS_MS));
      fireEvent.pointerUp(btn);
      fireEvent.click(btn, { detail: 1 });
      expect(screen.getByRole("button", { name: "Corbeille" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Ouvrir" })).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Pendant ton absence" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("« C'est vu » calls seen and returns home", async () => {
    const calls = mockApi({ "GET /api/activity": FULL, "POST /api/activity/seen": () => new Response(null, { status: 204 }) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/activity");
    await user.click(await screen.findByRole("button", { name: "C'est vu" }));
    expect(await screen.findByRole("heading", { name: "Mes boîtes" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/activity/seen")).toBe(true);
  });

  it("back button returns to home", async () => {
    mockApi({ "GET /api/activity": FULL });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/activity");
    await user.click(await screen.findByRole("button", { name: "Accueil" }));
    expect(await screen.findByRole("heading", { name: "Mes boîtes" })).toBeInTheDocument();
  });
});
