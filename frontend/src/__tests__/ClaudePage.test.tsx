import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import type { ClaudeStatus } from "../types";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const LOGIN_URL = "https://claude.com/cai/oauth/authorize?code=true&state=abc";
const status = { connected: true, last_ok_at: "2026-11-05T07:02:00Z", last_error: null, token_set_at: "2026-01-01T00:00:00Z", expires_at: "2027-09-13T00:00:00Z", days_left: 312, warn_days: 7 };

describe("Page Claude", () => {
  beforeEach(() => setViewportWide(false));

  it("claudepage_shows_days_left_and_saves_token", async () => {
    let current = status;
    const calls = mockApi({
      "GET /api/claude/status": () => jsonResponse(current),
      "POST /api/claude/login/start": { url: LOGIN_URL },
      "POST /api/claude/token": () => { current = { ...status, days_left: 365 }; return jsonResponse({ ok: true, detail: "Jeton enregistré" }); },
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    expect(await screen.findByText("Connecté")).toBeInTheDocument();
    expect(screen.getByText("dans 312 jours")).toBeInTheDocument();
    expect(screen.getByText(/13\/09\/2027/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "312");
    await user.click(screen.getByRole("button", { name: "Reconnecter" }));
    await user.click(await screen.findByRole("button", { name: "Autre méthode (avancé)" }));
    expect(screen.getByText(/claude setup-token/)).toBeInTheDocument();
    const field = screen.getByLabelText("Jeton Claude");
    expect(field).toHaveAttribute("autocomplete", "off");
    expect(field).toHaveAttribute("spellcheck", "false");
    await user.type(field, "sk-ant-oat01-xyz");
    await user.click(screen.getByRole("button", { name: "Tester et enregistrer" }));
    expect(calls.find((c) => c.path === "/api/claude/token")!.body).toEqual({ token: "sk-ant-oat01-xyz" });
    expect(await screen.findByText("Jeton enregistré")).toBeInTheDocument();
    expect(await screen.findByText("dans 365 jours")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("sk-ant-oat01-xyz")).not.toBeInTheDocument();
  });

  it("claudepage_shows_failure_detail", async () => {
    mockApi({
      "POST /api/claude/login/start": { url: LOGIN_URL },
      "POST /api/claude/token": () => jsonResponse({ ok: false, detail: "Jeton refusé par Claude" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));
    await user.click(await screen.findByRole("button", { name: "Autre méthode (avancé)" }));
    await user.type(screen.getByLabelText("Jeton Claude"), "bad");
    await user.click(screen.getByRole("button", { name: "Tester et enregistrer" }));
    expect(await screen.findByText("Jeton refusé par Claude")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("bad")).not.toBeInTheDocument();
  });

  it("claudepage_warn_days_select_saves", async () => {
    const calls = mockApi({
      "GET /api/claude/status": status,
      "PUT /api/claude/settings": (c) => jsonResponse(c.body),
    });
    renderWithProviders(<App />, "/settings/claude");
    const select = await screen.findByLabelText("Me prévenir avant l'expiration");
    expect(select).toHaveValue("7");
    fireEvent.change(select, { target: { value: "14" } });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ warn_days: 14 });
    expect(await screen.findByText("Réglages enregistrés")).toBeInTheDocument();
  });

  it("claudepage_connects_subscription_from_the_app", async () => {
    let current: ClaudeStatus = { ...status, connected: false, last_error: "401", days_left: 2 };
    const calls = mockApi({
      "GET /api/claude/status": () => jsonResponse(current),
      "POST /api/claude/login/start": { url: LOGIN_URL },
      "POST /api/claude/login/complete": () => { current = { ...status, days_left: 365 }; return jsonResponse({ ok: true, detail: "Claude est connecté." }); },
      "POST /api/claude/login/cancel": () => jsonResponse(null, 204),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    expect(await screen.findByText("Déconnecté")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reconnecter" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("connexion à ton abonnement Claude");
    const link = await screen.findByRole("link", { name: "Se connecter à Claude" });
    expect(link).toHaveAttribute("href", LOGIN_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Connecte-toi avec ton compte Claude (abonnement Max). Claude t'affichera un code.")).toBeInTheDocument();
    expect(dialog.textContent).not.toMatch(/jeton|token/i); // vocabulaire du parcours principal
    expect(calls.filter((c) => c.path === "/api/claude/login/start")).toHaveLength(1);
    const field = screen.getByLabelText("Code affiché par Claude");
    expect(field).toHaveAttribute("autocomplete", "off");
    expect(field).toHaveAttribute("spellcheck", "false");
    await user.type(field, "abc#def");
    await user.click(screen.getByRole("button", { name: "Valider" }));
    expect(calls.find((c) => c.path === "/api/claude/login/complete")!.body).toEqual({ code: "abc#def" });
    expect(await screen.findByText("Claude est connecté")).toBeInTheDocument();
    expect(await screen.findByText("dans 365 jours")).toBeInTheDocument();
    expect(screen.getByText("Connecté")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.some((c) => c.path === "/api/claude/login/cancel")).toBe(false);
  });

  it("claudepage_login_failure_shows_detail_and_can_restart", async () => {
    const calls = mockApi({
      "POST /api/claude/login/start": { url: LOGIN_URL },
      "POST /api/claude/login/complete": () => jsonResponse({ ok: false, detail: "Claude a refusé le code." }),
      "POST /api/claude/login/cancel": () => jsonResponse(null, 204),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));
    await screen.findByRole("link", { name: "Se connecter à Claude" });
    await user.type(screen.getByLabelText("Code affiché par Claude"), "wrong");
    await user.click(screen.getByRole("button", { name: "Valider" }));
    expect(await screen.findByText("Claude a refusé le code.")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("wrong")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Recommencer" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/claude/login/start")).toHaveLength(2));
    expect(await screen.findByRole("link", { name: "Se connecter à Claude" })).toBeInTheDocument();
    expect(screen.queryByText("Claude a refusé le code.")).not.toBeInTheDocument();
  });

  it("claudepage_start_error_is_shown", async () => {
    mockApi({
      "POST /api/claude/login/start": () => jsonResponse({ detail: "Impossible de démarrer la connexion à Claude" }, 502),
      "POST /api/claude/login/cancel": () => jsonResponse(null, 204),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));
    expect(await screen.findByText("Impossible de démarrer la connexion à Claude")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Se connecter à Claude" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recommencer" })).toBeInTheDocument();
  });

  it("claudepage_closing_the_panel_cancels_the_login", async () => {
    const calls = mockApi({
      "POST /api/claude/login/start": { url: LOGIN_URL },
      "POST /api/claude/login/cancel": () => jsonResponse(null, 204),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));
    await screen.findByRole("link", { name: "Se connecter à Claude" });
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.path === "/api/claude/login/cancel")).toBe(true));
  });
});
