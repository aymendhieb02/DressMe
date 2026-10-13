import type { ExportAvatarResult } from "@avaturn/sdk";

export const AVATAR_CONSENT_VERSION = "avaturn-photo-processing-v1";
export const MAX_AVATAR_BYTES = 50 * 1024 * 1024;
const DEFAULT_AVATURN_URL = "https://dressme.avaturn.dev/";

export function getAvaturnUrl(raw = import.meta.env.VITE_AVATURN_URL || DEFAULT_AVATURN_URL): string {
  let configured: URL;
  try {
    configured = new URL(raw);
  } catch {
    throw new Error("Avaturn is not configured. Set VITE_AVATURN_URL to your Avaturn creator URL.");
  }
  if (
    configured.protocol !== "https:"
    || configured.username
    || configured.password
    || configured.search
    || configured.hash
    || !/^[a-z0-9-]+\.avaturn\.dev$/i.test(configured.hostname)
  ) {
    throw new Error("The Avaturn URL must use HTTPS on your configured .avaturn.dev subdomain.");
  }
  return configured.href;
}

function allowedExportOrigins(): Set<string> {
  const origins = new Set([new URL(getAvaturnUrl()).origin]);
  const configured = import.meta.env.VITE_AVATURN_EXPORT_ORIGINS ?? "";
  for (const raw of configured.split(",")) {
    const value = raw.trim();
    if (!value) continue;
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "https:" || parsed.origin !== value.replace(/\/$/, "")) {
        throw new Error();
      }
      origins.add(parsed.origin);
    } catch {
      throw new Error("VITE_AVATURN_EXPORT_ORIGINS must contain exact HTTPS origins separated by commas.");
    }
  }
  return origins;
}

async function readBounded(response: Response): Promise<Blob> {
  if (!response.ok) throw new Error("Avaturn export download failed (" + response.status + ").");
  const type = response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() ?? "";
  if (type && type !== "model/gltf-binary" && type !== "application/octet-stream") {
    throw new Error("Avaturn returned a non-GLB export. Nothing was saved.");
  }
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_AVATAR_BYTES) {
    throw new Error("Avaturn's export is larger than DressMe's current 50 MB limit.");
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const blob = await response.blob();
    if (blob.size > MAX_AVATAR_BYTES) throw new Error("Avaturn's export is larger than DressMe's current 50 MB limit.");
    return new Blob([blob], { type: "model/gltf-binary" });
  }
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_AVATAR_BYTES) {
        await reader.cancel();
        throw new Error("Avaturn's export is larger than DressMe's current 50 MB limit.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const parts = chunks.map((chunk) => chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.byteLength) as ArrayBuffer);
  return new Blob(parts, { type: "model/gltf-binary" });
}

export async function fetchAvaturnExport(
  result: Pick<ExportAvatarResult, "url" | "urlType">,
  fetcher: typeof fetch = fetch,
): Promise<File> {
  if (!result.url || typeof result.url !== "string") throw new Error("Avaturn did not return an export URL.");
  if (result.urlType === "dataURL") {
    if (!result.url.startsWith("data:") || result.url.length > Math.ceil(MAX_AVATAR_BYTES * 4 / 3) + 1024) {
      throw new Error("Avaturn's embedded export exceeds DressMe's current 50 MB limit.");
    }
    const response = await fetcher(result.url, { credentials: "omit", redirect: "error" });
    return new File([await readBounded(response)], "avaturn-avatar.glb", { type: "model/gltf-binary" });
  }
  if (result.urlType !== "httpURL") throw new Error("Avaturn returned an unsupported export type.");
  let target: URL;
  try {
    target = new URL(result.url);
  } catch {
    throw new Error("Avaturn returned an invalid export URL.");
  }
  if (target.protocol !== "https:" || target.username || target.password || !allowedExportOrigins().has(target.origin)) {
    throw new Error("Avaturn's export uses an unconfigured origin. Add its exact HTTPS origin to VITE_AVATURN_EXPORT_ORIGINS and reload.");
  }
  try {
    const response = await fetcher(target.href, { credentials: "omit", redirect: "error", mode: "cors" });
    return new File([await readBounded(response)], "avaturn-avatar.glb", { type: "model/gltf-binary" });
  } catch (cause) {
    if (cause instanceof Error && cause.message.includes("Avaturn")) throw cause;
    throw new Error("The browser could not download Avaturn's export. Check provider CORS and the exact export origin; no server-side URL fetch was attempted.");
  }
}
