import { screen } from "@testing-library/react";
import App from "../App";
import { detail, mockApi, setViewportWide } from "../test-fixtures";
import { renderWithProviders } from "../test-utils";

describe("Reader", () => {
  it("reader_shows_summary_and_sandboxed_body", async () => {
    setViewportWide(false);
    mockApi({
      "GET /api/messages/7": detail(7, {
        subject: "Avis de taxe", from_name: "Impôts", summary: "Paiement à faire avant le 15.", attachments: ["avis.pdf"],
        body_html: "<p>Corps nettoyé</p>", open_url: "googlegmail://",
      }),
    });
    renderWithProviders(<App />, "/mail/7");
    expect(await screen.findByText("Paiement à faire avant le 15.")).toBeInTheDocument();
    expect(screen.getByText("Résumé de Claude")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Avis de taxe" })).toBeInTheDocument();
    expect(screen.getByText(/Impôts/)).toBeInTheDocument();
    const frame = screen.getByTitle("Contenu du mail") as HTMLIFrameElement;
    const sandbox = frame.getAttribute("sandbox") ?? "";
    expect(sandbox).toContain("allow-popups");
    for (const bad of ["allow-scripts", "allow-same-origin", "allow-forms"]) expect(sandbox).not.toContain(bad);
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("srcdoc")).toContain("Corps nettoyé");
    expect(screen.getByText("avis.pdf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ouvrir l'app" })).toHaveAttribute("href", "googlegmail://");
  });

  it("reader_text_fallback_and_no_open_app", async () => {
    setViewportWide(false);
    mockApi({ "GET /api/messages/8": detail(8, { body_html: null, body_text: "Texte brut", open_url: null }) });
    renderWithProviders(<App />, "/mail/8");
    expect(await screen.findByText("Texte brut")).toBeInTheDocument();
    expect(screen.queryByTitle("Contenu du mail")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ouvrir l'app" })).not.toBeInTheDocument();
  });

  it("reader_error_message", async () => {
    setViewportWide(false);
    mockApi({ "GET /api/messages/9": () => new Response(JSON.stringify({ detail: "Impossible de récupérer ce mail" }), { status: 502, headers: { "Content-Type": "application/json" } }) });
    renderWithProviders(<App />, "/mail/9");
    expect(await screen.findByText("Impossible de récupérer ce mail")).toBeInTheDocument();
  });
});

describe("layout", () => {
  it("layout_two_columns_from_900px", async () => {
    setViewportWide(true);
    mockApi({ "GET /api/messages/3": detail(3, { subject: "Relevé disponible" }) });
    renderWithProviders(<App />, "/box/all/inbox/mail/3");
    expect(await screen.findByTitle("Contenu du mail")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Réception" })).toBeInTheDocument();
    expect(screen.getByText("Promo ce week-end")).toBeInTheDocument();
  });

  it("layout_single_column_below_900px", async () => {
    setViewportWide(false);
    mockApi({ "GET /api/messages/3": detail(3) });
    renderWithProviders(<App />, "/box/all/inbox/mail/3");
    expect(await screen.findByTitle("Contenu du mail")).toBeInTheDocument();
    expect(screen.queryByText("Promo ce week-end")).not.toBeInTheDocument();
  });

  it("layout_wide_without_mail_shows_placeholder", async () => {
    setViewportWide(true);
    mockApi({});
    renderWithProviders(<App />, "/box/all/inbox");
    expect(await screen.findByText("Sélectionne un mail pour le lire")).toBeInTheDocument();
  });
});
