import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const status = { connected: true, last_ok_at: "2026-11-05T07:02:00Z", last_error: null, token_set_at: "2026-01-01T00:00:00Z", expires_at: "2027-09-13T00:00:00Z", days_left: 312 };

describe("Page Claude", () => {
  beforeEach(() => setViewportWide(false));

  it("claudepage_shows_days_left_and_saves_token", async () => {
    let current = status;
    const calls = mockApi({
      "GET /api/claude/status": () => jsonResponse(current),
      "POST /api/claude/token": () => { current = { ...status, days_left: 365 }; return jsonResponse({ ok: true, detail: "Jeton enregistré" }); },
    });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    expect(await screen.findByText("Connecté")).toBeInTheDocument();
    expect(screen.getByText("dans 312 jours")).toBeInTheDocument();
    expect(screen.getByText(/13\/09\/2027/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "312");
    await user.click(screen.getByRole("button", { name: "Reconnecter" }));
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
    mockApi({ "POST /api/claude/token": () => jsonResponse({ ok: false, detail: "Jeton refusé par Claude" }) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/claude");
    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));
    await user.type(screen.getByLabelText("Jeton Claude"), "bad");
    await user.click(screen.getByRole("button", { name: "Tester et enregistrer" }));
    expect(await screen.findByText("Jeton refusé par Claude")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("bad")).not.toBeInTheDocument();
  });
});
