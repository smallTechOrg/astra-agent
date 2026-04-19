"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Shell } from "@/components/shell";
import { api, ApiError } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TenantDetail {
  id: string;
  name: string;
  enabled: boolean;
  config: Record<string, unknown> | null;
  destinations: Record<
    string,
    { needs_reauth: boolean; degraded: boolean; last_error: string | null }
  >;
  secrets: Record<string, "set" | "empty">;
}

interface Cadence {
  id: number;
  tenant_id: string;
  name: string;
  cron: string;
  prompt: string;
  feedback_last_n: number;
  enabled: boolean;
}

interface PublishEvent {
  id: number;
  title: string;
  url: string;
  published_at: string;
  detected_at: string;
  distribution: Array<{
    platform: string;
    status: string;
    error: string | null;
    attempted_at: string;
  }>;
}

interface Tweet {
  id: number;
  cadence_name: string;
  text: string;
  status: string;
  error: string | null;
  posted_at: string;
}

type Tab = "config" | "secrets" | "cadences" | "events" | "tweets";

/* ------------------------------------------------------------------ */
/*  Main page wrapper (Suspense needed for useSearchParams)            */
/* ------------------------------------------------------------------ */

export default function TenantPage() {
  return (
    <Suspense
      fallback={
        <Shell>
          <p className="text-slate-400">Loading…</p>
        </Shell>
      }
    >
      <TenantContent />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/*  Content                                                            */
/* ------------------------------------------------------------------ */

function TenantContent() {
  const searchParams = useSearchParams();
  const tenantId = searchParams.get("id") ?? "";
  const router = useRouter();

  const [tenant, setTenant] = useState<TenantDetail | null>(null);
  const [tab, setTab] = useState<Tab>("config");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTenant(await api<TenantDetail>(`/api/tenants/${tenantId}`));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      setError(err instanceof Error ? err.message : "Failed to load tenant");
    }
  }, [tenantId]);

  useEffect(() => {
    if (tenantId) load();
  }, [tenantId, load]);

  if (!tenantId)
    return (
      <Shell>
        <p className="text-slate-500">No tenant selected.</p>
      </Shell>
    );

  return (
    <Shell>
      <div className="max-w-5xl space-y-6">
        {/* Back link */}
        <Link
          href="/"
          className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
        >
          ← Back to dashboard
        </Link>

        {error && (
          <div className="rounded-lg px-4 py-3 text-sm bg-red-50 text-red-800 border border-red-200">
            {error}
          </div>
        )}

        {tenant && (
          <>
            {/* Header */}
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold text-slate-900">
                  {tenant.name}
                </h2>
                <p className="text-sm text-slate-500 font-mono">{tenant.id}</p>
              </div>
              <div className="flex items-center gap-3">
                <ToggleButton tenant={tenant} onDone={load} />
                <DeleteButton tenantId={tenant.id} onDone={() => router.push("/")} />
              </div>
            </div>

            {/* Destination health */}
            {Object.keys(tenant.destinations).length > 0 && (
              <div className="flex gap-4">
                {Object.entries(tenant.destinations).map(([platform, st]) => (
                  <div
                    key={platform}
                    className={`text-xs px-3 py-1.5 rounded-lg border ${
                      st.degraded || st.needs_reauth
                        ? "bg-red-50 border-red-200 text-red-700"
                        : "bg-emerald-50 border-emerald-200 text-emerald-700"
                    }`}
                  >
                    <strong className="capitalize">{platform}</strong>
                    {st.needs_reauth && " — needs reauth"}
                    {st.degraded && " — degraded"}
                    {!st.needs_reauth && !st.degraded && " — healthy"}
                  </div>
                ))}
              </div>
            )}

            {/* Tabs */}
            <div className="border-b border-slate-200">
              <nav className="flex gap-6">
                {(
                  [
                    "config",
                    "secrets",
                    "cadences",
                    "events",
                    "tweets",
                  ] as Tab[]
                ).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={`pb-2 text-sm font-medium capitalize transition-colors ${
                      tab === t
                        ? "border-b-2 border-indigo-600 text-indigo-600"
                        : "text-slate-500 hover:text-slate-700"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </nav>
            </div>

            {/* Tab content */}
            {tab === "config" && (
              <ConfigTab tenantId={tenant.id} config={tenant.config} onSaved={load} />
            )}
            {tab === "secrets" && (
              <SecretsTab tenantId={tenant.id} secrets={tenant.secrets} onSaved={load} />
            )}
            {tab === "cadences" && <CadencesTab tenantId={tenant.id} />}
            {tab === "events" && <EventsTab tenantId={tenant.id} />}
            {tab === "tweets" && <TweetsTab tenantId={tenant.id} />}
          </>
        )}
      </div>
    </Shell>
  );
}

/* ------------------------------------------------------------------ */
/*  Toggle enable/disable                                              */
/* ------------------------------------------------------------------ */

function ToggleButton({
  tenant,
  onDone,
}: {
  tenant: TenantDetail;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      await api(`/api/tenants/${tenant.id}`, {
        method: "PUT",
        body: JSON.stringify({ enabled: !tenant.enabled }),
      });
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        tenant.enabled
          ? "bg-amber-100 text-amber-800 hover:bg-amber-200"
          : "bg-emerald-100 text-emerald-800 hover:bg-emerald-200"
      }`}
    >
      {tenant.enabled ? "Disable" : "Enable"}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Delete                                                             */
/* ------------------------------------------------------------------ */

function DeleteButton({
  tenantId,
  onDone,
}: {
  tenantId: string;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleDelete() {
    if (!confirm(`Delete tenant "${tenantId}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api(`/api/tenants/${tenantId}`, { method: "DELETE" });
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={handleDelete}
      disabled={busy}
      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-red-100 text-red-800 hover:bg-red-200 transition-colors"
    >
      Delete
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Config tab                                                         */
/* ------------------------------------------------------------------ */

const CONFIG_FIELDS: Array<{
  key: string;
  label: string;
  type: "text" | "checkbox";
}> = [
  { key: "source_type", label: "Source type", type: "text" },
  { key: "source_url", label: "Source URL", type: "text" },
  { key: "source_username", label: "Source username", type: "text" },
  { key: "source_poll_cron", label: "Poll cron", type: "text" },
  { key: "linkedin_enabled", label: "LinkedIn enabled", type: "checkbox" },
  { key: "linkedin_org_id", label: "LinkedIn Org ID", type: "text" },
  { key: "twitter_enabled", label: "Twitter enabled", type: "checkbox" },
  {
    key: "twitter_announcement_prompt",
    label: "Twitter announcement prompt",
    type: "text",
  },
  { key: "llm_provider", label: "LLM provider (override)", type: "text" },
  { key: "llm_model", label: "LLM model (override)", type: "text" },
  { key: "llm_temperature", label: "LLM temperature (override)", type: "text" },
  { key: "llm_max_tokens", label: "LLM max tokens (override)", type: "text" },
];

function ConfigTab({
  tenantId,
  config,
  onSaved,
}: {
  tenantId: string;
  config: Record<string, unknown> | null;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Record<string, unknown>>(config ?? {});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      await api(`/api/tenants/${tenantId}/config`, {
        method: "PUT",
        body: JSON.stringify(form),
      });
      setMsg("Saved");
      onSaved();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {CONFIG_FIELDS.map((f) => (
          <div key={f.key}>
            {f.type === "checkbox" ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!form[f.key]}
                  onChange={(e) =>
                    setForm({ ...form, [f.key]: e.target.checked })
                  }
                  className="rounded border-slate-300"
                />
                {f.label}
              </label>
            ) : (
              <>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  {f.label}
                </label>
                <input
                  type="text"
                  value={String(form[f.key] ?? "")}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      [f.key]: e.target.value || null,
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
              </>
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save config"}
        </button>
        {msg && (
          <span
            className={`text-sm ${msg === "Saved" ? "text-emerald-600" : "text-red-600"}`}
          >
            {msg}
          </span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Secrets tab                                                        */
/* ------------------------------------------------------------------ */

function SecretsTab({
  tenantId,
  secrets,
  onSaved,
}: {
  tenantId: string;
  secrets: Record<string, "set" | "empty">;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(key: string) {
    setBusy(true);
    try {
      await api(`/api/tenants/${tenantId}/secrets/${key}`, {
        method: "PUT",
        body: JSON.stringify({ value }),
      });
      setEditing(null);
      setValue("");
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  async function remove(key: string) {
    setBusy(true);
    try {
      await api(`/api/tenants/${tenantId}/secrets/${key}`, {
        method: "DELETE",
      });
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {Object.entries(secrets).map(([key, status]) => (
        <div
          key={key}
          className="flex items-center justify-between bg-white border border-slate-200 rounded-lg px-4 py-3"
        >
          <div>
            <span className="text-sm font-mono font-medium text-slate-800">
              {key}
            </span>
            <span
              className={`ml-3 text-xs ${status === "set" ? "text-emerald-600" : "text-slate-400"}`}
            >
              {status === "set" ? "● Set" : "○ Empty"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {editing === key ? (
              <>
                <input
                  type="password"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="Enter value…"
                  className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm w-64 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  autoFocus
                />
                <button
                  onClick={() => save(key)}
                  disabled={busy || !value}
                  className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  onClick={() => {
                    setEditing(null);
                    setValue("");
                  }}
                  className="px-3 py-1.5 text-slate-500 text-xs hover:text-slate-700"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => setEditing(key)}
                  className="px-3 py-1.5 bg-slate-100 text-slate-700 rounded-lg text-xs font-medium hover:bg-slate-200"
                >
                  {status === "set" ? "Update" : "Set"}
                </button>
                {status === "set" && (
                  <button
                    onClick={() => remove(key)}
                    disabled={busy}
                    className="px-3 py-1.5 text-red-600 text-xs hover:text-red-800"
                  >
                    Remove
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Cadences tab                                                       */
/* ------------------------------------------------------------------ */

function CadencesTab({ tenantId }: { tenantId: string }) {
  const [cadences, setCadences] = useState<Cadence[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    name: "",
    cron: "0 9 * * *",
    prompt: "twitter_announcement",
    feedback_last_n: 20,
    enabled: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setCadences(await api<Cadence[]>(`/api/tenants/${tenantId}/cadences`));
  }, [tenantId]);

  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/tenants/${tenantId}/cadences`, {
        method: "POST",
        body: JSON.stringify(form),
      });
      setShowNew(false);
      setForm({
        name: "",
        cron: "0 9 * * *",
        prompt: "twitter_announcement",
        feedback_last_n: 20,
        enabled: true,
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled(c: Cadence) {
    await api(`/api/tenants/${tenantId}/cadences/${c.name}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: !c.enabled }),
    });
    load();
  }

  async function remove(name: string) {
    if (!confirm(`Delete cadence "${name}"?`)) return;
    await api(`/api/tenants/${tenantId}/cadences/${name}`, {
      method: "DELETE",
    });
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          onClick={() => setShowNew(!showNew)}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          {showNew ? "Cancel" : "New cadence"}
        </button>
      </div>

      {showNew && (
        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Name
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="daily-tips"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Cron
              </label>
              <input
                value={form.cron}
                onChange={(e) => setForm({ ...form, cron: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Prompt name
              </label>
              <input
                value={form.prompt}
                onChange={(e) => setForm({ ...form, prompt: e.target.value })}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Feedback last N
              </label>
              <input
                type="number"
                value={form.feedback_last_n}
                onChange={(e) =>
                  setForm({ ...form, feedback_last_n: Number(e.target.value) })
                }
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            onClick={create}
            disabled={busy}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            Create
          </button>
        </div>
      )}

      {cadences.length === 0 && !showNew ? (
        <p className="text-sm text-slate-500 py-4">No cadences configured.</p>
      ) : (
        <div className="space-y-2">
          {cadences.map((c) => (
            <div
              key={c.name}
              className="flex items-center justify-between bg-white border border-slate-200 rounded-lg px-4 py-3"
            >
              <div>
                <span className="font-medium text-sm text-slate-900">
                  {c.name}
                </span>
                <span className="ml-3 text-xs text-slate-500 font-mono">
                  {c.cron}
                </span>
                <span className="ml-3 text-xs text-slate-400">
                  prompt: {c.prompt}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => toggleEnabled(c)}
                  className={`px-2 py-1 rounded text-xs font-medium ${
                    c.enabled
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {c.enabled ? "Enabled" : "Disabled"}
                </button>
                <button
                  onClick={() => remove(c.name)}
                  className="text-xs text-red-600 hover:text-red-800"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Events tab                                                         */
/* ------------------------------------------------------------------ */

function EventsTab({ tenantId }: { tenantId: string }) {
  const [events, setEvents] = useState<PublishEvent[]>([]);

  useEffect(() => {
    api<PublishEvent[]>(`/api/events?tenant=${tenantId}&limit=20`).then(
      setEvents,
    );
  }, [tenantId]);

  if (events.length === 0)
    return <p className="text-sm text-slate-500 py-4">No events yet.</p>;

  return (
    <div className="space-y-3">
      {events.map((ev) => (
        <div
          key={ev.id}
          className="bg-white border border-slate-200 rounded-lg px-4 py-3"
        >
          <div className="flex justify-between items-start">
            <div>
              <a
                href={ev.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-sm text-indigo-600 hover:underline"
              >
                {ev.title}
              </a>
              <p className="text-xs text-slate-500 mt-0.5">
                Published {new Date(ev.published_at).toLocaleString()} —
                Detected {new Date(ev.detected_at).toLocaleString()}
              </p>
            </div>
          </div>
          {ev.distribution.length > 0 && (
            <div className="mt-2 flex gap-3">
              {ev.distribution.map((d, i) => (
                <span
                  key={i}
                  className={`text-xs px-2 py-1 rounded ${
                    d.status === "success"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-red-50 text-red-700"
                  }`}
                >
                  {d.platform}: {d.status}
                  {d.error && ` — ${d.error}`}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tweets tab                                                         */
/* ------------------------------------------------------------------ */

function TweetsTab({ tenantId }: { tenantId: string }) {
  const [tweets, setTweets] = useState<Tweet[]>([]);

  useEffect(() => {
    api<Tweet[]>(`/api/tenants/${tenantId}/tweets?limit=20`).then(setTweets);
  }, [tenantId]);

  if (tweets.length === 0)
    return (
      <p className="text-sm text-slate-500 py-4">No scheduled tweets yet.</p>
    );

  return (
    <div className="space-y-3">
      {tweets.map((tw) => (
        <div
          key={tw.id}
          className="bg-white border border-slate-200 rounded-lg px-4 py-3"
        >
          <p className="text-sm text-slate-900">{tw.text}</p>
          <div className="flex gap-4 mt-2 text-xs text-slate-500">
            <span>Cadence: {tw.cadence_name}</span>
            <span
              className={
                tw.status === "posted" ? "text-emerald-600" : "text-amber-600"
              }
            >
              {tw.status}
            </span>
            <span>{new Date(tw.posted_at).toLocaleString()}</span>
          </div>
          {tw.error && (
            <p className="text-xs text-red-600 mt-1">{tw.error}</p>
          )}
        </div>
      ))}
    </div>
  );
}
