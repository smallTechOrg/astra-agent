"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface WizardState {
  /* Step 1: Identity */
  id: string;
  name: string;
  /* Step 2: WordPress */
  source_url: string;
  source_username: string;
  wp_app_password: string;
  /* Step 3: LinkedIn */
  linkedin_enabled: boolean;
  linkedin_org_id: string;
  linkedin_access_token: string;
  /* Step 4: Twitter */
  twitter_enabled: boolean;
  twitter_api_key: string;
  twitter_api_secret: string;
  twitter_access_token: string;
  twitter_access_secret: string;
  /* Step 5: Cadences */
  cadences: Array<{
    name: string;
    cron: string;
    prompt: string;
    feedback_last_n: number;
    enabled: boolean;
  }>;
}

const INITIAL: WizardState = {
  id: "",
  name: "",
  source_url: "",
  source_username: "",
  wp_app_password: "",
  linkedin_enabled: false,
  linkedin_org_id: "",
  linkedin_access_token: "",
  twitter_enabled: false,
  twitter_api_key: "",
  twitter_api_secret: "",
  twitter_access_token: "",
  twitter_access_secret: "",
  cadences: [],
};

const STEP_LABELS = [
  "Identity",
  "WordPress",
  "LinkedIn",
  "Twitter",
  "Cadences",
  "Review",
  "Save",
];

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function NewTenantPage() {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const router = useRouter();

  function update(partial: Partial<WizardState>) {
    setState((s) => ({ ...s, ...partial }));
  }

  function next() {
    setError(null);
    setStep((s) => Math.min(s + 1, 6));
  }
  function back() {
    setError(null);
    setStep((s) => Math.max(s - 1, 0));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      // 1. Create tenant
      await api("/api/tenants", {
        method: "POST",
        body: JSON.stringify({ id: state.id, name: state.name }),
      });

      // 2. Set tenant config
      const config: Record<string, unknown> = {
        source_type: "wordpress",
        source_url: state.source_url || null,
        source_username: state.source_username || null,
        linkedin_enabled: state.linkedin_enabled,
        linkedin_org_id: state.linkedin_org_id || null,
        twitter_enabled: state.twitter_enabled,
      };
      await api(`/api/tenants/${state.id}/config`, {
        method: "PUT",
        body: JSON.stringify(config),
      });

      // 3. Set tenant secrets (only if provided)
      const secrets: Record<string, string> = {};
      if (state.wp_app_password) secrets.WP_APP_PASSWORD = state.wp_app_password;
      if (state.linkedin_access_token) secrets.LINKEDIN_ACCESS_TOKEN = state.linkedin_access_token;
      if (state.twitter_api_key) secrets.TWITTER_API_KEY = state.twitter_api_key;
      if (state.twitter_api_secret) secrets.TWITTER_API_SECRET = state.twitter_api_secret;
      if (state.twitter_access_token) secrets.TWITTER_ACCESS_TOKEN = state.twitter_access_token;
      if (state.twitter_access_secret) secrets.TWITTER_ACCESS_SECRET = state.twitter_access_secret;

      for (const [key, value] of Object.entries(secrets)) {
        await api(`/api/tenants/${state.id}/secrets/${key}`, {
          method: "PUT",
          body: JSON.stringify({ value }),
        });
      }

      // 4. Create cadences
      for (const cad of state.cadences) {
        await api(`/api/tenants/${state.id}/cadences`, {
          method: "POST",
          body: JSON.stringify(cad),
        });
      }

      setDone(true);
      setStep(6);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell>
      <div className="max-w-2xl space-y-6">
        <Link
          href="/"
          className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
        >
          ← Back to dashboard
        </Link>

        <h2 className="text-2xl font-bold text-slate-900">New tenant</h2>

        {/* Step indicators */}
        <div className="flex gap-2 text-xs">
          {STEP_LABELS.map((label, i) => (
            <button
              key={label}
              onClick={() => i < step && !done && setStep(i)}
              disabled={i >= step || done}
              className={`px-2 py-1 rounded transition-colors ${
                i === step
                  ? "bg-indigo-600 text-white"
                  : i < step
                    ? "bg-indigo-100 text-indigo-700 hover:bg-indigo-200"
                    : "bg-slate-100 text-slate-400"
              }`}
            >
              {i + 1}. {label}
            </button>
          ))}
        </div>

        {error && (
          <div className="rounded-lg px-4 py-3 text-sm bg-red-50 text-red-800 border border-red-200">
            {error}
          </div>
        )}

        {/* Step content */}
        <div className="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
          {step === 0 && (
            <StepIdentity state={state} update={update} onNext={next} />
          )}
          {step === 1 && (
            <StepWordPress state={state} update={update} onNext={next} onBack={back} />
          )}
          {step === 2 && (
            <StepLinkedIn state={state} update={update} onNext={next} onBack={back} />
          )}
          {step === 3 && (
            <StepTwitter state={state} update={update} onNext={next} onBack={back} />
          )}
          {step === 4 && (
            <StepCadences state={state} update={update} onNext={next} onBack={back} />
          )}
          {step === 5 && (
            <StepReview state={state} onSave={save} onBack={back} saving={saving} />
          )}
          {step === 6 && done && (
            <div className="text-center py-8">
              <div className="text-4xl mb-3">✓</div>
              <h3 className="text-lg font-bold text-slate-900 mb-1">
                Tenant created
              </h3>
              <p className="text-sm text-slate-500 mb-4">
                <strong>{state.name}</strong> ({state.id}) is ready. Enable it
                and run the daemon to start distributing.
              </p>
              <button
                onClick={() => router.push(`/tenant?id=${state.id}`)}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
              >
                View tenant
              </button>
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}

/* ------------------------------------------------------------------ */
/*  Step components                                                    */
/* ------------------------------------------------------------------ */

function StepIdentity({
  state,
  update,
  onNext,
}: {
  state: WizardState;
  update: (p: Partial<WizardState>) => void;
  onNext: () => void;
}) {
  const valid = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(state.id) && state.name.trim().length > 0;

  return (
    <>
      <h3 className="text-lg font-semibold text-slate-900">Identity</h3>
      <div className="space-y-3">
        <Field
          label="Tenant ID"
          value={state.id}
          onChange={(v) => update({ id: v })}
          placeholder="acme-corp"
          hint="Lowercase letters, numbers, and hyphens."
          mono
        />
        <Field
          label="Display name"
          value={state.name}
          onChange={(v) => update({ name: v })}
          placeholder="Acme Corporation"
        />
      </div>
      <NavButtons onNext={valid ? onNext : undefined} />
    </>
  );
}

function StepWordPress({
  state,
  update,
  onNext,
  onBack,
}: {
  state: WizardState;
  update: (p: Partial<WizardState>) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <>
      <h3 className="text-lg font-semibold text-slate-900">WordPress source</h3>
      <div className="space-y-3">
        <Field
          label="Site URL"
          value={state.source_url}
          onChange={(v) => update({ source_url: v })}
          placeholder="https://blog.acme.com"
        />
        <Field
          label="Username"
          value={state.source_username}
          onChange={(v) => update({ source_username: v })}
          placeholder="admin"
        />
        <Field
          label="Application password"
          value={state.wp_app_password}
          onChange={(v) => update({ wp_app_password: v })}
          type="password"
          hint="WordPress → Users → Application Passwords"
        />
      </div>
      <NavButtons onBack={onBack} onNext={onNext} />
    </>
  );
}

function StepLinkedIn({
  state,
  update,
  onNext,
  onBack,
}: {
  state: WizardState;
  update: (p: Partial<WizardState>) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <>
      <h3 className="text-lg font-semibold text-slate-900">
        LinkedIn destination
      </h3>
      <label className="flex items-center gap-2 text-sm mb-4">
        <input
          type="checkbox"
          checked={state.linkedin_enabled}
          onChange={(e) => update({ linkedin_enabled: e.target.checked })}
          className="rounded border-slate-300"
        />
        Enable LinkedIn distribution
      </label>
      {state.linkedin_enabled && (
        <div className="space-y-3">
          <Field
            label="Organization ID"
            value={state.linkedin_org_id}
            onChange={(v) => update({ linkedin_org_id: v })}
            placeholder="12345678"
          />
          <Field
            label="Access token"
            value={state.linkedin_access_token}
            onChange={(v) => update({ linkedin_access_token: v })}
            type="password"
            hint="Or use: astra auth linkedin --tenant <id> after saving."
          />
        </div>
      )}
      <NavButtons onBack={onBack} onNext={onNext} nextLabel={state.linkedin_enabled ? "Next" : "Skip"} />
    </>
  );
}

function StepTwitter({
  state,
  update,
  onNext,
  onBack,
}: {
  state: WizardState;
  update: (p: Partial<WizardState>) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <>
      <h3 className="text-lg font-semibold text-slate-900">
        Twitter destination
      </h3>
      <label className="flex items-center gap-2 text-sm mb-4">
        <input
          type="checkbox"
          checked={state.twitter_enabled}
          onChange={(e) => update({ twitter_enabled: e.target.checked })}
          className="rounded border-slate-300"
        />
        Enable Twitter distribution
      </label>
      {state.twitter_enabled && (
        <div className="space-y-3">
          <Field
            label="API key"
            value={state.twitter_api_key}
            onChange={(v) => update({ twitter_api_key: v })}
            type="password"
          />
          <Field
            label="API secret"
            value={state.twitter_api_secret}
            onChange={(v) => update({ twitter_api_secret: v })}
            type="password"
          />
          <Field
            label="Access token"
            value={state.twitter_access_token}
            onChange={(v) => update({ twitter_access_token: v })}
            type="password"
          />
          <Field
            label="Access secret"
            value={state.twitter_access_secret}
            onChange={(v) => update({ twitter_access_secret: v })}
            type="password"
          />
        </div>
      )}
      <NavButtons onBack={onBack} onNext={onNext} nextLabel={state.twitter_enabled ? "Next" : "Skip"} />
    </>
  );
}

function StepCadences({
  state,
  update,
  onNext,
  onBack,
}: {
  state: WizardState;
  update: (p: Partial<WizardState>) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  function addCadence() {
    update({
      cadences: [
        ...state.cadences,
        {
          name: "",
          cron: "0 9 * * *",
          prompt: "twitter_announcement",
          feedback_last_n: 20,
          enabled: true,
        },
      ],
    });
  }

  function updateCadence(
    index: number,
    patch: Partial<WizardState["cadences"][0]>,
  ) {
    const copy = [...state.cadences];
    copy[index] = { ...copy[index], ...patch };
    update({ cadences: copy });
  }

  function removeCadence(index: number) {
    update({ cadences: state.cadences.filter((_, i) => i !== index) });
  }

  return (
    <>
      <h3 className="text-lg font-semibold text-slate-900">Cadences</h3>
      <p className="text-sm text-slate-500 mb-4">
        Cadences schedule autonomous tweets on a cron. Optional — skip if not
        needed.
      </p>

      {state.cadences.map((c, i) => (
        <div
          key={i}
          className="border border-slate-200 rounded-lg p-4 mb-3 space-y-2"
        >
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium text-slate-700">
              Cadence {i + 1}
            </span>
            <button
              onClick={() => removeCadence(i)}
              className="text-xs text-red-600 hover:text-red-800"
            >
              Remove
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field
              label="Name"
              value={c.name}
              onChange={(v) => updateCadence(i, { name: v })}
              placeholder="daily-tips"
              mono
            />
            <Field
              label="Cron"
              value={c.cron}
              onChange={(v) => updateCadence(i, { cron: v })}
              mono
            />
            <Field
              label="Prompt"
              value={c.prompt}
              onChange={(v) => updateCadence(i, { prompt: v })}
            />
            <Field
              label="Feedback last N"
              value={String(c.feedback_last_n)}
              onChange={(v) =>
                updateCadence(i, { feedback_last_n: Number(v) || 20 })
              }
            />
          </div>
        </div>
      ))}

      <button
        onClick={addCadence}
        className="text-sm text-indigo-600 hover:text-indigo-800"
      >
        + Add cadence
      </button>

      <NavButtons
        onBack={onBack}
        onNext={onNext}
        nextLabel={state.cadences.length > 0 ? "Next" : "Skip"}
      />
    </>
  );
}

function StepReview({
  state,
  onSave,
  onBack,
  saving,
}: {
  state: WizardState;
  onSave: () => void;
  onBack: () => void;
  saving: boolean;
}) {
  return (
    <>
      <h3 className="text-lg font-semibold text-slate-900">Review</h3>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-slate-500">Tenant ID</dt>
        <dd className="font-mono">{state.id}</dd>
        <dt className="text-slate-500">Name</dt>
        <dd>{state.name}</dd>
        <dt className="text-slate-500">WordPress URL</dt>
        <dd>{state.source_url || "—"}</dd>
        <dt className="text-slate-500">WordPress user</dt>
        <dd>{state.source_username || "—"}</dd>
        <dt className="text-slate-500">WP password</dt>
        <dd>{state.wp_app_password ? "••••••" : "—"}</dd>
        <dt className="text-slate-500">LinkedIn</dt>
        <dd>
          {state.linkedin_enabled
            ? `Org ${state.linkedin_org_id || "—"}`
            : "Disabled"}
        </dd>
        <dt className="text-slate-500">Twitter</dt>
        <dd>
          {state.twitter_enabled
            ? `${state.twitter_api_key ? "Keys set" : "No keys"}`
            : "Disabled"}
        </dd>
        <dt className="text-slate-500">Cadences</dt>
        <dd>
          {state.cadences.length > 0
            ? state.cadences.map((c) => c.name || "(unnamed)").join(", ")
            : "None"}
        </dd>
      </dl>

      <div className="flex gap-3 pt-4">
        <button
          onClick={onBack}
          className="px-4 py-2 text-slate-600 text-sm hover:text-slate-900"
        >
          ← Back
        </button>
        <button
          onClick={onSave}
          disabled={saving}
          className="px-6 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Creating…" : "Create tenant"}
        </button>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared helpers                                                     */
/* ------------------------------------------------------------------ */

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  hint,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  hint?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-1">
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 ${mono ? "font-mono" : ""}`}
      />
      {hint && <p className="text-xs text-slate-400 mt-1">{hint}</p>}
    </div>
  );
}

function NavButtons({
  onBack,
  onNext,
  nextLabel = "Next",
}: {
  onBack?: () => void;
  onNext?: () => void;
  nextLabel?: string;
}) {
  return (
    <div className="flex gap-3 pt-4">
      {onBack && (
        <button
          onClick={onBack}
          className="px-4 py-2 text-slate-600 text-sm hover:text-slate-900 transition-colors"
        >
          ← Back
        </button>
      )}
      {onNext && (
        <button
          onClick={onNext}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          {nextLabel} →
        </button>
      )}
    </div>
  );
}
