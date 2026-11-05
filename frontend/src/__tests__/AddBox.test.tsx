import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

describe("Ajout de boîte", () => {
  beforeEach(() => setViewportWide(false));

  it("addbox_shows_only_three_providers", async () => {
    mockApi({});
    renderWithProviders(<App />, "/settings/boxes/new");
    expect(await screen.findByRole("button", { name: "Gmail" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "iCloud" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Autre (IMAP)" })).toBeInTheDocument();
    expect(screen.queryByText(/Outlook/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Microsoft/)).not.toBeInTheDocument();
  });

  it("addbox_displays_server_error", async () => {
    const calls = mockApi({ "POST /api/accounts": () => jsonResponse({ detail: "Identifiants refusés par le serveur" }, 400) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    await user.click(await screen.findByRole("button", { name: "Gmail" }));
    expect(screen.getByText(/mot de passe d'application/i, { selector: "p" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Adresse e-mail"), "a@gmail.com");
    await user.type(screen.getByLabelText("Mot de passe d'application"), "secret");
    await user.click(screen.getByRole("button", { name: "Tester et ajouter" }));
    expect(await screen.findByText("Identifiants refusés par le serveur")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ provider: "gmail", email: "a@gmail.com", password: "secret" });
  });

  it("addbox_imap_sends_host_and_port_then_returns_to_boxes", async () => {
    const calls = mockApi({
      "POST /api/accounts": () => jsonResponse({ id: 3, provider: "imap", label: "La Poste", email: "x@laposte.net", enabled: true, status: "ok", status_message: null, last_sync_at: null, color: "#B88A00" }, 201),
      "GET /api/accounts": [],
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    await user.click(await screen.findByRole("button", { name: "Autre (IMAP)" }));
    await user.type(screen.getByLabelText("Adresse e-mail"), "x@laposte.net");
    await user.type(screen.getByLabelText("Serveur IMAP"), "imap.laposte.net");
    await user.type(screen.getByLabelText("Mot de passe"), "pw");
    const runsBefore = calls.filter((c) => c.path === "/api/runs/latest").length;
    await user.click(screen.getByRole("button", { name: "Tester et ajouter" }));
    expect(await screen.findByRole("heading", { name: "Boîtes mail" })).toBeInTheDocument();
    // l'ajout lance une analyse côté serveur : l'état des runs est relu (et sondé s'il tourne)
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/runs/latest").length).toBeGreaterThan(runsBefore));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ provider: "imap", email: "x@laposte.net", password: "pw", imap_host: "imap.laposte.net", imap_port: 993 });
  });
});
