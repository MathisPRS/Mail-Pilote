import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const RUN = {
  id: 9, kind: "full", trigger: "manual", status: "running", started_at: "2026-11-05T07:00:00Z", finished_at: null,
  mails_count: 0, error: null, step: null, total: 0,
};
const latest = (over: object | null, extra: object = {}) => ({
  "GET /api/runs/latest": { light: null, full: over === null ? null : { ...RUN, ...over }, next_full_at: null, next_light_at: null, ...extra },
});

async function openSheet(user: ReturnType<typeof userEvent.setup>, path = "/box/all/inbox") {
  renderWithProviders(<App />, path);
  await user.click(await screen.findByRole("button", { name: /^Actions/ }));
  return within(await screen.findByRole("dialog"));
}

const SYNC = { ...RUN, id: 20, kind: "sync", trigger: "manual", status: "running", step: "sync" };
const latestSync = (over: object = {}) => ({
  "GET /api/runs/latest": { light: null, full: null, sync: { ...SYNC, ...over }, next_full_at: null, next_light_at: null },
});

describe("ActionsSheet suivi", () => {
  beforeEach(() => setViewportWide(false));

  it("sync_row_is_first_and_click_posts_sync_keeping_panel_open", async () => {
    const calls = mockApi({ ...latest(null), "POST /api/runs": () => jsonResponse({ ...SYNC }, 202) });
    const user = userEvent.setup();
    const dialog = await openSheet(user);
    const rows = dialog.getAllByRole("button").filter((b) => b.classList.contains("action-row"));
    expect(rows[0]).toHaveTextContent("Synchroniser maintenant");
    expect(rows[0]).toHaveTextContent("Récupère les nouveaux mails de toutes les boîtes");
    await user.click(rows[0]);
    expect(calls.find((c) => c.path === "/api/runs")!.body).toEqual({ kind: "sync" });
    expect(await screen.findByText("Synchronisation lancée…")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("sync_row_disabled_with_right_text_while_running", async () => {
    mockApi(latestSync());
    const dialog = await openSheet(userEvent.setup());
    const btn = await dialog.findByRole("button", { name: /Synchroniser maintenant/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("Synchronisation en cours…");
    expect(dialog.getByRole("button", { name: /Lancer une analyse/ })).toBeDisabled();
    expect(dialog.getByText("Synchronisation")).toBeInTheDocument();
    expect(dialog.getByText("Récupération des nouveaux mails")).toBeInTheDocument();
  });

  it("sync_row_says_analysis_in_progress_when_analysis_runs", async () => {
    mockApi(latest({ step: "classify", total: 3 }));
    const dialog = await openSheet(userEvent.setup());
    const btn = await dialog.findByRole("button", { name: /Synchroniser maintenant/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("Analyse en cours…");
  });

  it("shows_finished_sync_run", async () => {
    mockApi(latestSync({ status: "ok", step: null, finished_at: "2026-11-05T07:01:00Z", mails_count: 1 }));
    const dialog = await openSheet(userEvent.setup());
    expect(await dialog.findByText("Dernière synchronisation · 08:01 · 1 nouveau mail")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: /Synchroniser maintenant/ })).toBeEnabled();
  });

  it("dot_on_lightning_button_during_sync", async () => {
    mockApi(latestSync());
    renderWithProviders(<App />, "/box/all/inbox");
    const btn = await screen.findByRole("button", { name: "Actions, synchronisation en cours" });
    expect(btn.querySelector(".run-dot")).not.toBeNull();
  });

  it("stays_open_after_launching_an_analysis", async () => {
    const calls = mockApi({ ...latest(null), "POST /api/runs": () => jsonResponse({ ...RUN, id: 5 }, 202) });
    const user = userEvent.setup();
    const dialog = await openSheet(user);
    await user.click(dialog.getByRole("button", { name: /Lancer une analyse/ }));
    expect(calls.find((c) => c.path === "/api/runs")!.body).toEqual({ kind: "full" });
    expect(await screen.findByText("Analyse lancée…")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows_step_and_progress_of_running_run", async () => {
    mockApi(latest({ step: "classify", total: 12, mails_count: 4 }));
    const dialog = await openSheet(userEvent.setup());
    expect(await dialog.findByText("Analyse complète")).toBeInTheDocument();
    expect(dialog.getByText(/lancée manuellement/)).toBeInTheDocument();
    expect(dialog.getByText("Claude trie les mails · 4 / 12")).toBeInTheDocument();
    const bar = dialog.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "4");
    expect(bar).toHaveAttribute("aria-valuemax", "12");
  });

  it.each([
    ["sync", "Récupération des nouveaux mails"],
    ["bodies", "Lecture du contenu des mails"],
    ["alerts", "Envoi des alertes"],
  ])("running_step_%s_label", async (step, label) => {
    mockApi(latest({ step, trigger: "schedule" }));
    const dialog = await openSheet(userEvent.setup());
    expect(await dialog.findByText(label)).toBeInTheDocument();
    expect(dialog.getByText(/planifiée/)).toBeInTheDocument();
    expect(dialog.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("disables_launch_button_while_running", async () => {
    mockApi(latest({ step: "sync" }));
    const dialog = await openSheet(userEvent.setup());
    const btn = await dialog.findByRole("button", { name: /Lancer une analyse/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("Analyse en cours…");
  });

  it("shows_finished_ok_run_and_next_planned", async () => {
    mockApi(latest(
      { status: "ok", finished_at: "2026-11-05T07:01:00Z", mails_count: 3 },
      { next_full_at: "2026-11-05T12:00:00Z" },
    ));
    const dialog = await openSheet(userEvent.setup());
    expect(await dialog.findByText("Dernière analyse · 08:01 · 3 mails analysés")).toBeInTheDocument();
    expect(dialog.getByText("Prochaine analyse à 13:00")).toBeInTheDocument();
    expect(dialog.getByRole("button", { name: /Lancer une analyse/ })).toBeEnabled();
  });

  it("shows_queued_and_error_states", async () => {
    mockApi(latest({ status: "queued", finished_at: "2026-11-05T07:01:00Z", error: "limite" }));
    const first = await openSheet(userEvent.setup());
    expect(await first.findByText("En attente : Claude indisponible, reprise au prochain tri")).toBeInTheDocument();
  });

  it("shows_error_message", async () => {
    mockApi(latest({ status: "error", finished_at: "2026-11-05T07:01:00Z", error: "IMAP KO" }));
    const dialog = await openSheet(userEvent.setup());
    expect(await dialog.findByText(/Échec/)).toBeInTheDocument();
    expect(dialog.getByText(/IMAP KO/)).toBeInTheDocument();
  });

  it("shows_empty_state", async () => {
    mockApi(latest(null));
    const dialog = await openSheet(userEvent.setup());
    expect(await dialog.findByText("Aucune analyse pour l'instant")).toBeInTheDocument();
  });

  it("shows_dot_on_lightning_button_while_running", async () => {
    mockApi(latest({ step: "sync" }));
    renderWithProviders(<App />, "/box/all/inbox");
    const btn = await screen.findByRole("button", { name: "Actions, analyse en cours" });
    expect(btn.querySelector(".run-dot")).not.toBeNull();
  });

  it("no_dot_when_idle", async () => {
    mockApi(latest({ status: "ok", finished_at: "2026-11-05T07:01:00Z" }));
    renderWithProviders(<App />, "/box/all/inbox");
    const btn = await screen.findByRole("button", { name: "Actions manuelles" });
    expect(btn.querySelector(".run-dot")).toBeNull();
  });

  it("cleanup_disables_its_row_while_pending", async () => {
    let release: (r: Response) => void = () => {};
    const pending = new Promise<Response>((r) => { release = r; });
    mockApi({ ...latest(null), "POST /api/cleanup": () => pending as unknown as Response });
    const user = userEvent.setup();
    const dialog = await openSheet(user);
    await user.click(dialog.getByRole("button", { name: /Nettoyer pubs et spams/ }));
    const row = await dialog.findByRole("button", { name: /Nettoyage en cours…/ });
    expect(row).toBeDisabled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    release(jsonResponse({ batch_id: "c1", count: 2 }));
    expect(await screen.findByText("2 pubs et spams mis à la corbeille")).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByRole("button", { name: /Nettoyer pubs et spams/ })).toBeEnabled());
  });
});
