import axios from "axios";

export interface HealthResponse {
  status: "ready" | "not_ready";
  dependencies: Record<string, string>;
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "",
  timeout: 5000,
});

export async function getHealth(): Promise<HealthResponse> {
  const response = await api.get<HealthResponse>("/health/ready");
  return response.data;
}
