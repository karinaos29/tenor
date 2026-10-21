/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The backend's origin when it is hosted separately (e.g. Railway); empty in development. */
  readonly VITE_BACKEND_URL?: string;
}
