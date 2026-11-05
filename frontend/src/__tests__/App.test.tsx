import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createQueryClient } from "../queryClient";
import App from "../App";
import { jsonResponse, mockFetch, renderWithProviders } from "../test-utils";

describe("App routing", () => {
  it("redirects_to_login_when_not_authenticated", async () => {
    mockFetch({ "GET /api/auth/status": () => jsonResponse({ setup_done: true, authenticated: false }) });
    renderWithProviders(<App />, "/");
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  });

  it("shows_home_when_authenticated", async () => {
    mockFetch({ "GET /api/auth/status": () => jsonResponse({ setup_done: true, authenticated: true }) });
    renderWithProviders(<App />, "/");
    expect(await screen.findByRole("heading", { name: "Accueil" })).toBeInTheDocument();
  });
});

describe("login flow with the real query client config", () => {
  beforeEach(() => window.history.pushState({}, "", "/login"));

  it("login_then_home_is_visible", async () => {
    let authenticated = false;
    mockFetch({
      "GET /api/auth/status": () => jsonResponse({ setup_done: true, authenticated }),
      "POST /api/auth/login": () => {
        authenticated = true;
        return jsonResponse({ username: "m", display_name: "M" });
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/login", createQueryClient());
    await user.type(await screen.findByLabelText("Identifiant"), "m");
    await user.type(screen.getByLabelText("Mot de passe"), "secret");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("heading", { name: "Accueil" })).toBeInTheDocument();
  });
});
