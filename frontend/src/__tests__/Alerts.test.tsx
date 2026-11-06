import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const alerts = {
  webpush: false, gotify: false, gotify_url: null, notify_tt: true, notify_important: true, notify_action: true, notify_summary: false,
  quiet_enabled: true, quiet_from: "22:00", quiet_to: "07:00", quiet_tt_bypass: true, gotify_token_set: false,
};

function stubStandalone(standalone: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: q.includes("standalone") ? standalone : false, media: q, addEventListener: () => {}, removeEventListener: () => {},
  }));
}

function stubPush(permission: NotificationPermission) {
  const subscribe = vi.fn(async () => ({ toJSON: () => ({ endpoint: "https://push.example/abc", keys: { p256dh: "P", auth: "A" } }) }));
  Object.defineProperty(navigator, "serviceWorker", { value: { ready: Promise.resolve({ pushManager: { subscribe } }) }, configurable: true });
  vi.stubGlobal("PushManager", class {});
  vi.stubGlobal("Notification", { requestPermission: vi.fn(async () => permission), permission: "default" });
  return subscribe;
}

describe("Alertes", () => {
  beforeEach(() => setViewportWide(false));
  afterEach(() => { Reflect.deleteProperty(navigator, "serviceWorker"); Reflect.deleteProperty(navigator, "userAgent"); });

  it("alerts_webpush_requires_installed_app", async () => {
    stubStandalone(false);
    Object.defineProperty(navigator, "userAgent", { value: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", configurable: true });
    const subscribe = stubPush("granted");
    const calls = mockApi({ "GET /api/settings/alerts": alerts });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/alerts");
    await user.click(await screen.findByRole("switch", { name: "Notification iPhone" }));
    expect(await screen.findByText("Installe d'abord l'appli : Partager › Sur l'écran d'accueil")).toBeInTheDocument();
    expect(subscribe).not.toHaveBeenCalled();
    expect(calls.some((c) => c.path === "/api/push/subscribe")).toBe(false);
    expect(screen.getByRole("switch", { name: "Notification iPhone" })).toHaveAttribute("aria-checked", "false");
  });

  it("alerts_webpush_toggle_subscribes", async () => {
    stubStandalone(true);
    const subscribe = stubPush("granted");
    const calls = mockApi({
      "GET /api/settings/alerts": alerts,
      "GET /api/push/vapid-public-key": { key: "BEl0" },
      "POST /api/push/subscribe": () => jsonResponse({ ok: true }),
      "PUT /api/settings/alerts": (c) => jsonResponse({ ...(c.body as object), gotify_token_set: false }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/alerts");
    await user.click(await screen.findByRole("switch", { name: "Gotify" })); // modification locale non enregistrée
    await user.click(screen.getByRole("switch", { name: "Notification iPhone" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(calls.find((c) => c.path === "/api/push/subscribe")!.body).toEqual({ endpoint: "https://push.example/abc", keys: { p256dh: "P", auth: "A" } });
    const { gotify_token_set: _s, ...serverValues } = alerts;
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ ...serverValues, webpush: true });
    expect(await screen.findByText("Réglages enregistrés")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Notification iPhone" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch", { name: "Gotify" })).toHaveAttribute("aria-checked", "true"); // brouillon conservé
    await user.click(screen.getByRole("switch", { name: "Notification iPhone" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PUT")[1].body).toMatchObject({ webpush: false, gotify: false });
  });

  it("alerts_webpush_denied_shows_toast", async () => {
    stubStandalone(true);
    stubPush("denied");
    mockApi({ "GET /api/settings/alerts": alerts, "GET /api/push/vapid-public-key": { key: "BEl0" } });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/alerts");
    await user.click(await screen.findByRole("switch", { name: "Notification iPhone" }));
    expect(await screen.findByText("Notifications refusées dans les réglages du navigateur")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Notification iPhone" })).toHaveAttribute("aria-checked", "false");
  });

  it("alerts_gotify_fields_not_seen_as_login_form", async () => {
    mockApi({ "GET /api/settings/alerts": { ...alerts, gotify: true } });
    renderWithProviders(<App />, "/settings/alerts");
    const url = await screen.findByLabelText("URL du serveur Gotify");
    const token = screen.getByLabelText("Jeton de l'application Gotify");
    // un champ type=password fait croire à iOS / aux gestionnaires de mots de passe à un formulaire de connexion
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(token).toHaveAttribute("type", "text");
    expect(token).toHaveClass("secret-input");
    for (const el of [url, token]) {
      expect(el).toHaveAttribute("autocomplete", "off");
      expect(el).toHaveAttribute("data-1p-ignore");
      expect(el).toHaveAttribute("data-lpignore", "true");
    }
    expect(url).toHaveAttribute("type", "url");
    expect(screen.getByText("Adresse du serveur Gotify")).toBeInTheDocument();
    expect(screen.getByText("Jeton d'application (Gotify › Apps)")).toBeInTheDocument();
  });

  it("alerts_gotify_save_and_test", async () => {
    const calls = mockApi({
      "GET /api/settings/alerts": alerts,
      "PUT /api/settings/alerts": (c) => jsonResponse({ ...(c.body as object), gotify_token: undefined, gotify_token_set: true }),
      "POST /api/alerts/test": () => jsonResponse({ ok: true, detail: "Notification envoyée" }),
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/alerts");
    await user.click(await screen.findByRole("switch", { name: "Gotify" }));
    await user.type(screen.getByLabelText("URL du serveur Gotify"), "https://g.local");
    await user.type(screen.getByLabelText("Jeton de l'application Gotify"), "tok");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    const put = calls.find((c) => c.method === "PUT")!.body as Record<string, unknown>;
    expect(put).toMatchObject({ gotify: true, gotify_url: "https://g.local", gotify_token: "tok" });
    expect(put).not.toHaveProperty("gotify_token_set");
    await user.click(await screen.findByRole("button", { name: "Envoyer une notification de test" }));
    expect(calls.find((c) => c.path === "/api/alerts/test")!.body).toEqual({ channel: "gotify" });
    expect(await screen.findByText("Notification envoyée")).toBeInTheDocument();
  });
});
