import { describe, expect, it, vi } from "vitest";
import { fetchAvaturnExport, getAvaturnUrl, MAX_AVATAR_BYTES } from "./provider";

describe("Avaturn provider boundary", () => {
  it("accepts only the configured HTTPS Avaturn subdomain", () => {
    expect(getAvaturnUrl("https://dressme.avaturn.dev/")).toBe("https://dressme.avaturn.dev/");
    expect(() => getAvaturnUrl("http://dressme.avaturn.dev/")).toThrow(/HTTPS/);
    expect(() => getAvaturnUrl("https://attacker.example/")).toThrow(/HTTPS/);
    expect(() => getAvaturnUrl("https://dressme.avaturn.dev/?token=secret")).toThrow(/HTTPS/);
  });

  it("downloads both documented export types without sending cookies", async () => {
    const fetcher = vi.fn(async () => new Response(new Uint8Array([1, 2, 3]), {
      headers: { "Content-Type": "model/gltf-binary", "Content-Length": "3" },
    })) as unknown as typeof fetch;
    const dataFile = await fetchAvaturnExport({
      url: "data:model/gltf-binary;base64,AA==", urlType: "dataURL",
    }, fetcher);
    expect(dataFile.name).toBe("avaturn-avatar.glb");
    expect(dataFile.size).toBe(3);
    expect(fetcher).toHaveBeenCalledWith("data:model/gltf-binary;base64,AA==", {
      credentials: "omit", redirect: "error",
    });

    const remoteFile = await fetchAvaturnExport({
      url: "https://dressme.avaturn.dev/export.glb", urlType: "httpURL",
    }, fetcher);
    expect(remoteFile.size).toBe(3);
    expect(fetcher).toHaveBeenLastCalledWith("https://dressme.avaturn.dev/export.glb", {
      credentials: "omit", redirect: "error", mode: "cors",
    });
  });

  it("rejects unconfigured origins and provider responses above the upload cap", async () => {
    const fetcher = vi.fn();
    await expect(fetchAvaturnExport({
      url: "https://outside.example/avatar.glb", urlType: "httpURL",
    }, fetcher as unknown as typeof fetch)).rejects.toThrow(/unconfigured origin/);
    expect(fetcher).not.toHaveBeenCalled();

    const oversized = vi.fn(async () => new Response(new Uint8Array([1]), {
      headers: { "Content-Type": "model/gltf-binary", "Content-Length": String(MAX_AVATAR_BYTES + 1) },
    })) as unknown as typeof fetch;
    await expect(fetchAvaturnExport({
      url: "data:model/gltf-binary;base64,AA==", urlType: "dataURL",
    }, oversized)).rejects.toThrow(/50 MB limit/);
  });
});
