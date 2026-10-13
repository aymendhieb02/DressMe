interface ImportMetaEnv {
  readonly VITE_AVATURN_URL?: string;
  readonly VITE_AVATURN_EXPORT_ORIGINS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
