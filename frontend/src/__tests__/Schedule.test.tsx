import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fireEvent } from "@testing-library/react";
import App from "../App";
import { mockApi, setViewportWide } from "../test-fixtures";
import { jsonResponse, renderWithProviders } from "../test-utils";

const schedule = { full_times: ["08:00", "12:00"], light_interval_min: 30, light_start: "07:00", light_end: "23:00", days: [0, 1, 2, 3, 4, 5, 6] };

describe("Planification", () => {
  beforeEach(() => setViewportWide(false));

  it("schedule_add_and_remove_time_saves", async () => {
    const calls = mockApi({ "GET /api/settings/schedule": schedule, "PUT /api/settings/schedule": (c) => jsonResponse(c.body) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/schedule");
    expect(await screen.findByText("08:00")).toBeInTheDocument();
    expect(screen.queryByText(/Apprentissage/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nouvel horaire"), { target: { value: "16:00" } });
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    await user.click(screen.getByRole("button", { name: "Retirer l'horaire 12:00" }));
    await user.click(screen.getByRole("button", { name: "Lundi" }));
    await user.click(screen.getByRole("button", { name: "15 min" }));
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({ full_times: ["08:00", "16:00"], light_interval_min: 15, light_start: "07:00", light_end: "23:00", days: [1, 2, 3, 4, 5, 6] });
    expect(await screen.findByText("Réglages enregistrés")).toBeInTheDocument();
  });

  it("schedule_shows_validation_error", async () => {
    mockApi({ "GET /api/settings/schedule": schedule, "PUT /api/settings/schedule": () => jsonResponse({ detail: [{ msg: "La plage de vérification est invalide", loc: [], type: "x" }] }, 422) });
    const user = userEvent.setup();
    renderWithProviders(<App />, "/settings/schedule");
    await screen.findByText("08:00");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("La plage de vérification est invalide")).toBeInTheDocument();
  });
});
