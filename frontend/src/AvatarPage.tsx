import { AvaturnSDK, type ExportAvatarResult } from "@avaturn/sdk";
import type { ModelViewerElement } from "@google/model-viewer";
import { useCallback, useEffect, useRef, useState, createElement } from "react";
import { api, type Avatar, type AvatarConsent } from "./api";
import { downloadPrivateAvatarModel } from "./avatar/api";
import { AVATAR_CONSENT_VERSION, fetchAvaturnExport, MAX_AVATAR_BYTES, getAvaturnUrl } from "./avatar/provider";

type ExportSource = Pick<ExportAvatarResult, "url" | "urlType"> & { avatarId: string };
type ExportState = "idle" | "downloading" | "ready" | "error";

function sizeLabel(size: number) {
  return size >= 1024 * 1024 ? (size / (1024 * 1024)).toFixed(1) + " MB" : Math.max(1, Math.round(size / 1024)) + " KB";
}

export default function AvatarPage() {
  const [avatar, setAvatar] = useState<Avatar | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(true);
  const [modelUrl, setModelUrl] = useState("");
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState("");
  const [viewerRegistered, setViewerRegistered] = useState(false);
  const [viewerError, setViewerError] = useState("");
  const [showConsent, setShowConsent] = useState(false);
  const [acceptedConsent, setAcceptedConsent] = useState(false);
  const [consent, setConsent] = useState<AvatarConsent | null>(null);
  const [creatorOpen, setCreatorOpen] = useState(false);
  const [creatorPhase, setCreatorPhase] = useState<"loading" | "ready" | "timeout" | "error">("loading");
  const [creatorError, setCreatorError] = useState("");
  const [creatorAttempt, setCreatorAttempt] = useState(0);
  const [creatorBusy, setCreatorBusy] = useState(false);
  const [exportPhase, setExportPhase] = useState<ExportState>("idle");
  const [exportError, setExportError] = useState("");
  const [exportFile, setExportFile] = useState<File | null>(null);
  const [exportAvatarId, setExportAvatarId] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [pageError, setPageError] = useState("");
  const [viewerReady, setViewerReady] = useState(false);

  const creatorContainerRef = useRef<HTMLDivElement>(null);
  const sdkRef = useRef<AvaturnSDK | null>(null);
  const exportSourceRef = useRef<ExportSource | null>(null);
  const exportOperationRef = useRef(0);
  const mountedRef = useRef(false);
  const viewerRef = useRef<ModelViewerElement | null>(null);
  const deleteDialogRef = useRef<HTMLDialogElement>(null);
  const objectUrlRef = useRef("");

  useEffect(() => {
    mountedRef.current = true;
    let active = true;
    api<Avatar | null>("/avatars/current")
      .then((current) => { if (active) setAvatar(current); })
      .catch((cause) => { if (active) setPageError(cause instanceof Error ? cause.message : "The saved avatar could not be loaded."); })
      .finally(() => { if (active) setAvatarLoading(false); });
    return () => {
      active = false;
      mountedRef.current = false;
      exportOperationRef.current += 1;
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    if (!avatar) {
      setModelUrl("");
      setModelLoading(false);
      setModelError("");
      return;
    }
    let active = true;
    setModelLoading(true);
    setModelError("");
    setViewerError("");
    setViewerReady(false);
    setModelUrl("");
    downloadPrivateAvatarModel(avatar.model_url)
      .then((blob) => {
        const nextUrl = URL.createObjectURL(blob);
        if (!active) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = nextUrl;
        setModelUrl(nextUrl);
      })
      .catch((cause) => { if (active) setModelError(cause instanceof Error ? cause.message : "The saved avatar could not be opened."); })
      .finally(() => { if (active) setModelLoading(false); });
    return () => {
      active = false;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = "";
      }
    };
  }, [avatar]);

  useEffect(() => {
    const dialog = deleteDialogRef.current;
    if (!dialog) return;
    if (deleteDialogOpen && !dialog.open) dialog.showModal();
    else if (!deleteDialogOpen && dialog.open) dialog.close();
  }, [deleteDialogOpen]);

  const importExport = useCallback(async (source: ExportSource) => {
    const operation = ++exportOperationRef.current;
    setExportPhase("downloading");
    setExportError("");
    setExportFile(null);
    try {
      const file = await fetchAvaturnExport(source);
      if (!mountedRef.current || operation !== exportOperationRef.current) return;
      setExportFile(file);
      setExportAvatarId(source.avatarId);
      setExportPhase("ready");
      exportSourceRef.current = null;
    } catch (cause) {
      if (!mountedRef.current || operation !== exportOperationRef.current) return;
      setExportError(cause instanceof Error ? cause.message : "Avaturn's export could not be imported.");
      setExportPhase("error");
    }
  }, []);

  useEffect(() => {
    if (!creatorOpen) return;
    let active = true;
    let callbackHandled = false;
    let timer = 0;
    let sdk: AvaturnSDK | null = null;
    try {
      const url = getAvaturnUrl();
      sdk = new AvaturnSDK();
      sdkRef.current = sdk;
      timer = window.setTimeout(() => {
        if (active) {
          setCreatorPhase("timeout");
          setCreatorError("Avaturn did not finish loading. Check the connection or retry.");
        }
      }, 90_000);
      sdk.on("error", (issue) => {
        if (!active) return;
        setCreatorPhase("error");
        setCreatorError(issue.message || "Avaturn could not continue. Retry or close the creator.");
      });
      sdk.on("export", (result) => {
        if (!active || callbackHandled || !result.avatarId || !result.url) return;
        callbackHandled = true;
        const source: ExportSource = {
          avatarId: result.avatarId,
          url: result.url,
          urlType: result.urlType,
        };
        exportSourceRef.current = source;
        setCreatorOpen(false);
        setNotice("Avaturn exported a model. Review the imported GLB and save it to DressMe when ready.");
        void importExport(source);
      });
      sdk.init(creatorContainerRef.current, { url, iframeClassName: "avaturn-sdk-iframe" })
        .then(() => {
          if (!active) return;
          window.clearTimeout(timer);
          setCreatorPhase("ready");
          setCreatorError("");
          const frame = creatorContainerRef.current?.querySelector("iframe");
          if (frame) frame.title = "Avaturn 3D avatar creator";
        })
        .catch((cause: unknown) => {
          if (!active) return;
          window.clearTimeout(timer);
          setCreatorPhase("error");
          setCreatorError(cause instanceof Error ? cause.message : "Avaturn could not be loaded.");
        });
    } catch (cause) {
      setCreatorPhase("error");
      setCreatorError(cause instanceof Error ? cause.message : "Avaturn is not configured.");
    }
    return () => {
      active = false;
      window.clearTimeout(timer);
      if (sdkRef.current === sdk) sdkRef.current = null;
      sdk?.destroy();
    };
  }, [creatorOpen, creatorAttempt, importExport]);

  useEffect(() => {
    if (!modelUrl) {
      setViewerRegistered(false);
      return;
    }
    let active = true;
    setViewerRegistered(false);
    import("@google/model-viewer")
      .then(() => { if (active) setViewerRegistered(true); })
      .catch(() => { if (active) setViewerError("The 3D viewer could not be loaded in this browser."); });
    return () => { active = false; };
  }, [modelUrl]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !modelUrl || !viewerRegistered) return;
    const onLoad = () => { setViewerReady(true); setViewerError(""); };
    const onError = () => { setViewerReady(false); setViewerError("This GLB could not be rendered. Try reloading it or create a replacement."); };
    const onContextLost = () => { setViewerReady(false); setViewerError("3D rendering is unavailable in this browser session. Reload the page or try another browser."); };
    viewer.addEventListener("load", onLoad);
    viewer.addEventListener("error", onError);
    viewer.addEventListener("webglcontextlost", onContextLost);
    return () => {
      viewer.removeEventListener("load", onLoad);
      viewer.removeEventListener("error", onError);
      viewer.removeEventListener("webglcontextlost", onContextLost);
    };
  }, [modelUrl, viewerRegistered]);

  async function beginAvatarCreation() {
    if (!acceptedConsent || creatorBusy) return;
    setCreatorBusy(true);
    setPageError("");
    setExportError("");
    setExportFile(null);
    setExportPhase("idle");
    try {
      const savedConsent = await api<AvatarConsent>("/avatars/consents", {
        method: "POST",
        body: JSON.stringify({ accepted: true }),
      });
      if (savedConsent.consent_version !== AVATAR_CONSENT_VERSION) {
        throw new Error("DressMe's consent disclosure changed. Reload the page before opening Avaturn.");
      }
      setConsent(savedConsent);
      setCreatorPhase("loading");
      setCreatorError("");
      setCreatorOpen(true);
      setCreatorAttempt((attempt) => attempt + 1);
      setShowConsent(false);
    } catch (cause) {
      setPageError(cause instanceof Error ? cause.message : "Your consent could not be saved.");
    } finally {
      setCreatorBusy(false);
    }
  }

  function retryExportImport() {
    if (exportSourceRef.current) void importExport(exportSourceRef.current);
  }

  async function saveExportedAvatar() {
    if (!exportFile || !consent || !exportAvatarId || saving) return;
    setSaving(true);
    setPageError("");
    try {
      const form = new FormData();
      form.append("model", exportFile);
      form.append("provider_avatar_id", exportAvatarId);
      form.append("consent_id", consent.id);
      form.append("consent_version", consent.consent_version);
      const saved = await api<Avatar>("/avatars/current", { method: "PUT", body: form });
      setAvatar(saved);
      setExportFile(null);
      setExportAvatarId("");
      setExportPhase("idle");
      setConsent(null);
      setNotice(saved.version > 1 ? "Your replacement avatar is saved privately." : "Your 3D avatar is saved privately.");
    } catch (cause) {
      setPageError(cause instanceof Error ? cause.message : "The avatar could not be saved. Your current avatar is still available.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteAvatar() {
    if (!avatar || deleting) return;
    setDeleting(true);
    setPageError("");
    try {
      await api<void>("/avatars/current", { method: "DELETE" });
      setAvatar(null);
      setDeleteDialogOpen(false);
      setNotice("Your DressMe avatar and private GLB were deleted. Delete your Avaturn account separately if you also want provider-side data removed.");
    } catch (cause) {
      setPageError(cause instanceof Error ? cause.message : "The avatar could not be deleted.");
    } finally {
      setDeleting(false);
    }
  }

  function closeCreator() {
    setCreatorOpen(false);
    setCreatorError("");
    setConsent(null);
  }

  function resetViewer() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.cameraOrbit = "0deg 75deg auto";
    viewer.cameraTarget = "auto auto auto";
    viewer.resetTurntableRotation(0);
  }

  return <section className="page-section avatar-page" aria-labelledby="avatar-heading">
    <div className="section-heading">
      <p className="eyebrow">A private, reusable 3D profile</p>
      <h1 id="avatar-heading">My Avatar</h1>
      <p className="muted">Create a 3D visual profile. It is not a body measurement or a validated garment-fit estimate.</p>
    </div>

    {notice && <p className="notice" role="status">{notice}<button aria-label="Dismiss avatar message" onClick={() => setNotice("")}>×</button></p>}
    {pageError && <p className="alert" role="alert">{pageError}</p>}

    {avatarLoading ? <p role="status">Loading your private avatar…</p> : avatar ? <article className="avatar-card" aria-label="Saved avatar">
      <div className="avatar-card-heading">
        <div><p className="eyebrow">Saved in your private DressMe storage</p><h2>Your 3D avatar</h2><p className="muted">Version {avatar.version} · {sizeLabel(avatar.asset_size)} GLB</p></div>
        <div className="avatar-actions">
          <button className="button primary" onClick={() => { setShowConsent(true); setAcceptedConsent(false); setPageError(""); }}>Create replacement</button>
          <button className="button danger" onClick={() => setDeleteDialogOpen(true)}>Delete avatar</button>
        </div>
      </div>
      {modelLoading && <p role="status">Loading your private 3D model…</p>}
      {modelError && <p className="alert" role="alert">{modelError} <button className="button subtle" onClick={() => setAvatar({ ...avatar })}>Retry loading</button></p>}
      {modelUrl && <div className="avatar-viewer-wrap">
        {viewerError && <p className="alert" role="alert">{viewerError}</p>}
        {!viewerRegistered && <p role="status">Loading the 3D viewer…</p>}
        {viewerRegistered && <>
        {createElement("model-viewer", {
          ref: (node: ModelViewerElement | null) => { viewerRef.current = node; },
          src: modelUrl,
          alt: "Your saved personalized 3D avatar. Drag to rotate and use touch or wheel to zoom.",
          "camera-controls": "",
          "touch-action": "pan-y",
          "camera-orbit": "0deg 75deg auto",
          "camera-target": "auto auto auto",
          "shadow-intensity": "1",
          "exposure": "1",
          "interaction-prompt": "auto",
        })}
        {!viewerError && !viewerReady && <p className="hint" role="status">Preparing interactive 3D view…</p>}
        <div className="avatar-viewer-actions">
          <button className="button subtle" onClick={resetViewer} disabled={!viewerReady}>Reset view</button>
          <p className="hint">Drag to rotate; scroll or pinch to zoom. Use Reset view to return to full-body framing.</p>
        </div>
        </>}
      </div>}
    </article> : <div className="empty-state avatar-empty">
      <div aria-hidden="true" className="empty-icon">◌</div>
      <h2>No saved avatar yet</h2>
      <p>Create an avatar in Avaturn, customize it there, then explicitly save the exported GLB to your private DressMe account.</p>
      {!showConsent && <button className="button primary" onClick={() => { setShowConsent(true); setAcceptedConsent(false); setPageError(""); }}>Create avatar</button>}
    </div>}

    {showConsent && !creatorOpen && <section className="avatar-consent-card" aria-labelledby="avatar-consent-heading">
      <p className="eyebrow">Before opening the third-party creator</p>
      <h2 id="avatar-consent-heading">{avatar ? "Create a replacement" : "Photo processing and storage"}</h2>
      <ul>
        <li>Avaturn receives and processes the photos you choose inside its embedded creator under its own <a href="https://docs.google.com/document/d/e/2PACX-1vT5_TR6-MNs29LqI-LLKHvIKHVE0iluuapOpHODGRVDaqyfuCsEgaiE3ZIliI1-FN_-9rxJZ3iVo_jJ/pub" target="_blank" rel="noreferrer">terms</a> and <a href="https://docs.google.com/document/d/e/2PACX-1vT-lYthxjPO4SbgkB2kJN8dTFWvRVdF3srOs37oRBgL7IYXK0PAD62u-tF8JXo8ULV6_KVfRW_kuIMo/pub" target="_blank" rel="noreferrer">privacy policy</a>.</li>
        <li>DressMe does not send your stored wardrobe or person photos to Avaturn. Only photos you select in its creator are sent.</li>
        <li>After export, DressMe stores the GLB privately in this account. A replacement keeps the current avatar until the new file validates and saves successfully.</li>
        <li>This visual avatar is not a body measurement and does not validate physical garment fit. Deleting it here does not delete provider-side Avaturn data.</li>
      </ul>
      <label className="avatar-consent-check">
        <input type="checkbox" checked={acceptedConsent} onChange={(event) => setAcceptedConsent(event.target.checked)} />
        <span>I have read this notice and consent to Avaturn processing the photos I choose in its creator.</span>
      </label>
      <div className="avatar-actions">
        <button className="button subtle" onClick={() => setShowConsent(false)}>Cancel</button>
        <button className="button primary" onClick={() => void beginAvatarCreation()} disabled={!acceptedConsent || creatorBusy}>
          {creatorBusy ? "Saving consent…" : "Continue to Avaturn"}
        </button>
      </div>
    </section>}

    {creatorOpen && <section className="avatar-creator-card" aria-label="Avaturn creator">
      <div className="avatar-card-heading">
        <div><p className="eyebrow">Third-party avatar creator</p><h2>Customize your avatar</h2><p className="muted">Choose and upload photos directly inside Avaturn. DressMe does not reuse saved photos.</p></div>
        <button className="button subtle" onClick={closeCreator}>Close creator</button>
      </div>
      <div className="avaturn-frame" ref={creatorContainerRef} aria-busy={creatorPhase === "loading"} />
      {creatorPhase === "loading" && <p role="status">Connecting to Avaturn…</p>}
      {creatorError && <p className="alert" role="alert">{creatorError}</p>}
      {(creatorPhase === "timeout" || creatorPhase === "error") && <div className="avatar-actions">
        <button className="button subtle" onClick={closeCreator}>Close</button>
        <button className="button primary" onClick={() => { setCreatorPhase("loading"); setCreatorError(""); setCreatorAttempt((attempt) => attempt + 1); }}>Retry Avaturn</button>
      </div>}
    </section>}

    {exportPhase === "downloading" && <p className="notice" role="status">Importing the exported GLB into DressMe's private save flow…</p>}
    {exportPhase === "error" && <section className="avatar-export-card" aria-labelledby="avatar-export-heading">
      <h2 id="avatar-export-heading">Export not imported</h2>
      <p className="alert" role="alert">{exportError}</p>
      <div className="avatar-actions">
        {exportSourceRef.current && <button className="button primary" onClick={retryExportImport}>Retry import</button>}
        <button className="button subtle" onClick={() => { exportSourceRef.current = null; setExportPhase("idle"); setExportError(""); setConsent(null); }}>Dismiss</button>
      </div>
    </section>}
    {exportPhase === "ready" && exportFile && <section className="avatar-export-card" aria-labelledby="avatar-export-heading">
      <p className="eyebrow">Exported from Avaturn · not saved yet</p>
      <h2 id="avatar-export-heading">Review your 3D model</h2>
      <p>{exportFile.name} · {sizeLabel(exportFile.size)}. The server will validate the GLB structure before private storage.</p>
      <div className="avatar-actions">
        <button className="button subtle" onClick={() => { exportSourceRef.current = null; setExportFile(null); setExportAvatarId(""); setExportPhase("idle"); setConsent(null); }}>Discard export</button>
        <button className="button primary" onClick={() => void saveExportedAvatar()} disabled={saving || exportFile.size > MAX_AVATAR_BYTES}>
          {saving ? "Validating and saving…" : avatar ? "Save replacement privately" : "Save avatar privately"}
        </button>
      </div>
    </section>}

    <dialog className="confirmation-dialog avatar-delete-dialog" ref={deleteDialogRef} onClose={() => setDeleteDialogOpen(false)}>
      <form method="dialog" onSubmit={(event) => event.preventDefault()}>
        <h2>Delete your DressMe avatar?</h2>
        <p>This removes the saved GLB from DressMe private storage. It does not delete data held by Avaturn.</p>
        <div className="dialog-actions">
          <button type="button" className="button subtle" autoFocus onClick={() => setDeleteDialogOpen(false)}>Cancel</button>
          <button type="button" className="button danger" disabled={deleting} onClick={() => void deleteAvatar()}>{deleting ? "Deleting…" : "Delete avatar"}</button>
        </div>
      </form>
    </dialog>
  </section>;
}
