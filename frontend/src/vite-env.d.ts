// vite/client comes from tsconfig "types"; this only types our env variables.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}
