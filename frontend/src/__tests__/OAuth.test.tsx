import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../App";
import { nav } from "../navigation";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const both = { google: true, microsoft: true };

const oauthAccount = {
  id: 7, provider: "gmail", label: "Gmail", email: "me@gmail.com", enabled: true, status: "error",
  status_message: "Reconnexion à Google nécessaire", last_sync_at: null, color: "#D93025", auth_type: "oauth",
};
const outlookAccount = { ...oauthAccount, id: 8, provider: "outlook", label: "Outlook", email: "me@outlook.fr", color: "#0F6CBD", status_message: "Reconnexion à Microsoft nécessaire" };

describe("Connexion Google / Microsoft", () => {
  let assign: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    setViewportWide(false);
    assign = vi.spyOn(nav, "assign").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows_outlook_and_google_button_when_configured", async () => {
    mockApi({ "GET /api/oauth/providers": both });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    expect(await screen.findByRole("button", { name: "Outlook" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Gmail" }));
    expect(screen.getByRole("button", { name: "Se connecter avec Google" })).toBeInTheDocument();
    // le mot de passe d'application reste possible, replié
    expect(screen.queryByLabelText("Mot de passe d'application")).not.toBeVisible();
    await user.click(screen.getByText("Utiliser un mot de passe d'application"));
    expect(screen.getByLabelText("Mot de passe d'application")).toBeVisible();
  });

  it("hides_oauth_when_not_configured", async () => {
    mockApi({ "GET /api/oauth/providers": { google: false, microsoft: false } });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    await user.click(await screen.findByRole("button", { name: "Gmail" }));
    expect(screen.queryByRole("button", { name: "Outlook" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Se connecter avec Google" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mot de passe d'application")).toBeVisible();
  });

  it("google_button_starts_and_redirects", async () => {
    const calls = mockApi({
      "GET /api/oauth/providers": both,
      "POST /api/oauth/google/start": () => jsonResponse({ url: "https://accounts.google.com/o/oauth2/v2/auth?x=1" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    await user.click(await screen.findByRole("button", { name: "Gmail" }));
    await user.click(screen.getByRole("button", { name: "Se connecter avec Google" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?x=1"));
    expect(calls.find((c) => c.path === "/api/oauth/google/start")!.body).toEqual({});
  });

  it("microsoft_button_starts_and_redirects", async () => {
    mockApi({
      "GET /api/oauth/providers": both,
      "POST /api/oauth/microsoft/start": () => jsonResponse({ url: "https://login.microsoftonline.com/x" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    await user.click(await screen.findByRole("button", { name: "Outlook" }));
    expect(screen.queryByLabelText(/Mot de passe/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Se connecter avec Microsoft" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://login.microsoftonline.com/x"));
  });

  it("iphone_help_line_for_google_only", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)");
    mockApi({ "GET /api/oauth/providers": both });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes/new");
    await user.click(await screen.findByRole("button", { name: "Gmail" }));
    expect(screen.getByText(/application non validée/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Outlook" }));
    expect(screen.queryByText(/application non validée/)).not.toBeInTheDocument();
  });

  it("return_ok_shows_toast", async () => {
    mockApi({ "GET /api/accounts": [oauthAccount] });
    renderWithProviders(<App />, "/settings/boxes?oauth=ok");
    expect(await screen.findByText("Boîte ajoutée")).toBeInTheDocument();
  });

  it("return_reconnected_shows_toast", async () => {
    mockApi({ "GET /api/accounts": [oauthAccount] });
    renderWithProviders(<App />, "/settings/boxes?oauth=reconnected");
    expect(await screen.findByText("Boîte reconnectée")).toBeInTheDocument();
  });

  it.each([
    ["duplicate", /déjà configurée/],
    ["mismatch", /même compte/],
    ["imap", /IMAP/],
    ["denied", /annulée/],
    ["state", /expiré/],
    ["exchange", /refusé la connexion/],
  ])("return_error_%s_shows_message", async (reason, text) => {
    mockApi({ "GET /api/accounts": [] });
    renderWithProviders(<App />, `/settings/boxes?oauth=error&reason=${reason}`);
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("oauth_account_in_error_offers_reconnect", async () => {
    const calls = mockApi({
      "GET /api/accounts": [oauthAccount, outlookAccount],
      "POST /api/oauth/google/start": () => jsonResponse({ url: "https://accounts.google.com/again" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/boxes");
    expect(await screen.findByRole("button", { name: "Se reconnecter avec Microsoft" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mettre à jour le mot de passe" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Se reconnecter avec Google" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/again"));
    expect(calls.find((c) => c.path === "/api/oauth/google/start")!.body).toEqual({ account_id: 7 });
  });
});
