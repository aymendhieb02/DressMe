import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); });

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
    await user.click(screen.getByRole("button", { name: "Try-on preview" }));
    expect(await screen.findByText(/MOCK MODE · NO AI TRY-ON/)).toBeInTheDocument();
    expect(screen.getByText(/This is a mock workflow\. It does not generate an outfit/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No jobs yet" })).toBeInTheDocument();
  });
});
