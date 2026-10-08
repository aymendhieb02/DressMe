import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  api, ApiError, categories, colors, getCsrfToken, patterns, setCsrfToken, sleeves,
  type AuthResponse, type Garment, type GarmentPage, type PendingUpload, type PersonPhoto,
  type TryOnJob, type TryOnJobList, type User,
} from "./api";

type Screen = "wardrobe" | "add" | "try-on";
type Category = (typeof categories)[number];
type Color = (typeof colors)[number];
type Pattern = (typeof patterns)[number];
type Sleeve = (typeof sleeves)[number];
type EditValues = { category: Category; garment_photo_type: "flat-lay" | "model"; color: Color | null; pattern: Pattern | null; sleeve_length: Sleeve | null; description: string; name: string | null; notes: string | null };
type ReviewValues = { category: Category | ""; color: Color | ""; pattern: Pattern | ""; sleeve_length: Sleeve | "" };
type GarmentPhotoType = "flat-lay" | "model";
type ConfirmationRequest = {
  title: string;
  message: string;
  confirmLabel: string;
  requirePassword?: boolean;
  onConfirm: (password?: string) => Promise<void>;
};

const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function screenFromHash(hash: string): Screen {
  const route = hash.replace(/^#\/?/, "");
  return route === "add" || route === "try-on" ? route : "wardrobe";
}

function imageFileError(file: File) {
  const extension = file.name.toLowerCase().split(".").pop();
  const knownExtension = extension === "jpg" || extension === "jpeg" || extension === "png" || extension === "webp";
  if (file.type ? !IMAGE_TYPES.has(file.type) : !knownExtension) return "Choose a JPEG, PNG, or WEBP image.";
  if (file.size > MAX_IMAGE_BYTES) return "This image is larger than 10 MB. Choose a smaller file.";
  return "";
}

function fileSizeLabel(size: number) {
  return size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function SelectField<T extends string>({ label, value, options, onChange, allowBlank = false }: {
  label: string; value: T | ""; options: readonly T[]; onChange: (value: T | "") => void; allowBlank?: boolean;
}) {
  return <label className="field">
    <span>{label}</span>
    <select value={value} onChange={(event) => onChange(event.target.value as T | "")}>
      {allowBlank && <option value="">Not confirmed</option>}
      {options.map((option) => <option key={option} value={option}>{option.replaceAll("-", " ")}</option>)}
    </select>
  </label>;
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [screen, setScreen] = useState<Screen>(() => screenFromHash(window.location.hash));
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null);
  const [confirmationPassword, setConfirmationPassword] = useState("");
  const [confirmationBusy, setConfirmationBusy] = useState(false);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const confirmationDialogRef = useRef<HTMLDialogElement>(null);
  const confirmationReturnFocusRef = useRef<HTMLElement | null>(null);
  const garmentFileInputRef = useRef<HTMLInputElement>(null);
  const personFileInputRef = useRef<HTMLInputElement>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [garments, setGarments] = useState<Garment[]>([]);
  const [personPhotos, setPersonPhotos] = useState<PersonPhoto[]>([]);
  const [tryOnJobs, setTryOnJobs] = useState<TryOnJob[]>([]);
  const [personFile, setPersonFile] = useState<File | null>(null);
  const [personFileError, setPersonFileError] = useState("");
  const [personPreview, setPersonPreview] = useState("");
  const [photoConsent, setPhotoConsent] = useState(false);
  const [selectedPersonPhoto, setSelectedPersonPhoto] = useState("");
  const [selectedGarment, setSelectedGarment] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [localPreview, setLocalPreview] = useState("");
  const [pending, setPending] = useState<PendingUpload | null>(null);
  const [review, setReview] = useState<ReviewValues>({ category: "", color: "", pattern: "", sleeve_length: "" });
  const [garmentPhotoType, setGarmentPhotoType] = useState<GarmentPhotoType | "">("");
  const [description, setDescription] = useState("");
  const [generatedDescription, setGeneratedDescription] = useState("");
  const [editId, setEditId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<EditValues | null>(null);
  const [editOriginal, setEditOriginal] = useState<EditValues | null>(null);

  useEffect(() => {
    const handlePopState = () => {
      setScreen(screenFromHash(window.location.hash));
      if (mobileMenuOpen) mobileMenuButtonRef.current?.focus();
      setMobileMenuOpen(false);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [mobileMenuOpen]);

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileMenuOpen(false);
        mobileMenuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [mobileMenuOpen]);

  useEffect(() => {
    const dialog = confirmationDialogRef.current;
    if (!dialog) return;
    if (confirmation && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!confirmation && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      confirmationReturnFocusRef.current?.focus();
      confirmationReturnFocusRef.current = null;
    }
  }, [confirmation]);

  function navigateTo(next: Screen) {
    if (next !== screen) window.history.pushState(null, "", `#${next}`);
    if (mobileMenuOpen) mobileMenuButtonRef.current?.focus();
    setScreen(next);
    setMobileMenuOpen(false);
  }

  function askForConfirmation(request: ConfirmationRequest) {
    confirmationReturnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConfirmationPassword("");
    setConfirmation(request);
  }

  async function confirmRequestedAction(event: FormEvent) {
    event.preventDefault();
    if (!confirmation || confirmationBusy) return;
    setConfirmationBusy(true);
    try {
      await confirmation.onConfirm(confirmation.requirePassword ? confirmationPassword : undefined);
      setConfirmation(null);
      setConfirmationPassword("");
    } finally {
      setConfirmationBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const me = await api<User>("/auth/me");
        if (active) setUser(me);
      } catch (firstError) {
        if (firstError instanceof ApiError && firstError.status === 401 && getCsrfToken()) {
          try {
            const refreshed = await api<AuthResponse>("/auth/refresh", { method: "POST" });
            setCsrfToken(refreshed.csrf_token);
            if (active) setUser(refreshed.user);
          } catch {
            setCsrfToken(null);
          }
        }
      } finally {
        if (active) setAuthLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  async function loadWardrobe(category = filterCategory) {
    const query = new URLSearchParams({ page: "1", page_size: "48" });
    if (category) query.set("category", category);
    const page = await api<GarmentPage>(`/garments?${query.toString()}`);
    setGarments(page.items);
    setSelectedGarment((current) => page.items.some((item) => item.id === current) ? current : page.items[0]?.id ?? "");
  }

  async function loadTryOnData() {
    const [photos, jobs] = await Promise.all([
      api<PersonPhoto[]>("/person-photos"),
      api<TryOnJobList>("/try-on/jobs?page_size=50"),
    ]);
    setPersonPhotos(photos);
    setSelectedPersonPhoto((current) => photos.some((photo) => photo.id === current) ? current : photos[0]?.id ?? "");
    setTryOnJobs(jobs.items);
  }

  useEffect(() => {
    if (!user) return;
    loadWardrobe().catch((cause) => setError(errorMessage(cause)));
  }, [user, filterCategory]);

  useEffect(() => {
    if (!user) return;
    loadTryOnData().catch((cause) => setError(errorMessage(cause)));
  }, [user]);

  useEffect(() => {
    if (!personFile) { setPersonPreview(""); return; }
    const url = URL.createObjectURL(personFile);
    setPersonPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [personFile]);

  useEffect(() => {
    if (!tryOnJobs.some((job) => job.state === "queued" || job.state === "running")) return;
    const timer = window.setInterval(() => {
      loadTryOnData().catch((cause) => setError(errorMessage(cause)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [tryOnJobs, personPhotos]);

  useEffect(() => {
    if (!file) { setLocalPreview(""); return; }
    const url = URL.createObjectURL(file);
    setLocalPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!pending || !review.category) { setGeneratedDescription(""); return; }
    const timer = window.setTimeout(async () => {
      try {
        const confirmed = Object.fromEntries(Object.entries(review).filter(([, value]) => value));
        const result = await api<{ text: string }>("/garments/describe", {
          method: "POST", body: JSON.stringify({ pending_upload_id: pending.id, confirmed }),
        });
        setGeneratedDescription(result.text);
        setDescription((current) => current === generatedDescription || current === "" ? result.text : current);
      } catch (cause) {
        setError(errorMessage(cause));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [pending, review]);

  async function submitAuth(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api<AuthResponse>(`/auth/${authMode}`, {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      setCsrfToken(result.csrf_token); setUser(result.user); setPassword(""); setMobileMenuOpen(false); setNotice("Welcome to your wardrobe.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function logout() {
    setBusy(true); setError("");
    try {
      if (!(await discardPendingUpload())) return;
      await api<void>("/auth/logout", { method: "POST" });
      setCsrfToken(null); setUser(null); setGarments([]); setPersonPhotos([]); setTryOnJobs([]); setSelectedPersonPhoto(""); setMobileMenuOpen(false); setNotice("");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function deleteAccount(passwordToConfirm: string) {
    setBusy(true); setError("");
    try {
      const deletion = await api<{ status?: string }>("/auth/account", {
        method: "DELETE",
        body: JSON.stringify({ password: passwordToConfirm, confirmation: "DELETE" }),
      });
      if (deletion?.status === "deletion_queued") setError("Your account was deleted. Private file removal is queued for retry.");
      setCsrfToken(null); setUser(null); setGarments([]); setPersonPhotos([]); setTryOnJobs([]); setMobileMenuOpen(false);
      setSelectedPersonPhoto(""); setSelectedGarment(""); setNotice("");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function discardPendingUpload() {
    if (!pending) return true;
    try {
      const deletion = await api<{ status?: string }>(`/garments/uploads/${pending.id}`, { method: "DELETE" });
      if (deletion?.status === "deletion_queued") setNotice("Pending upload access was removed. Private file cleanup is queued for retry.");
      setPending(null); setFile(null); setFileError("");
      if (garmentFileInputRef.current) garmentFileInputRef.current.value = "";
      return true;
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        setPending(null); setFile(null); setFileError("");
        if (garmentFileInputRef.current) garmentFileInputRef.current.value = "";
        return true;
      }
      setError(errorMessage(cause));
      return false;
    }
  }

  async function submitUpload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const form = new FormData(); form.append("image", file);
      const result = await api<PendingUpload>("/garments/analyze", { method: "POST", body: form });
      setPending(result); setReview({ category: "", color: "", pattern: "", sleeve_length: "" });
      setGarmentPhotoType("");
      setDescription(""); setGeneratedDescription("");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function saveGarment(event: FormEvent) {
    event.preventDefault();
    if (!pending || !review.category || !garmentPhotoType) return;
    setBusy(true); setError("");
    try {
      const body: Record<string, unknown> = { pending_upload_id: pending.id, garment_photo_type: garmentPhotoType, ...review };
      for (const key of ["color", "pattern", "sleeve_length"]) if (!body[key]) delete body[key];
      if (description.trim() && description.trim() !== generatedDescription) body.description = description.trim();
      await api<Garment>("/garments", { method: "POST", body: JSON.stringify(body) });
      setPending(null); setFile(null); setFileError(""); setDescription(""); navigateTo("wardrobe"); setNotice("Garment saved to your wardrobe.");
      await loadWardrobe();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  function beginEdit(garment: Garment) {
    setEditId(garment.id);
    const values: EditValues = { category: garment.category as Category, garment_photo_type: garment.garment_photo_type, color: garment.color as Color | null,
      pattern: garment.pattern as Pattern | null, sleeve_length: garment.sleeve_length as Sleeve | null,
      description: garment.description, name: garment.name, notes: garment.notes };
    setEditOriginal(values);
    setEditValues(values);
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editId || !editValues || !editOriginal) return;
    setBusy(true); setError("");
    try {
      const changes = Object.fromEntries(Object.entries(editValues).filter(([key, value]) => value !== editOriginal[key as keyof EditValues]));
      if (Object.keys(changes).length) {
        await api<Garment>(`/garments/${editId}`, { method: "PATCH", body: JSON.stringify(changes) });
        setNotice("Garment updated."); await loadWardrobe();
      }
      setEditId(null); setEditValues(null); setEditOriginal(null);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function deleteGarment(id: string) {
    setBusy(true); setError("");
    try {
      const deletion = await api<{ status?: string }>(`/garments/${id}`, { method: "DELETE" });
      setNotice(deletion?.status === "deletion_queued" ? "Garment access was removed. Private file cleanup is queued for retry." : "Garment deleted."); await loadWardrobe();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function uploadPersonPhoto(event: FormEvent) {
    event.preventDefault();
    if (!personFile || !photoConsent) return;
    setBusy(true); setError("");
    try {
      const form = new FormData(); form.append("image", personFile); form.append("consent", "true");
      const photo = await api<PersonPhoto>("/person-photos", { method: "POST", body: form });
      setPersonFile(null); setPersonFileError(""); setPhotoConsent(false); setSelectedPersonPhoto(photo.id);
      if (personFileInputRef.current) personFileInputRef.current.value = "";
      setNotice("Private person photo saved with consent version " + photo.consent_version + ".");
      await loadTryOnData();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function submitMockTryOn(event: FormEvent) {
    event.preventDefault();
    if (!selectedPersonPhoto || !selectedGarment) return;
    const garment = garments.find((item) => item.id === selectedGarment);
    if (!garment?.vton_eligibility.candidate_category) return;
    setBusy(true); setError("");
    try {
      await api<TryOnJob>("/try-on/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ garment_id: selectedGarment, person_photo_id: selectedPersonPhoto }),
      });
      setNotice("Mock preview queued. No try-on model will run.");
      await loadTryOnData();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function cancelTryOn(id: string) {
    setBusy(true); setError("");
    try { await api<TryOnJob>(`/try-on/jobs/${id}/cancel`, { method: "POST" }); setNotice("Mock preview cancelled."); await loadTryOnData(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function deleteTryOn(id: string) {
    setBusy(true); setError("");
    try {
      const deletion = await api<{ status?: string }>(`/try-on/jobs/${id}`, { method: "DELETE" });
      setNotice(deletion?.status === "deletion_queued" ? "Job access was removed. Private result cleanup is queued for retry." : "Job and result deleted.");
      await loadTryOnData();
    }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function deletePersonPhoto(id: string) {
    setBusy(true); setError("");
    try {
      const deletion = await api<{ status?: string }>(`/person-photos/${id}`, { method: "DELETE" });
      setNotice(deletion?.status === "deletion_queued" ? "Photo access and dependent jobs were removed. Private file cleanup is queued for retry." : "Person photo and dependent jobs deleted.");
      await loadTryOnData();
    }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  const candidateCategories = useMemo(() => pending?.prediction.suggestions.map((entry) => entry.category) ?? [], [pending]);

  if (authLoading) return <main className="center-page"><p role="status">Restoring your session…</p></main>;
  if (!user) return <main className="auth-page">
    <section className="auth-card">
      <div className="brand-mark" aria-hidden="true">D</div>
      <p className="eyebrow">A considered wardrobe</p>
      <h1>{authMode === "login" ? "Welcome back" : "Create your account"}</h1>
      <p className="muted">Keep your garments in one private, searchable place.</p>
      <form onSubmit={submitAuth} className="stack-form">
        <label className="field"><span>Email</span><input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="field"><span>Password</span><input type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} minLength={12} required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <p className="hint">Use at least 12 characters.</p>
        {error && <p className="alert" role="alert">{error}</p>}
        <button className="button primary full" disabled={busy}>{busy ? "Please wait…" : authMode === "login" ? "Sign in" : "Create account"}</button>
      </form>
      <button className="text-button" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setError(""); }}>
        {authMode === "login" ? "New to DressMe? Create an account" : "Already have an account? Sign in"}
      </button>
    </section>
  </main>;

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#wardrobe" onClick={(e) => { e.preventDefault(); navigateTo("wardrobe"); }}><span className="brand-mark small" aria-hidden="true">D</span><span>dressme</span></a>
      <button ref={mobileMenuButtonRef} type="button" className="mobile-menu-toggle" aria-expanded={mobileMenuOpen} aria-controls="primary-menu" onClick={() => setMobileMenuOpen((open) => !open)}>
        <span className="menu-toggle-icon" aria-hidden="true">{mobileMenuOpen ? "×" : "☰"}</span>{mobileMenuOpen ? "Close menu" : "Menu"}
      </button>
      <div id="primary-menu" className="header-menu" data-open={mobileMenuOpen}>
      <nav aria-label="Main navigation" className="nav-actions">
        <button aria-current={screen === "wardrobe" ? "page" : undefined} className={`nav-link ${screen === "wardrobe" ? "selected" : ""}`} onClick={() => navigateTo("wardrobe")}>Wardrobe</button>
        <button aria-current={screen === "add" ? "page" : undefined} className={`nav-link ${screen === "add" ? "selected" : ""}`} onClick={() => navigateTo("add")}>Add a garment</button>
        <button aria-current={screen === "try-on" ? "page" : undefined} className={`nav-link ${screen === "try-on" ? "selected" : ""}`} onClick={() => navigateTo("try-on")}>Try-on preview</button>
      </nav>
      <div className="account-actions"><span className="user-email">{user.email}</span><button className="button subtle" onClick={logout} disabled={busy}>Sign out</button><button className="button danger" onClick={() => askForConfirmation({ title: "Delete your account?", message: "This permanently deletes your DressMe account, wardrobe, private photos, jobs, and results.", confirmLabel: "Delete account", requirePassword: true, onConfirm: (confirmedPassword) => deleteAccount(confirmedPassword ?? "") })} disabled={busy}>Delete account</button></div>
      </div>
    </header>

    <main className="content">
      {notice && <p className="notice" role="status">{notice}<button aria-label="Dismiss message" onClick={() => setNotice("")}>×</button></p>}
      {error && <p className="alert page-alert" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError("")}>×</button></p>}

      {screen === "add" && <section className="page-section">
        <div className="section-heading"><div><p className="eyebrow">Your wardrobe, one piece at a time</p><h1>Add a garment</h1><p className="muted">Add one clear garment photo. AI suggestions are for your review.</p></div></div>
        {!pending ? <form className="upload-panel" onSubmit={submitUpload} aria-busy={busy}>
          <label className="dropzone">
            <input ref={garmentFileInputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-label="Choose a garment photo" aria-describedby="garment-file-help" onChange={(e) => {
              const chosen = e.currentTarget.files?.[0] ?? null;
              const validation = chosen ? imageFileError(chosen) : "";
              setFileError(validation);
              setFile(validation ? null : chosen);
              if (validation) e.currentTarget.value = "";
            }} />
            {localPreview ? <img className="upload-preview" src={localPreview} alt="Selected garment preview" /> : <span className="upload-placeholder"><span className="upload-icon" aria-hidden="true">＋</span><strong>Choose a garment photo</strong><span>JPEG, PNG, or WEBP · up to 10 MB</span></span>}
          </label>
          <p id="garment-file-help" className="upload-file-details" aria-live="polite">{file ? `${file.name} · ${file.type.replace("image/", "").toUpperCase()} · ${fileSizeLabel(file.size)}` : "Select a JPEG, PNG, or WEBP image up to 10 MB."}</p>
          {fileError && <p className="alert upload-error" role="alert">{fileError}</p>}
          <button className="button primary" disabled={!file || busy} aria-busy={busy}>{busy ? "Analyzing image…" : "Get suggestions"}</button>
        </form> : <div className="review-layout">
          <aside className="review-image-card"><img src={pending.image_url} alt="Private uploaded garment" /><p>{pending.width} × {pending.height} pixels</p></aside>
          <form className="review-card" onSubmit={saveGarment} aria-busy={busy}>
            <p className="eyebrow">AI suggestion · please review</p>
            <h2>Check the details</h2>
            <div className="suggestion-box">
              <span className="suggestion-label">Category suggestions</span>
              <p>{candidateCategories.length ? candidateCategories.join(" · ") : "No category suggestion"}</p>
              <small>Scores are not probabilities. Choose the category that best fits.</small>
            </div>
            {pending.quality.warnings?.length ? <div className="quality-note"><strong>Photo tips</strong><ul>{pending.quality.warnings.map((warning, index) => <li key={index}>{typeof warning === "string" ? warning : warning.message}</li>)}</ul><span>You can still continue.</span></div> : null}
            <div className="field-grid">
              <SelectField label="Category *" value={review.category} options={categories} onChange={(v) => setReview((old) => ({ ...old, category: v }))} allowBlank />
              <SelectField label="Garment photo type *" value={garmentPhotoType} options={["flat-lay", "model"] as const} onChange={(v) => setGarmentPhotoType(v as GarmentPhotoType | "")} allowBlank />
              <SelectField label="Color (confirm if correct)" value={review.color} options={colors} onChange={(v) => setReview((old) => ({ ...old, color: v }))} allowBlank />
              <SelectField label="Pattern" value={review.pattern} options={patterns} onChange={(v) => setReview((old) => ({ ...old, pattern: v }))} allowBlank />
              <SelectField label="Sleeve length" value={review.sleeve_length} options={sleeves} onChange={(v) => setReview((old) => ({ ...old, sleeve_length: v }))} allowBlank />
            </div>
            <label className="field"><span>Description preview</span><textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Choose a category to preview the description" /></label>
            <small className="hint">The description uses only fields you confirm. Editing it will save your own wording.</small>
            <div className="review-actions"><button type="button" className="button subtle" onClick={() => void discardPendingUpload()}>Choose another photo</button><button className="button primary" disabled={!review.category || !garmentPhotoType || busy}>{busy ? "Saving…" : "Save to wardrobe"}</button></div>
          </form>
        </div>}
      </section>}

      {screen === "try-on" && <section className="page-section">
        <div className="section-heading"><div><p className="eyebrow">A private workflow preview</p><h1>Try-on preview</h1><p className="muted">This is a mock workflow. It does not generate an outfit, change the person photo, or predict fit.</p></div></div>
        <div className="quality-note mock-notice" role="note"><strong>MOCK MODE · NO AI TRY-ON</strong><p>Submitted jobs return a labelled contact sheet only. Real FASHN inference is disabled.</p><p>Academic prototype. Component and dataset terms vary; this notice does not grant commercial-use clearance.</p></div>
        <div className="review-layout">
          <form className="review-card" onSubmit={uploadPersonPhoto} aria-busy={busy}>
            <h2>Add a person photo</h2>
            <p className="muted">The photo stays private and is only used for a try-on you request.</p>
          <label className="field"><span>Choose a JPEG, PNG, or WEBP photo</span><input ref={personFileInputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-describedby="person-file-help" onChange={(e) => {
            const chosen = e.currentTarget.files?.[0] ?? null;
            const validation = chosen ? imageFileError(chosen) : "";
            setPersonFileError(validation);
            setPersonFile(validation ? null : chosen);
            if (validation) e.currentTarget.value = "";
          }} /></label>
          <p id="person-file-help" className="upload-file-details" aria-live="polite">{personFile ? `${personFile.name} · ${personFile.type.replace("image/", "").toUpperCase()} · ${fileSizeLabel(personFile.size)}` : "Choose an image up to 10 MB."}</p>
          {personFileError && <p className="alert upload-error" role="alert">{personFileError}</p>}
            {personPreview && <img className="person-photo-preview" src={personPreview} alt="Selected private person photo preview" />}
            <label className="consent-field"><input type="checkbox" checked={photoConsent} onChange={(e) => setPhotoConsent(e.target.checked)} /><span>I consent to DressMe storing this private photo and using it for try-on jobs I request. I can delete it and its dependent jobs/results.</span></label>
            <small className="hint">Consent is saved with a version and timestamp.</small>
            <button className="button primary" disabled={!personFile || !photoConsent || busy}>{busy ? "Saving photo…" : "Save person photo"}</button>
          </form>
          <div className="review-card">
            <h2>Private person photos</h2>
            {personPhotos.length === 0 ? <p className="muted">No person photos saved yet.</p> : <div className="person-photo-list">
              {personPhotos.map((photo) => <article className={`person-photo-card ${selectedPersonPhoto === photo.id ? "chosen" : ""}`} key={photo.id}>
                <label><input type="radio" name="person-photo" value={photo.id} checked={selectedPersonPhoto === photo.id} onChange={() => setSelectedPersonPhoto(photo.id)} /><img src={photo.image_url} alt="Private person photo" /><span>{photo.width} × {photo.height} · consent {photo.consent_version}</span></label>
                <button type="button" className="button danger" aria-label="Delete photo and dependent jobs" onClick={() => askForConfirmation({ title: "Delete this person photo?", message: "The photo and its dependent try-on jobs and private results will be removed.", confirmLabel: "Delete photo", onConfirm: () => deletePersonPhoto(photo.id) })} disabled={busy}>Delete photo &amp; jobs</button>
              </article>)}
            </div>}
          </div>
        </div>
        <form className="review-card tryon-submit" onSubmit={submitMockTryOn} aria-busy={busy}>
          <h2>Submit a mock preview</h2>
          <label className="field"><span>Reviewed wardrobe garment</span><select value={selectedGarment} onChange={(e) => setSelectedGarment(e.target.value)}><option value="">Choose a garment</option>{garments.map((garment) => <option key={garment.id} value={garment.id} disabled={!garment.vton_eligibility.candidate_category}>{garment.name || garment.category} · {garment.vton_eligibility.candidate_category ? `mock candidate ${garment.vton_eligibility.candidate_category}` : "unsupported"}</option>)}</select></label>
          {selectedGarment && (() => { const garment = garments.find((item) => item.id === selectedGarment); return garment && <p className="hint">Candidate mapping {garment.vton_eligibility.candidate_category ?? "unavailable"} · {garment.vton_eligibility.reason ?? "unknown"}. Candidate mappings are unvalidated and mock-only.</p>; })()}
          <button className="button primary" disabled={!selectedPersonPhoto || !selectedGarment || !garments.find((item) => item.id === selectedGarment)?.vton_eligibility.candidate_category || busy}>{busy ? "Submitting…" : "Queue mock preview"}</button>
        </form>
        <section className="job-history" aria-labelledby="job-history-heading">
          <div className="section-heading"><div><p className="eyebrow">Owner-only job history</p><h2 id="job-history-heading">Try-on jobs</h2></div></div>
          {tryOnJobs.length === 0 ? <div className="empty-state"><h3>No jobs yet</h3><p>Submit a mock preview to see the private job lifecycle.</p></div> : <div className="tryon-job-list">
            {tryOnJobs.map((job) => <article className="tryon-job-card" key={job.id}>
              <div className="tryon-job-heading"><div><strong>MOCK · NO TRY-ON GENERATED</strong><p role="status" aria-live="polite">Status: {job.state}{job.cancellation_requested ? " · cancellation requested" : ""}</p><small>Created {new Date(job.created_at).toLocaleString()}</small></div><div className="card-actions">
                {(job.state === "queued" || job.state === "running") && <button className="button subtle" onClick={() => cancelTryOn(job.id)} disabled={busy}>Cancel</button>}
                <button className="button danger" onClick={() => askForConfirmation({ title: "Delete this try-on job?", message: "The job and any private result will be removed.", confirmLabel: "Delete job", onConfirm: () => deleteTryOn(job.id) })} disabled={busy}>Delete job</button>
              </div></div>
              {job.error_code && <p className="alert">Job failed: {job.error_code}</p>}
              {job.result_url && <div className="mock-result"><p className="mock-result-label">MOCK OUTPUT · No VTON model ran and no try-on image was generated.</p><img src={job.result_url} alt="Mock workflow contact sheet showing the two source photos; no try-on result was generated" /><p>No fit estimate is provided in mock mode.</p></div>}
            </article>)}
          </div>}
        </section>
      </section>}

      {screen === "wardrobe" && <section className="page-section">
        <div className="section-heading wardrobe-heading"><div><p className="eyebrow">A little more room for what you love</p><h1>Your wardrobe</h1><p className="muted">{garments.length} {garments.length === 1 ? "garment" : "garments"} saved privately</p></div><button className="button primary" onClick={() => navigateTo("add")}>＋ Add a garment</button></div>
        <div className="filter-row"><label className="field compact"><span>Filter by category</span><select value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}><option value="">All categories</option>{categories.map((category) => <option key={category}>{category}</option>)}</select></label></div>
         {garments.length === 0 ? <div className="empty-state"><div aria-hidden="true" className="empty-icon">◌</div><h2>Your wardrobe starts here</h2><p>Add a garment photo to get a category suggestion and build your collection.</p><button className="button primary" onClick={() => navigateTo("add")}>Add your first garment</button></div> : <div className="garment-grid">
          {garments.map((garment) => <article className="garment-card" key={garment.id}>
            <img className="garment-image" src={garment.image_url} alt={garment.name || garment.category} loading="lazy" />
            {editId === garment.id && editValues ? <form className="card-edit" onSubmit={saveEdit}>
              <SelectField label="Category" value={editValues.category} options={categories} onChange={(v) => setEditValues({ ...editValues, category: v || garment.category as Category })} />
              <SelectField label="Garment photo type" value={editValues.garment_photo_type} options={["flat-lay", "model"] as const} onChange={(v) => setEditValues({ ...editValues, garment_photo_type: v as GarmentPhotoType || garment.garment_photo_type })} />
              <SelectField label="Color" value={editValues.color ?? ""} options={colors} onChange={(v) => setEditValues({ ...editValues, color: v as Color || null })} allowBlank />
              <SelectField label="Pattern" value={editValues.pattern ?? ""} options={patterns} onChange={(v) => setEditValues({ ...editValues, pattern: v as Pattern || null })} allowBlank />
              <SelectField label="Sleeve length" value={editValues.sleeve_length ?? ""} options={sleeves} onChange={(v) => setEditValues({ ...editValues, sleeve_length: v as Sleeve || null })} allowBlank />
              <label className="field"><span>Description</span><textarea rows={2} value={editValues.description} onChange={(e) => setEditValues({ ...editValues, description: e.target.value })} /></label>
              <label className="field"><span>Name</span><input value={editValues.name ?? ""} onChange={(e) => setEditValues({ ...editValues, name: e.target.value || null })} /></label>
              <label className="field"><span>Notes</span><textarea rows={2} value={editValues.notes ?? ""} onChange={(e) => setEditValues({ ...editValues, notes: e.target.value || null })} /></label>
              <div className="card-actions"><button className="button primary" disabled={busy}>Save changes</button><button type="button" className="button subtle" onClick={() => { setEditId(null); setEditValues(null); setEditOriginal(null); }}>Cancel</button></div>
            </form> : <div className="garment-details">
              <div className="garment-title"><div><h2>{garment.name || garment.category.replaceAll("-", " ")}</h2><p>{garment.description}</p></div><span className="category-chip">{garment.category}</span></div>
              <dl className="metadata-list"><div><dt>Photo type</dt><dd>{garment.garment_photo_type}</dd></div>{garment.color && <div><dt>Color</dt><dd>{garment.color}</dd></div>}{garment.pattern && <div><dt>Pattern</dt><dd>{garment.pattern}</dd></div>}{garment.sleeve_length && <div><dt>Sleeves</dt><dd>{garment.sleeve_length}</dd></div>}</dl>
              {!garment.vton_eligibility.eligible && <p className="hint">Try-on eligibility: {garment.vton_eligibility.reason === "mapping_not_visually_validated" ? `not enabled for ${garment.vton_eligibility.candidate_category ?? "this category"} until its mapping is validated` : "not supported"}.</p>}
              {garment.notes && <p className="garment-notes">{garment.notes}</p>}
              <div className="card-actions"><button className="button subtle" onClick={() => beginEdit(garment)}>Edit</button><button className="button danger" onClick={() => askForConfirmation({ title: "Delete this garment?", message: "This garment and its stored image will be removed from your wardrobe.", confirmLabel: "Delete garment", onConfirm: () => deleteGarment(garment.id) })} disabled={busy}>Delete</button></div>
            </div>}
          </article>)}
        </div>}
      </section>}
    </main>
      <footer><span>DressMe · Private by design</span><span>AI suggestions require your review</span></footer>
      <dialog ref={confirmationDialogRef} className="confirmation-dialog" aria-labelledby="confirmation-title" aria-describedby="confirmation-message" onCancel={(event) => { event.preventDefault(); setConfirmation(null); setConfirmationPassword(""); }}>
        {confirmation && <form onSubmit={confirmRequestedAction}>
          <h2 id="confirmation-title">{confirmation.title}</h2>
          <p id="confirmation-message">{confirmation.message}</p>
          {confirmation.requirePassword && <label className="field"><span>Password</span><input type="password" autoFocus autoComplete="current-password" required value={confirmationPassword} onChange={(event) => setConfirmationPassword(event.target.value)} /></label>}
          <div className="dialog-actions"><button type="button" className="button subtle" autoFocus={!confirmation.requirePassword} onClick={() => { setConfirmation(null); setConfirmationPassword(""); }}>Cancel</button><button type="submit" className="button danger" disabled={confirmationBusy || busy}>{confirmationBusy ? "Working…" : confirmation.confirmLabel}</button></div>
        </form>}
      </dialog>
  </div>;
}

export default App;
