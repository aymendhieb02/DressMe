import { ApiError } from "../api";

export async function downloadPrivateAvatarModel(modelUrl: string): Promise<Blob> {
  const target = new URL(modelUrl, window.location.origin);
  if (target.origin !== window.location.origin || !/^\/avatars\/[0-9a-f-]+\/model$/.test(target.pathname)) {
    throw new Error("The saved avatar address is invalid. Reload the page and try again.");
  }
  const response = await fetch(target.pathname, { credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message ?? body?.detail?.message ?? "Request failed (" + response.status + ").";
    throw new ApiError(message, response.status);
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.startsWith("model/gltf-binary") && !contentType.startsWith("application/octet-stream")) {
    throw new Error("The saved avatar is not a binary GLB file.");
  }
  const size = Number(response.headers.get("content-length"));
  if (Number.isFinite(size) && size > 50 * 1024 * 1024) {
    throw new Error("The saved avatar exceeds the viewer's 50 MB limit.");
  }
  const blob = await response.blob();
  if (blob.size > 50 * 1024 * 1024) {
    throw new Error("The saved avatar exceeds the viewer's 50 MB limit.");
  }
  return blob;
}
