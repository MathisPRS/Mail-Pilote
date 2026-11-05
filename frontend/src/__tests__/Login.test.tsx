import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Login from "../screens/Login";
import { jsonResponse, mockFetch, renderWithProviders } from "../test-utils";

const status = (setup_done: boolean) => () => jsonResponse({ setup_done, authenticated: false });

describe("Login", () => {
  beforeEach(() => window.history.pushState({}, "", "/login"));

  it("shows_setup_form_when_no_user", async () => {
    mockFetch({ "GET /api/auth/status": status(false) });
    renderWithProviders(<Login />, "/login");
    expect(await screen.findByLabelText("Nom affiché")).toBeInTheDocument();
    expect(screen.getByLabelText("Identifiant")).toBeInTheDocument();
    expect(screen.getByLabelText("Mot de passe")).toBeInTheDocument();
    expect(screen.getByLabelText("Confirmer")).toBeInTheDocument();
    expect(screen.getByText(/12 caractères/)).toBeInTheDocument();
  });

  it("shows_login_form_when_setup_done", async () => {
    mockFetch({ "GET /api/auth/status": status(true) });
    renderWithProviders(<Login />, "/login");
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Nom affiché")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Confirmer")).not.toBeInTheDocument();
  });

  it("shows_rate_limit_message_on_429", async () => {
    mockFetch({
      "GET /api/auth/status": status(true),
      "POST /api/auth/login": () => jsonResponse({ detail: "Too Many" }, 429),
    });
    const user = userEvent.setup();
    renderWithProviders(<Login />, "/login");
    await user.type(await screen.findByLabelText("Identifiant"), "mathis");
    await user.type(screen.getByLabelText("Mot de passe"), "whatever");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Trop de tentatives, réessaie dans 15 minutes.");
  });

  it("shows_bad_credentials_inline", async () => {
    mockFetch({
      "GET /api/auth/status": status(true),
      "POST /api/auth/login": () => jsonResponse({ detail: "Identifiants incorrects" }, 401),
    });
    const user = userEvent.setup();
    renderWithProviders(<Login />, "/login");
    await user.type(await screen.findByLabelText("Identifiant"), "mathis");
    await user.type(screen.getByLabelText("Mot de passe"), "x");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiants incorrects");
  });

  it("setup_rejects_mismatch_and_short_password_without_calling_api", async () => {
    const f = mockFetch({ "GET /api/auth/status": status(false) });
    const user = userEvent.setup();
    renderWithProviders(<Login />, "/login");
    await user.type(await screen.findByLabelText("Identifiant"), "mathis");
    await user.type(screen.getByLabelText("Mot de passe"), "court");
    await user.type(screen.getByLabelText("Confirmer"), "court");
    await user.click(screen.getByRole("button", { name: "Créer le compte" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("au moins 12 caractères");
    await user.clear(screen.getByLabelText("Mot de passe"));
    await user.type(screen.getByLabelText("Mot de passe"), "un mot de passe long");
    await user.click(screen.getByRole("button", { name: "Créer le compte" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("ne correspondent pas"));
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("setup_creates_account_then_logs_in_and_goes_home", async () => {
    const f = mockFetch({
      "GET /api/auth/status": status(false),
      "POST /api/auth/setup": () => jsonResponse({ username: "mathis" }, 201),
      "POST /api/auth/login": () => jsonResponse({ username: "mathis", display_name: "Mathis" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<Login />, "/login");
    await user.type(await screen.findByLabelText("Nom affiché"), "Mathis");
    await user.type(screen.getByLabelText("Identifiant"), "mathis");
    await user.type(screen.getByLabelText("Mot de passe"), "un mot de passe long");
    await user.type(screen.getByLabelText("Confirmer"), "un mot de passe long");
    await user.click(screen.getByRole("button", { name: "Créer le compte" }));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(4));
    const setupBody = JSON.parse((f.mock.calls[1][1] as RequestInit).body as string);
    expect(setupBody).toEqual({ display_name: "Mathis", username: "mathis", password: "un mot de passe long" });
  });
});
