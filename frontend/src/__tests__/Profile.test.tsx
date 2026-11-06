import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const accounts = [
  { id: 1, provider: "gmail", label: "Gmail", email: "a@gmail.com", enabled: true, status: "ok", status_message: null, last_sync_at: "2026-11-05T07:00:00Z", color: "#D93025" },
  { id: 2, provider: "icloud", label: "iCloud", email: "b@icloud.com", enabled: true, status: "error", status_message: "Mot de passe d'application expiré", last_sync_at: null, color: "#3A9BDC" },
];

describe("Profil", () => {
  beforeEach(() => setViewportWide(false));

  it("profile_has_only_delivered_entries", async () => {
    mockApi({ "GET /api/accounts": accounts });
    renderWithProviders(<App />, "/settings");
    expect(await screen.findByRole("button", { name: /Boîtes mail/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Claude/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Planification/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Alertes/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Se déconnecter" })).toBeInTheDocument();
    expect(await screen.findByText("2 boîtes connectées")).toBeInTheDocument();
    for (const banned of [/Compte/, /Thème/, /Sécurité/, /Règles/, /Bientôt/, /Face ID/, /Mot de passe et/]) {
      expect(screen.queryByText(banned)).not.toBeInTheDocument();
    }
  });

  it("profile_back_always_goes_home_even_after_subpages", async () => {
    mockApi({ "GET /api/accounts": accounts, "GET /api/boxes": [] });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings");
    await user.click(await screen.findByRole("button", { name: /Boîtes mail/ }));
    await user.click(await screen.findByRole("button", { name: /Profil/ }));
    await user.click(await screen.findByRole("button", { name: /Accueil/ }));
    expect(screen.queryByRole("heading", { name: "Profil" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Boîtes mail" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Profil et réglages" })).toBeInTheDocument();
  });

  it("profile_navigates_to_subpages", async () => {
    mockApi({ "GET /api/accounts": accounts });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings");
    await user.click(await screen.findByRole("button", { name: /Boîtes mail/ }));
    expect(await screen.findByRole("heading", { name: "Boîtes mail" })).toBeInTheDocument();
    expect(await screen.findByText("Synchronisée à 08:00")).toBeInTheDocument();
    expect(screen.getByText("Mot de passe d'application expiré")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Profil/ }));
    expect(await screen.findByRole("heading", { name: "Profil" })).toBeInTheDocument();
  });

  it("profile_logout_calls_api_and_goes_to_login", async () => {
    let logged = false;
    const calls = mockApi({
      "GET /api/accounts": accounts,
      "GET /api/auth/status": () => jsonResponse({ setup_done: true, authenticated: !logged }),
      "POST /api/auth/logout": () => { logged = true; return jsonResponse(null, 204); },
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings");
    await user.click(await screen.findByRole("button", { name: "Se déconnecter" }));
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/auth/logout")).toBe(true);
    expect(await screen.findByRole("button", { name: /Se connecter/ })).toBeInTheDocument();
  });

  it("boxes_toggle_patches_and_password_update", async () => {
    const calls = mockApi({
      "GET /api/accounts": accounts,
      "PATCH /api/accounts/1": (c) => jsonResponse({ ...accounts[0], enabled: (c.body as { enabled: boolean }).enabled }),
      "PATCH /api/accounts/2": () => jsonResponse({ ...accounts[1], status: "ok", status_message: null }),
      "DELETE /api/accounts/1": () => jsonResponse(null, 204),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes");
    const toggles = await screen.findAllByRole("switch", { name: "Analyser cette boîte" });
    await user.click(toggles[0]);
    expect(calls.find((c) => c.method === "PATCH" && c.path === "/api/accounts/1")!.body).toEqual({ enabled: false });

    await user.click(screen.getByRole("button", { name: "Mettre à jour le mot de passe" }));
    await user.type(screen.getByLabelText("Nouveau mot de passe d'application"), "abcd efgh");
    await user.click(screen.getByRole("button", { name: "Tester et enregistrer" }));
    expect(calls.find((c) => c.path === "/api/accounts/2")!.body).toEqual({ password: "abcd efgh" });

    await user.click(screen.getAllByRole("button", { name: "Supprimer cette boîte" })[0]);
    expect(await screen.findByText(/uniquement de Mail Pilot/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Supprimer" }));
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/accounts/1")).toBe(true);
  });
});
