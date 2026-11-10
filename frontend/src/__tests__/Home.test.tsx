import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const RUN = { id: 9, kind: "light", trigger: "manual", status: "ok", started_at: "2026-11-05T07:00:00Z", finished_at: "2026-11-05T07:01:00Z", mails_count: 2, error: null, step: null, total: 0 };

describe("Home", () => {
  beforeEach(() => setViewportWide(false));

  it("home_lists_all_boxes_first", async () => {
    mockApi({});
    renderWithProviders(<App />, "/");
    const cards = await screen.findAllByTestId("box-card");
    expect(cards.map((c) => within(c).getByText(/Toutes les boîtes|Gmail|Outlook/).textContent)).toEqual([
      "Toutes les boîtes", "Gmail", "Outlook",
    ]);
    expect(within(cards[0]).getByLabelText("5 non lus")).toBeInTheDocument();
    expect(within(cards[0]).getByText("Ouverture TT+ jeudi")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Rien d'important à signaler")).toBeInTheDocument();
    expect(await screen.findByText("Claude · analysé à 08:01")).toBeInTheDocument();
    expect(screen.getByText("Prochaine analyse à 13:00")).toBeInTheDocument();
  });

  it("home_shows_claude_disconnected", async () => {
    mockApi({ "GET /api/claude/status": { connected: false, last_ok_at: null, last_error: "x", token_set_at: null, expires_at: null, days_left: null } });
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("Claude déconnecté")).toBeInTheDocument();
  });

  it("home_card_navigates_to_inbox", async () => {
    const calls = mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    await user.click((await screen.findAllByTestId("box-card"))[2]);
    expect(await screen.findByRole("heading", { name: "Réception" })).toBeInTheDocument();
    const list = calls.find((c) => c.path === "/api/messages")!;
    expect(list.query.get("account")).toBe("2");
    expect(list.query.get("folder")).toBe("inbox");
  });

  it("home_avatar_goes_to_settings", async () => {
    mockApi({ "GET /api/auth/me": () => jsonResponse({ username: "m", display_name: "Mathis" }) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    await user.click(await screen.findByRole("button", { name: "Profil et réglages" }));
    expect(await screen.findByRole("heading", { name: "Profil" })).toBeInTheDocument();
  });

  it("home_add_box_opens_new_box_form", async () => {
    mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    await user.click(await screen.findByRole("button", { name: "Ajouter une boîte mail" }));
    expect(await screen.findByRole("heading", { name: "Nouvelle boîte" })).toBeInTheDocument();
  });

  it("home_shows_analysis_in_progress", async () => {
    mockApi({ "GET /api/runs/latest": { light: { ...RUN, status: "running", finished_at: null }, full: null, next_full_at: null, next_light_at: null } });
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("Analyse en cours…")).toBeInTheDocument();
  });

  it("home_shows_synchronisation_not_analysis_during_sync", async () => {
    mockApi({ "GET /api/runs/latest": { light: null, full: null, sync: { ...RUN, kind: "sync", status: "running", finished_at: null }, next_full_at: null, next_light_at: null } });
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("Synchronisation…")).toBeInTheDocument();
    expect(screen.queryByText("Analyse en cours…")).not.toBeInTheDocument();
  });

  it("home_analysed_time_ignores_finished_sync", async () => {
    mockApi({ "GET /api/runs/latest": { light: null, full: { ...RUN, kind: "full", finished_at: "2026-11-05T07:01:00Z" }, sync: { ...RUN, kind: "sync", finished_at: "2026-11-05T09:00:00Z" }, next_full_at: null, next_light_at: null } });
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("Claude · analysé à 08:01")).toBeInTheDocument();
  });

  it("home_polls_running_run_and_refreshes_lists_when_done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let running = true;
      const calls = mockApi({
        "GET /api/runs/latest": () =>
          jsonResponse({ light: running ? { ...RUN, status: "running", finished_at: null } : RUN, full: null, next_full_at: null, next_light_at: null }),
      });
      renderWithProviders(<App />, "/");
      expect(await screen.findByText("Analyse en cours…")).toBeInTheDocument();
      const boxesBefore = calls.filter((c) => c.path === "/api/boxes/summary").length;
      const runsBefore = calls.filter((c) => c.path === "/api/runs/latest").length;
      await act(() => vi.advanceTimersByTimeAsync(3100));
      expect(calls.filter((c) => c.path === "/api/runs/latest").length).toBeGreaterThan(runsBefore);
      running = false;
      await act(() => vi.advanceTimersByTimeAsync(3100));
      expect(await screen.findByText("Claude · analysé à 08:01")).toBeInTheDocument();
      await waitFor(() => expect(calls.filter((c) => c.path === "/api/boxes/summary").length).toBeGreaterThan(boxesBefore));
      const after = calls.filter((c) => c.path === "/api/runs/latest").length;
      await act(() => vi.advanceTimersByTimeAsync(10_000));
      expect(calls.filter((c) => c.path === "/api/runs/latest").length).toBe(after); // plus de sondage
    } finally {
      vi.useRealTimers();
    }
  });
});
