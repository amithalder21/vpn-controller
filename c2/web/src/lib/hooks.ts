import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { api } from "./api";
import type {
  ActivityEvent,
  Job,
  MetricPoint,
  ProxyState,
  Schedule,
  Settings,
  Worker,
} from "./types";

export const keys = {
  workers: ["workers"] as const,
  proxy: ["proxy"] as const,
  metrics: ["metrics"] as const,
  events: ["events"] as const,
  jobs: ["jobs"] as const,
  schedules: ["schedules"] as const,
  settings: ["settings"] as const,
  scripts: ["scripts"] as const,
};

export function useWorkers(enabled = true) {
  return useQuery({
    queryKey: keys.workers,
    queryFn: () => api<Worker[]>("GET", "/api/workers"),
    refetchInterval: 5000,
    enabled,
  });
}
export function useProxy(enabled = true) {
  return useQuery({
    queryKey: keys.proxy,
    queryFn: () => api<ProxyState>("GET", "/api/proxy"),
    refetchInterval: 6000,
    enabled,
  });
}
export function useMetrics(enabled = true) {
  return useQuery({
    queryKey: keys.metrics,
    queryFn: () => api<MetricPoint[]>("GET", "/api/metrics"),
    refetchInterval: 8000,
    enabled,
  });
}
export function useEvents(enabled = true) {
  return useQuery({
    queryKey: keys.events,
    queryFn: () => api<ActivityEvent[]>("GET", "/api/events"),
    refetchInterval: 8000,
    enabled,
  });
}
export function useJobs(enabled = true) {
  return useQuery({
    queryKey: keys.jobs,
    queryFn: () => api<Job[]>("GET", "/api/jobs"),
    refetchInterval: 6000,
    enabled,
  });
}
export function useSchedules(enabled = true) {
  return useQuery({
    queryKey: keys.schedules,
    queryFn: () => api<Schedule[]>("GET", "/api/schedules"),
    refetchInterval: 15000,
    enabled,
  });
}
export function useSettings(enabled = true) {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => api<Settings>("GET", "/api/settings"),
    enabled,
  });
}
export function useScripts(enabled = true) {
  return useQuery({
    queryKey: keys.scripts,
    queryFn: () => api<string[]>("GET", "/api/scripts"),
    enabled,
  });
}

/* ---------------- toast store ---------------- */
export type ToastKind = "ok" | "err" | "info";
export interface Toast {
  id: number;
  text: string;
  kind: ToastKind;
}
let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let nextId = 1;
function emit() {
  listeners.forEach((l) => l());
}
export function toast(text: string, kind: ToastKind = "info", ms = 3200) {
  const id = nextId++;
  toasts = [...toasts, { id, text, kind }];
  emit();
  window.setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emit();
  }, ms);
}
export function dismissToast(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}
export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => toasts,
    () => toasts,
  );
}
