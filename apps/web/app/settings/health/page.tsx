"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, LoaderCircle } from "lucide-react";
import { Alert, EmptyState, PageHead } from "@/components/ui";
import { ListRowsSkeleton } from "@/components/skeleton";
import { useToast } from "@/components/toast";
import { api, messageFrom, ApiError } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatWhen } from "@/lib/datetime";
import type { ErrorEvent, ReadinessCheck } from "@/types";

const PAGE_SIZE = 50;

type ReadinessState = "checking" | "ok" | "degraded" | "unknown";

export default function HealthPage() {
  const { t, lang } = useLanguage();
  const toast = useToast();
  const [readiness, setReadiness] = useState<ReadinessState>("checking");
  const [errors, setErrors] = useState<ErrorEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const loadReadiness = useCallback(async () => {
    try {
      // /health/ready answers 503 when degraded, and api() throws ApiError on
      // any non-ok response — that 503 is a valid state to render as a badge,
      // never a toast.
      const check = await api<ReadinessCheck>("/health/ready");
      setReadiness(check.status);
    } catch (err) {
      setReadiness(err instanceof ApiError ? "degraded" : "unknown");
    }
  }, []);

  const loadErrors = useCallback(async (before?: string) => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (before) params.set("before", before);
    try {
      const page = await api<ErrorEvent[]>(`/health/errors?${params.toString()}`);
      setErrors((current) => (before ? [...current, ...page] : page));
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      toast.error(messageFrom(err));
      setHasMore(false);
    }
  }, [toast]);

  useEffect(() => {
    Promise.all([loadReadiness(), loadErrors()]).finally(() => setLoading(false));
    // Runs once on mount; loadReadiness/loadErrors are stable via useCallback.
  }, []);

  async function loadMore() {
    const last = errors.at(-1);
    if (!last) return;
    setLoadingMore(true);
    await loadErrors(last.id);
    setLoadingMore(false);
  }

  return (
    <div className="page">
      <Link href="/settings" className="back-link"><ArrowLeft size={17} /> {t("settings.index.title")}</Link>
      <PageHead eyebrow={t("health.eyebrow")} title={t("health.title")} description={t("health.description")} />

      <section className="section-block">
        <Alert type={readiness === "ok" ? "success" : readiness === "checking" ? "info" : "error"}>
          {readiness === "checking" && <LoaderCircle size={14} className="spin" />}{" "}
          {t(readiness === "checking" ? "health.readinessChecking" : readiness === "ok" ? "health.readinessOk" : readiness === "degraded" ? "health.readinessDegraded" : "health.readinessUnknown")}
        </Alert>
      </section>

      <section className="section-block">
        <div className="section-heading"><div><h2>{t("health.errorsHeading")}</h2><p>{t("health.errorsCopy")}</p></div></div>

        {loading ? <ListRowsSkeleton rows={6} /> : errors.length === 0 ? (
          <EmptyState icon={<CheckCircle2 />} title={t("health.emptyTitle")} description={t("health.emptyDescription")} />
        ) : (
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr><th>{t("health.colWhen")}</th><th>{t("health.colSource")}</th><th>{t("health.colException")}</th><th>{t("health.colMessage")}</th><th>{t("health.colPath")}</th><th /></tr>
              </thead>
              <tbody>
                {errors.map((row) => (
                  <tr key={row.id}>
                    <td>{formatWhen(row.occurred_at, lang)}</td>
                    <td><span className={`pill ${row.is_global ? "purple" : ""}`}>{t(row.is_global ? "health.scopeGlobal" : "health.scopeAgency")}</span> {row.source}</td>
                    <td>{row.exception_type}</td>
                    <td>{row.message}</td>
                    <td>{row.request_method && row.request_path ? `${row.request_method} ${row.request_path}` : row.request_path ?? row.subject_ref ?? "—"}</td>
                    <td>{row.traceback && <details><summary>{t("health.traceback")}</summary><pre>{row.traceback}</pre></details>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!loading && errors.length > 0 && (
          hasMore ? (
            <button type="button" className="button secondary" disabled={loadingMore} onClick={loadMore}>
              {loadingMore ? <LoaderCircle size={16} className="spin" /> : null} {t("health.loadMore")}
            </button>
          ) : (
            <p className="field-help">{t("health.endOfList")}</p>
          )
        )}
      </section>
    </div>
  );
}
