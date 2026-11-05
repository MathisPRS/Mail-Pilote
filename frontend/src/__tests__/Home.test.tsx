import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

describe("Home", () => {
  beforeEach(() => setViewportWide(false));

  it("home_lists_all_boxes_first", async () => {
    mockApi({});
    renderWithProviders(<App />, "/");
    const cards = await screen.findAllByTestId("box-card");
    expect(cards.map((c) => within(c).getByText(/Toutes les boîtes|Gmail|Outlook/).textContent)).toEqual([
      "Toutes les boîtes", "Gmail", "Outlook",
    ]);
    expect(within(cards[0]).getByLabelText("5 non lus")).toBeInTheDocument();
    expect(within(cards[0]).getByText("Ouverture TT+ jeudi")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Rien d'important à signaler")).toBeInTheDocument();
    expect(await screen.findByText("Claude · analysé à 08:01")).toBeInTheDocument();
    expect(screen.getByText("Prochaine analyse à 13:00")).toBeInTheDocument();
  });

  it("home_shows_claude_disconnected", async () => {
    mockApi({ "GET /api/claude/status": { connected: false, last_ok_at: null, last_error: "x", token_set_at: null, expires_at: null, days_left: null } });
    renderWithProviders(<App />, "/");
    expect(await screen.findByText("Claude déconnecté")).toBeInTheDocument();
  });

  it("home_card_navigates_to_inbox", async () => {
    const calls = mockApi({});
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    await user.click((await screen.findAllByTestId("box-card"))[2]);
    expect(await screen.findByRole("heading", { name: "Réception" })).toBeInTheDocument();
    const list = calls.find((c) => c.path === "/api/messages")!;
    expect(list.query.get("account")).toBe("2");
    expect(list.query.get("folder")).toBe("inbox");
  });

  it("home_avatar_goes_to_settings", async () => {
    mockApi({ "GET /api/auth/me": () => jsonResponse({ username: "m", display_name: "Mathis" }) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/");
    await user.click(await screen.findByRole("button", { name: "Profil et réglages" }));
    expect(await screen.findByRole("heading", { name: "Réglages" })).toBeInTheDocument();
  });
});
