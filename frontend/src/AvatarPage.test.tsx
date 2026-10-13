import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AvatarPage from "./AvatarPage";
import { setCsrfToken } from "./api";
import { fetchAvaturnExport } from "./avatar/provider";

const harness = vi.hoisted(() => ({ sdk: null as any }));

vi.mock("@avaturn/sdk", () => {
  class MockAvaturnSDK {
    callbacks = new Map<string, (value: any) => void>();
    init = vi.fn(async (container: HTMLElement | null) => {
      const frame = document.createElement("iframe");
      container?.append(frame);
      return this;
    });
    destroy = vi.fn();
    constructor() { harness.sdk = this; }
    on(event: string, callback: (value: any) => void) {
      this.callbacks.set(event, callback);
      return this;
    }
    emit(event: string, value: any) { this.callbacks.get(event)?.(value); }
  }
  return { AvaturnSDK: MockAvaturnSDK };
});

vi.mock("@google/model-viewer", () => ({}));
vi.mock("./avatar/provider", () => ({
  AVATAR_CONSENT_VERSION: "avaturn-photo-processing-v1",
  MAX_AVATAR_BYTES: 50 * 1024 * 1024,
  getAvaturnUrl: () => "https://dressme.avaturn.dev/",
  fetchAvaturnExport: vi.fn(),
}));

const consent = {
  id: "consent-1",
  provider: "avaturn",
  consent_version: "avaturn-photo-processing-v1",
  consented_at: "2026-10-13T09:00:00Z",
};
const savedAvatar = {
  id: "123e4567-e89b-12d3-a456-426614174000",
  provider: "avaturn",
  provider_avatar_id: "avt-123",
  model_url: "/avatars/123e4567-e89b-12d3-a456-426614174000/model",
  asset_sha256: "sha256-fixture",
  asset_size: 480,
  version: 1,
  consent_version: "avaturn-photo-processing-v1",
  created_at: "2026-10-13T09:01:00Z",
  updated_at: "2026-10-13T09:01:00Z",
};

function installFetchMock(saveStatus = 200) {
  const requests: { path: string; method: string; body: BodyInit | null | undefined }[] = [];
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), window.location.origin);
    const method = String(init?.method ?? "GET").toUpperCase();
    requests.push({ path: url.pathname, method, body: init?.body });
    if (url.pathname === "/avatars/current" && method === "GET") return Response.json(null);
    if (url.pathname === "/avatars/consents" && method === "POST") return Response.json(consent, { status: 201 });
    if (url.pathname === "/avatars/current" && method === "PUT") {
      if (saveStatus !== 200) return Response.json({ error: { message: "GLB storage unavailable." } }, { status: saveStatus });
      return Response.json(savedAvatar);
    }
    if (url.pathname === "/avatars/123e4567-e89b-12d3-a456-426614174000/model" && method === "GET") {
      return new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "model/gltf-binary", "Content-Length": "3" } });
    }
    return Response.json({ error: { message: "Unhandled test request." } }, { status: 404 });
  });
  return { fetchMock, requests };
}

describe("private Avaturn avatar flow", () => {
  beforeEach(() => {
    harness.sdk = null;
    vi.mocked(fetchAvaturnExport).mockReset();
    setCsrfToken("csrf-fixture");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:private-avatar") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    setCsrfToken(null);
  });

  it("requires external-photo consent, then requires a separate private save after export", async () => {
    const { requests } = installFetchMock();
    const file = new File(["synthetic GLB"], "avaturn-avatar.glb", { type: "model/gltf-binary" });
    vi.mocked(fetchAvaturnExport).mockResolvedValue(file);
    const user = userEvent.setup();
    render(<AvatarPage />);

    await user.click(await screen.findByRole("button", { name: "Create avatar" }));
    expect(screen.getByRole("heading", { name: "Photo processing and storage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "terms" })).toHaveAttribute("target", "_blank");
    expect(harness.sdk).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: /consent to Avaturn processing/ }));
    await user.click(screen.getByRole("button", { name: "Continue to Avaturn" }));
    expect(await screen.findByRole("heading", { name: "Customize your avatar" })).toBeInTheDocument();
    expect(harness.sdk.init).toHaveBeenCalledWith(expect.any(HTMLElement), {
      url: "https://dressme.avaturn.dev/",
      iframeClassName: "avaturn-sdk-iframe",
    });
    expect(await screen.findByTitle("Avaturn 3D avatar creator")).toBeInTheDocument();

    act(() => harness.sdk.emit("export", {
      avatarId: "avt-123",
      bodyId: "unused-body",
      sessionId: "session-secret-must-not-be-uploaded",
      avatarSupportsFaceAnimations: false,
      gender: "male",
      url: "data:model/gltf-binary;base64,fixture",
      urlType: "dataURL",
    }));
    expect(await screen.findByRole("heading", { name: "Review your 3D model" })).toBeInTheDocument();
    expect(requests.some((request) => request.path === "/avatars/current" && request.method === "PUT")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Save avatar privately" }));
    await waitFor(() => expect(requests.some((request) => request.path === "/avatars/current" && request.method === "PUT")).toBe(true));
    const save = requests.find((request) => request.path === "/avatars/current" && request.method === "PUT");
    const body = save?.body as FormData;
    expect((body.get("model") as File).name).toBe("avaturn-avatar.glb");
    expect(body.get("provider_avatar_id")).toBe("avt-123");
    expect(body.get("consent_id")).toBe("consent-1");
    expect([...body.keys()]).not.toContain("sessionId");
    expect(requests.some((request) => request.path === "/avatars/123e4567-e89b-12d3-a456-426614174000/model")).toBe(true);
    expect(await screen.findByText(/Your 3D avatar is saved privately/)).toBeInTheDocument();
  });

  it("keeps the exported GLB available and reports failed private saves", async () => {
    const { requests } = installFetchMock(503);
    vi.mocked(fetchAvaturnExport).mockResolvedValue(new File(["synthetic GLB"], "avaturn-avatar.glb", { type: "model/gltf-binary" }));
    const user = userEvent.setup();
    render(<AvatarPage />);
    await user.click(await screen.findByRole("button", { name: "Create avatar" }));
    await user.click(screen.getByRole("checkbox", { name: /consent to Avaturn processing/ }));
    await user.click(screen.getByRole("button", { name: "Continue to Avaturn" }));
    await waitFor(() => expect(harness.sdk).not.toBeNull());
    act(() => harness.sdk.emit("export", {
      avatarId: "avt-123", sessionId: "secret", url: "data:model/gltf-binary;base64,fixture", urlType: "dataURL",
    }));
    await user.click(await screen.findByRole("button", { name: "Save avatar privately" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("GLB storage unavailable.");
    expect(screen.getByRole("button", { name: "Save avatar privately" })).toBeEnabled();
    expect(requests.filter((request) => request.path === "/avatars/current" && request.method === "PUT")).toHaveLength(1);
  });
});
