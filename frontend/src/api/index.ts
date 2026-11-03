import { createHttpClient } from "@/api/http"
import type { ApiClient } from "@/api/client"

export { ApiError } from "@/api/client"
export type { ApiClient, StreamHandlers } from "@/api/client"

// Base URL from frontend/.env.local (see .env.example), without a trailing slash.
const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api"
).replace(/\/+$/, "")

/** The app's single API client. Components and stores import `api` from "@/api". */
export const api: ApiClient = createHttpClient(API_BASE_URL)
