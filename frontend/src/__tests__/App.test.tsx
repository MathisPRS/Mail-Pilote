import { screen } from "@testing-library/react";
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
