"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Shell } from "@/components/shell";
import { api, ApiError } from "@/lib/api";

interface Tenant {
  id: string;
  name: string;
  enabled: boolean;
  source_type: string | null;
  source_url: string | null;
  linkedin_enabled: boolean;
  twitter_enabled: boolean;
}

interface Health {
  daemon: {
    online: boolean;
    started_at: string | null;
    tenant_count: number;
    job_count: number;
  };
  tenants: Array<{
    id: string;
    enabled: boolean;
    destinations: Record<
      string,
      { needs_reauth: boolean; degraded: boolean }
    >;
  }>;
}

export default function Dashboard() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    Promise.all([api<Tenant[]>("/api/tenants"), api<Health>("/api/health")])
      .then(([t, h]) => {
        setTenants(t);
        setHealth(h);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) return;
        setError(err.message);
      });
  }, []);

  return (
    <Shell>
      <div className="space-y-6 max-w-5xl">
        {/* Daemon banner */}
        {health && (
          <div
            className={`rounded-lg px-4 py-3 text-sm ${
              health.daemon.online
                ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                : "bg-amber-50 text-amber-800 border border-amber-200"
            }`}
          >
            {health.daemon.online ? (
              <>
                <strong>Daemon online</strong> — {health.daemon.tenant_count}{" "}
                tenants, {health.daemon.job_count} jobs
              </>
            ) : (
              <>
                <strong>Daemon offline</strong> — run{" "}
                <code className="bg-amber-100 px-1 rounded font-mono text-xs">
                  astra run
                </code>{" "}
                to start
              </>
            )}
          </div>
        )}

        {error && (
          <div className="rounded-lg px-4 py-3 text-sm bg-red-50 text-red-800 border border-red-200">
            {error}
          </div>
        )}

        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold text-slate-900">Tenants</h2>
          <Link
            href="/tenants/new"
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            Add tenant
          </Link>
        </div>

        {/* Tenant list */}
        {tenants.length === 0 && !error ? (
          <div className="text-center py-16 text-slate-500">
            <p className="text-lg">No tenants yet</p>
            <p className="text-sm mt-1">
              Create your first tenant to get started.
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                    Tenant
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                    Destinations
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {tenants.map((t) => (
                  <tr
                    key={t.id}
                    className="hover:bg-slate-50 cursor-pointer transition-colors"
                    onClick={() => router.push(`/tenant?id=${t.id}`)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{t.name}</div>
                      <div className="text-xs text-slate-500 font-mono">
                        {t.id}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600">
                      {t.source_url || (
                        <span className="text-slate-400">Not configured</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {t.linkedin_enabled && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                            LinkedIn
                          </span>
                        )}
                        {t.twitter_enabled && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800">
                            Twitter
                          </span>
                        )}
                        {!t.linkedin_enabled && !t.twitter_enabled && (
                          <span className="text-sm text-slate-400">None</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          t.enabled
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {t.enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Shell>
  );
}
