import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { detail, inboxMessages, mockApi, msg, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

describe("MailList", () => {
  beforeEach(() => setViewportWide(false));

  it("list_priority_box_toggles_filter", async () => {
    mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    expect(await screen.findByText("Promo ce week-end")).toBeInTheDocument();
    const box = screen.getByRole("button", { name: /À ne pas manquer/ });
    expect(within(box).getByText("2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Important 1" })).toBeInTheDocument();
    await user.click(box);
    expect(screen.queryByText("Promo ce week-end")).not.toBeInTheDocument();
    expect(screen.queryByText("Relevé disponible")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /À ne pas manquer/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Tout afficher")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /À ne pas manquer/ }));
    expect(screen.getByText("Promo ce week-end")).toBeInTheDocument();
  });

  it("list_category_chip_filters_with_counts", async () => {
    mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await screen.findByText("Promo ce week-end");
    const chip = screen.getByRole("button", { name: "Pub 1" });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Relevé disponible")).not.toBeInTheDocument();
    expect(screen.getByText("Promo ce week-end")).toBeInTheDocument();
  });

  it("list_row_tap_shows_four_actions_and_archives_with_undo", async () => {
    const calls = mockApi({
      "POST /api/messages/actions": { batch_id: "b1", count: 1 },
      "POST /api/actions/b1/undo": { batch_id: "b1", count: 1 },
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByText("Relevé disponible"));
    for (const n of ["Ouvrir", "Archiver", "Important", "Corbeille"]) {
      expect(screen.getByRole("button", { name: n })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("button", { name: "Archiver" }));
    expect(calls.find((c) => c.path === "/api/messages/actions")!.body).toEqual({ ids: [3], action: "archive" });
    expect(await screen.findByText("Archivé")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/actions/b1/undo")).toBe(true));
  });

  it("list_row_open_goes_to_reader", async () => {
    mockApi({ "GET /api/messages/3": detail(3, { subject: "Relevé disponible" }) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByText("Relevé disponible"));
    await user.click(screen.getByRole("button", { name: "Ouvrir" }));
    expect(await screen.findByTitle("Contenu du mail")).toBeInTheDocument();
  });

  it("list_selection_bulk_trash_then_undo", async () => {
    const calls = mockApi({
      "POST /api/messages/actions": { batch_id: "b2", count: 2 },
      "POST /api/actions/b2/undo": () => jsonResponse({ detail: "Ce mail ne peut plus être restauré" }, 409),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await screen.findByText("Promo ce week-end");
    await user.click(screen.getByRole("button", { name: "Sélectionner" }));
    expect(screen.getByText("Aucun sélectionné")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Corbeille" })).toBeDisabled();
    await user.click(screen.getByText("Relevé disponible"));
    await user.click(screen.getByText("Promo ce week-end"));
    expect(screen.getByText("2 sélectionnés")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Corbeille" }));
    expect(calls.find((c) => c.path === "/api/messages/actions")!.body).toEqual({ ids: [3, 4], action: "trash" });
    expect(await screen.findByText("2 mails mis à la corbeille")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sélectionner" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(await screen.findByText("Ce mail ne peut plus être restauré")).toBeInTheDocument();
  });

  it("list_select_all_toggle", async () => {
    mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await screen.findByText("Promo ce week-end");
    await user.click(screen.getByRole("button", { name: "Sélectionner" }));
    await user.click(screen.getByRole("button", { name: "Tout sélect." }));
    expect(screen.getByText("4 sélectionnés")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tout désélect." }));
    expect(screen.getByText("Aucun sélectionné")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(screen.getByRole("button", { name: "Sélectionner" })).toBeInTheDocument();
  });

  it("list_folder_sheet_changes_folder", async () => {
    const calls = mockApi({
      "GET /api/messages": (c) =>
        jsonResponse({ items: c.query.get("folder") === "sent" ? [msg(9, { subject: "Mail envoyé" })] : inboxMessages, next_before_id: null }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByRole("button", { name: /Réception/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /Envoyés/ }));
    expect(await screen.findByText("Mail envoyé")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Envoyés" })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/messages" && c.query.get("folder") === "sent")).toBe(true);
  });

  it("list_move_opens_folder_sheet_in_destination_mode", async () => {
    const calls = mockApi({ "POST /api/messages/actions": { batch_id: "b3", count: 1 } });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await screen.findByText("Promo ce week-end");
    await user.click(screen.getByRole("button", { name: "Sélectionner" }));
    await user.click(screen.getByText("Relevé disponible"));
    await user.click(screen.getByRole("button", { name: "Déplacer" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Déplacer vers/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Archives/ }));
    expect(calls.find((c) => c.path === "/api/messages/actions")!.body).toEqual({ ids: [3], action: "move", target_folder: "archive" });
    expect(await screen.findByText("1 mail déplacé")).toBeInTheDocument();
  });

  it("list_search_and_load_more", async () => {
    const calls = mockApi({
      "GET /api/messages": (c) =>
        c.query.get("before_id")
          ? jsonResponse({ items: [msg(20, { subject: "Plus ancien" })], next_before_id: null })
          : jsonResponse({ items: inboxMessages, next_before_id: 4 }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByRole("button", { name: "Charger plus" }));
    expect(await screen.findByText("Plus ancien")).toBeInTheDocument();
    expect(calls.some((c) => c.query.get("before_id") === "4")).toBe(true);
    await user.type(screen.getByLabelText("Rechercher"), "taxe");
    await waitFor(() => expect(calls.some((c) => c.query.get("q") === "taxe")).toBe(true));
  });

  it("actions_sheet_cleanup_shows_count_and_undo", async () => {
    const calls = mockApi({
      "POST /api/cleanup": { batch_id: "c1", count: 7 },
      "POST /api/actions/c1/undo": { batch_id: "c1", count: 7 },
      "POST /api/runs": () => jsonResponse({ id: 5, kind: "full", trigger: "manual", status: "running", started_at: null, finished_at: null, mails_count: 0, error: null }, 202),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByRole("button", { name: "Actions manuelles" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText(/apprentissage/i)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Nettoyer pubs et spams/ }));
    expect(await screen.findByText("7 pubs et spams mis à la corbeille")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/cleanup")!.query.get("account")).toBe("all");
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/actions/c1/undo")).toBe(true));

    await user.click(screen.getByRole("button", { name: "Actions manuelles" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Lancer une analyse/ }));
    expect(calls.find((c) => c.path === "/api/runs")!.body).toEqual({ kind: "full" });
    expect(await screen.findByText("Analyse lancée…")).toBeInTheDocument();
  });

  it("actions_sheet_cleanup_nothing", async () => {
    mockApi({ "POST /api/cleanup": { batch_id: "", count: 0 } });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByRole("button", { name: "Actions manuelles" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Nettoyer/ }));
    expect(await screen.findByText("Rien à nettoyer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument();
  });

  it("sheet_closes_on_escape", async () => {
    mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/box/all/inbox");
    await user.click(await screen.findByRole("button", { name: "Actions manuelles" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("list_selection_raises_toast_offset", async () => {
    mockApi({});
    const user = userEvent.setup();
    const { unmount } = renderWithProviders(<App />, "/box/all/inbox");
    await screen.findByText("Promo ce week-end");
    const get = () => document.documentElement.style.getPropertyValue("--toast-bottom");
    expect(get()).toBe("");
    await user.click(screen.getByRole("button", { name: "Sélectionner" }));
    expect(get()).toBe("92px");
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(get()).toBe("");
    unmount();
  });
});
