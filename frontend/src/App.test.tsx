import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { setCsrfToken } from "./api";

const fixtureGarment = {
  id: "garment-1", category: "shirt", garment_photo_type: "flat-lay", vton_eligibility: { status: "ineligible", eligible: false, candidate_category: null, reason: "unsupported_category", policy_version: "fixture" },
  vton_eligibility_version: "fixture", color: "blue", pattern: "solid", sleeve_length: "short", description: "A blue shirt.", description_is_manual: false,
  name: "Blue shirt", notes: null, image_url: "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=", field_sources: {}, description_provenance: {},
};
const pendingUpload = {
  id: "pending-1", image_url: "data:image/png;base64,AA==", image_sha256: "fixture", width: 600, height: 800,
  quality: { warnings: [], advisory_only: true },
  prediction: { category: "shirt", score_type: "uncalibrated_softmax", suggestions: [{ category: "shirt", score: 0.8 }], category_confident: false, needs_user_review: true, description: "A shirt.", description_fields: {}, attributes: {} },
  expires_at: "2026-10-08T12:00:00Z",
};

function authenticatedFetchMock(garments: unknown[] = [], jobs: Record<string, unknown>[] = []) {
  let currentJobs = jobs;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), window.location.origin);
    const method = init?.method ?? "GET";
    if (url.pathname === "/auth/me") return Response.json({ id: "u1", email: "a@example.com", role: "USER" });
    if (url.pathname === "/auth/logout" && method === "POST") return new Response(null, { status: 204 });
    if (url.pathname === "/auth/login" && method === "POST") return Response.json({ user: { id: "u1", email: "a@example.com", role: "USER" }, csrf_token: "csrf-value" });
    if (url.pathname === "/garments" && method === "GET") return Response.json({ items: garments, page: 1, page_size: 48, total: garments.length });
    if (url.pathname === "/garments/analyze" && method === "POST") return Response.json(pendingUpload);
    if (url.pathname === "/garments/describe") return Response.json({ text: "A shirt." });
    if (url.pathname === "/person-photos") return Response.json([]);
    if (url.pathname === "/try-on/jobs") return Response.json({ items: currentJobs });
    if (/^\/try-on\/jobs\/[^/]+\/cancel$/.test(url.pathname) && method === "POST") {
      currentJobs = currentJobs.map((job) => ({ ...job, state: "cancelled" }));
      return Response.json(currentJobs[0]);
    }
    if (url.pathname.startsWith("/garments/") && method === "DELETE") return Response.json({ status: "deleted" });
    throw new Error(`Unexpected request: ${method} ${url.pathname}`);
  });
}

beforeEach(() => { window.history.replaceState(null, "", "/"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); setCsrfToken(null); });

describe("authentication shell", () => {
  it("offers registration and submits credentials without persisting an access token", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/auth/me") return Response.json({ error: { message: "Please sign in." } }, { status: 401 });
      if (url === "/auth/login") return Response.json({ user: { id: "u1", email: "a@example.com", role: "USER" }, csrf_token: "csrf-value" });
      if (url.startsWith("/garments?")) return Response.json({ items: [], page: 1, page_size: 48, total: 0 });
      if (url === "/person-photos") return Response.json([]);
      if (url.startsWith("/try-on/jobs?")) return Response.json({ items: [] });
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New to DressMe? Create an account" }));
    expect(screen.getByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Already have an account? Sign in" }));
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "a-long-and-unique-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/auth/login", expect.objectContaining({ credentials: "include" }));
    expect(sessionStorage.getItem("dressme.csrf")).toBe("csrf-value");
    expect(sessionStorage.getItem("access_token")).toBeNull();
    expect(screen.getByRole("button", { name: "Wardrobe" })).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: "Try-on preview" }));
    expect(screen.getByRole("button", { name: "Try-on preview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Wardrobe" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByText(/MOCK MODE · NO AI TRY-ON/)).toBeInTheDocument();
    expect(screen.getByText(/This is a mock workflow\. It does not generate an outfit/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No jobs yet" })).toBeInTheDocument();
  });

  it("keeps mobile navigation keyboard-operable and follows route history", async () => {
    authenticatedFetchMock();
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();

    const menu = screen.getByRole("button", { name: "Menu" });
    await user.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Wardrobe" })).toHaveAttribute("aria-current", "page");

    screen.getByRole("button", { name: "Try-on preview" }).focus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Menu" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Menu" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Menu" }));
    await user.click(screen.getByRole("button", { name: "Try-on preview" }));
    expect(window.location.hash).toBe("#try-on");
    expect(await screen.findByRole("heading", { name: "Try-on preview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try-on preview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Menu" })).toHaveFocus();

    act(() => {
      window.history.replaceState(null, "", "#wardrobe");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
  });

  it("closes the mobile menu across logout and login", async () => {
    authenticatedFetchMock();
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    const menuToggle = screen.getByRole("button", { name: "Menu" });
    await user.click(menuToggle);
    expect(menuToggle).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "a-long-and-unique-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Menu" })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps mock job labels and cancel controls readable and operable", async () => {
    const job = {
      id: "job-1", state: "queued", mode: "mock", status_url: "/try-on/jobs/job-1", result_url: null,
      error_code: null, cancellation_requested: false, settings_snapshot: {}, result_metadata: null,
      created_at: "2026-10-08T10:00:00Z", updated_at: "2026-10-08T10:00:00Z",
    };
    const fetchMock = authenticatedFetchMock([], [job]);
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: /^Your wardrobe$/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Menu" }));
    await user.click(screen.getByRole("button", { name: "Try-on preview" }));
    expect(screen.getByText(/MOCK MODE · NO AI TRY-ON/)).toBeInTheDocument();
    expect(screen.getByText("MOCK · NO TRY-ON GENERATED")).toBeInTheDocument();
    expect(screen.getByText("Status: queued")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Status: cancelled")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/try-on/jobs/job-1/cancel", expect.objectContaining({ method: "POST" }));
  });

  it("announces invalid garment files and permits choosing a supported image", async () => {
    authenticatedFetchMock();
    const user = userEvent.setup();
    if (!URL.createObjectURL) Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:fixture") });
    if (!URL.revokeObjectURL) Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add a garment" }));
    const input = screen.getByLabelText("Choose a garment photo");
    fireEvent.change(input, { target: { files: [new File(["gif"], "notes.gif", { type: "image/gif" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a JPEG, PNG, or WEBP image.");
    expect(screen.getByRole("button", { name: "Get suggestions" })).toBeDisabled();

    const oversized = new File(["x"], "large.png", { type: "image/png" });
    Object.defineProperty(oversized, "size", { value: 10 * 1024 * 1024 + 1 });
    fireEvent.change(input, { target: { files: [oversized] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("This image is larger than 10 MB.");

    fireEvent.change(input, { target: { files: [new File(["png"], "shirt.png", { type: "image/png" })] } });
    expect(await screen.findByText(/shirt\.png · PNG/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get suggestions" })).toBeEnabled();
  });

  it("keeps an analyzed garment draft when navigating away and back", async () => {
    const fetchMock = authenticatedFetchMock();
    const user = userEvent.setup();
    if (!URL.createObjectURL) Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:fixture") });
    if (!URL.revokeObjectURL) Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add a garment" }));
    fireEvent.change(screen.getByLabelText("Choose a garment photo"), { target: { files: [new File(["png"], "shirt.png", { type: "image/png" })] } });
    await user.click(screen.getByRole("button", { name: "Get suggestions" }));
    expect(await screen.findByRole("heading", { name: "Check the details" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Menu" }));
    await user.click(screen.getByRole("button", { name: "Wardrobe" }));
    await user.click(screen.getByRole("button", { name: "Menu" }));
    await user.click(screen.getByRole("button", { name: "Add a garment" }));
    expect(await screen.findByRole("heading", { name: "Check the details" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => String(input) === "/garments/uploads/pending-1" && init?.method === "DELETE")).toBe(false);
  });

  it("uses an accessible confirmation and returns focus when a deletion is cancelled", async () => {
    authenticatedFetchMock([fixtureGarment]);
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    const deleteButton = await screen.findByRole("button", { name: "Delete" });
    await user.click(deleteButton);
    expect(await screen.findByRole("dialog", { name: "Delete this garment?" })).toBeInTheDocument();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    await user.click(cancel);
    await waitFor(() => expect(deleteButton).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalledWith("/garments/garment-1", expect.objectContaining({ method: "DELETE" }));
  });

  it("keeps the wardrobe shell usable and announces a garment API error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/auth/me") return Response.json({ id: "u1", email: "a@example.com", role: "USER" });
      if (url.pathname === "/garments") return Response.json({ error: { message: "Wardrobe service is unavailable." } }, { status: 503 });
      if (url.pathname === "/person-photos") return Response.json([]);
      if (url.pathname === "/try-on/jobs") return Response.json({ items: [] });
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your wardrobe" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Wardrobe service is unavailable.");
    expect(screen.getByRole("button", { name: "＋ Add a garment" })).toBeEnabled();
  });
});
