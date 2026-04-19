"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface OperatorConfig {
  llm_provider: string;
  llm_model: string;
  llm_temperature: number;
  llm_max_tokens: number;
  log_level: string;
  share_sweep_cron: string;
  startup_grace_seconds: number;
  updated_at: string;
}

type SecretsMap = Record<string, "set" | "empty">;

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function SettingsPage() {
  const [tab, setTab] = useState<"config" | "secrets">("config");

  return (
    <Shell>
      <div className="max-w-3xl space-y-6">
        <h2 className="text-2xl font-bold text-slate-900">
          Operator Settings
        </h2>

        <div className="border-b border-slate-200">
          <nav className="flex gap-6">
            {(["config", "secrets"] as const).map((t) => (
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

        {tab === "config" && <ConfigSection />}
        {tab === "secrets" && <SecretsSection />}
      </div>
    </Shell>
  );
}

/* ------------------------------------------------------------------ */
/*  Config section                                                     */
/* ------------------------------------------------------------------ */

const CONFIG_FIELDS: Array<{
  key: keyof OperatorConfig;
  label: string;
  type: "text" | "number";
}> = [
  { key: "llm_provider", label: "LLM provider", type: "text" },
  { key: "llm_model", label: "LLM model", type: "text" },
  { key: "llm_temperature", label: "Temperature", type: "number" },
  { key: "llm_max_tokens", label: "Max tokens", type: "number" },
  { key: "log_level", label: "Log level", type: "text" },
  { key: "share_sweep_cron", label: "Share sweep cron", type: "text" },
  { key: "startup_grace_seconds", label: "Startup grace (s)", type: "number" },
];

function ConfigSection() {
  const [config, setConfig] = useState<OperatorConfig | null>(null);
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api<OperatorConfig>("/api/operator/config").then((cfg) => {
      setConfig(cfg);
      setForm({ ...cfg });
    });
  }, []);

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      // Send only changed fields
      const changes: Record<string, unknown> = {};
      for (const f of CONFIG_FIELDS) {
        const val = form[f.key];
        if (config && val !== config[f.key]) {
          changes[f.key] = val;
        }
      }
      if (Object.keys(changes).length === 0) {
        setMsg("No changes");
        setSaving(false);
        return;
      }
      await api("/api/operator/config", {
        method: "PUT",
        body: JSON.stringify(changes),
      });
      setMsg("Saved");
      // Reload
      const fresh = await api<OperatorConfig>("/api/operator/config");
      setConfig(fresh);
      setForm({ ...fresh });
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (!config) return <p className="text-slate-400 text-sm">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {CONFIG_FIELDS.map((f) => (
          <div key={f.key}>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              {f.label}
            </label>
            <input
              type={f.type}
              value={String(form[f.key] ?? "")}
              onChange={(e) =>
                setForm({
                  ...form,
                  [f.key]:
                    f.type === "number"
                      ? Number(e.target.value)
                      : e.target.value,
                })
              }
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-400">
        Last updated: {new Date(config.updated_at).toLocaleString()}
      </p>
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {msg && (
          <span
            className={`text-sm ${msg === "Saved" || msg === "No changes" ? "text-emerald-600" : "text-red-600"}`}
          >
            {msg}
          </span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Secrets section                                                    */
/* ------------------------------------------------------------------ */

function SecretsSection() {
  const [secrets, setSecrets] = useState<SecretsMap>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setSecrets(await api<SecretsMap>("/api/operator/secrets"));
  }

  useEffect(() => {
    load();
  }, []);

  async function save(key: string) {
    setBusy(true);
    try {
      await api(`/api/operator/secrets/${key}`, {
        method: "PUT",
        body: JSON.stringify({ value }),
      });
      setEditing(null);
      setValue("");
      load();
    } finally {
      setBusy(false);
    }
  }

  async function remove(key: string) {
    setBusy(true);
    try {
      await api(`/api/operator/secrets/${key}`, { method: "DELETE" });
      load();
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
