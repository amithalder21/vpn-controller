export interface IpInfo {
  ip?: string | null;
  country?: string | null;
  country_iso?: string | null;
  org?: string | null;
  city?: string | null;
  region?: string | null;
  checked?: number;
}

export interface WorkerStats {
  cpu?: number;
  mem_mb?: number;
  rx_mb?: number;
  tx_mb?: number;
}

export interface LeakResult {
  pass: boolean;
  reason?: string;
  exit_ip?: string | null;
  host_ip?: string | null;
  country?: string | null;
  country_iso?: string | null;
  checked?: number;
}

export interface ProxyInfo {
  port: number;
  active: boolean;
  online: boolean;
  pool: boolean;
}

export interface Worker {
  name: string;
  exists: boolean;
  vpn?: string;
  app?: string;
  health?: string | null;
  started_at?: string | null;
  ipinfo?: IpInfo | null;
  stats?: WorkerStats | null;
  leak?: LeakResult | null;
  desired?: string;
  tags?: string[];
  restarts?: number;
  gaveup?: boolean;
  proxy?: ProxyInfo;
}

export interface ProxyExit {
  name: string;
  port: number;
  active: boolean;
  online: boolean;
  pool: boolean;
}
export interface ProxyState {
  enabled: boolean;
  exits: ProxyExit[];
}

export interface MetricPoint {
  ts: number;
  conns: number;
  countries: number;
  healthy: number;
  online: number;
  rx: number; // cumulative MB
  tx: number;
}

export interface ActivityEvent {
  id: string;
  ts: string;
  kind: string;
  name: string;
  detail?: string;
}

export interface Job {
  id: string;
  ts: number;
  finished_at?: number;
  label: string;
  status: string;
  count?: number;
  targets: string[];
}

export interface Schedule {
  id: string;
  name: string;
  cron: string;
  body?: string;
  script?: string;
  targets: string | string[];
  timeout: number;
  enabled: boolean;
  created_at?: number;
  last_run?: number | null;
  last_status?: string | null;
  last_job?: string | null;
  next_run?: number | null;
}

export interface Settings {
  autoheal: boolean;
  webhook: boolean;
}

export interface ProbeRow {
  exit: string;
  country?: string | null;
  country_iso?: string | null;
  ip?: string | null;
  status?: number;
  size?: number;
  hash?: string;
  server?: string;
  ctype?: string;
  ms?: number;
  final_url?: string;
  resp_headers?: [string, string][];
  preview?: string;
  truncated?: boolean;
  error?: string;
  diff?: "same" | "outlier" | "unique" | "error";
}

export interface ProbeResult {
  url: string;
  method: string;
  count: number;
  majority: { status: number; hash: string } | null;
  all_unique?: boolean;
  rows: ProbeRow[];
  direct?: ProbeRow | null;
  req?: { method: string; url: string };
}

export interface ExecResult {
  exit: number | null;
  output: string;
  error?: string;
}
