"use client";

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Prompt {
  id: number;
  tenant_id: string | null;
  name: string;
  content: string;
  scope: "operator" | "tenant";
  updated_at: string;
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [editing, setEditing] = useState<Prompt | null>(null);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    setPrompts(await api<Prompt[]>("/api/prompts?scope=operator"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function startEdit(p: Prompt) {
    setEditing(p);
    setContent(p.content);
    setMsg(null);
  }

  async function handleSave() {
    if (!editing) return;
    setSaving(true);
    setMsg(null);
    try {
      await api(`/api/prompts/${editing.name}?scope=operator`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      });
      setMsg("Saved");
      setEditing(null);
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      await api(`/api/prompts/${newName}?scope=operator`, {
        method: "PUT",
        body: JSON.stringify({ content: "# variables:\n---\n" }),
      });
      setShowNew(false);
      setNewName("");
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell>
      <div className="max-w-4xl space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold text-slate-900">
            Prompts (Operator Defaults)
          </h2>
          <button
            onClick={() => setShowNew(!showNew)}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            {showNew ? "Cancel" : "New prompt"}
          </button>
        </div>

        {showNew && (
          <div className="flex items-center gap-3 bg-white border border-slate-200 rounded-lg p-4">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="prompt_name (lowercase, underscores)"
              className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
              autoFocus
            />
            <button
              onClick={handleCreate}
              disabled={saving || !newName.trim()}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              Create
            </button>
          </div>
        )}

        {msg && !editing && (
          <div
            className={`rounded-lg px-4 py-3 text-sm ${
              msg === "Saved"
                ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                : "bg-red-50 text-red-800 border border-red-200"
            }`}
          >
            {msg}
          </div>
        )}

        {/* Editor */}
        {editing && (
          <div className="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900 font-mono">
                {editing.name}
              </h3>
              <button
                onClick={() => {
                  setEditing(null);
                  setMsg(null);
                }}
                className="text-sm text-slate-500 hover:text-slate-700"
              >
                ✕ Close
              </button>
            </div>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={16}
              className="w-full px-4 py-3 border border-slate-300 rounded-lg text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 resize-y"
            />
            <div className="flex items-center gap-3">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save prompt"}
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
        )}

        {/* List */}
        <div className="space-y-2">
          {prompts.map((p) => (
            <div
              key={p.id}
              onClick={() => startEdit(p)}
              className="flex items-center justify-between bg-white border border-slate-200 rounded-lg px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors"
            >
              <div>
                <span className="font-medium text-sm text-slate-900 font-mono">
                  {p.name}
                </span>
                <span className="ml-4 text-xs text-slate-400 truncate max-w-md inline-block align-middle">
                  {p.content.slice(0, 80)}…
                </span>
              </div>
              <span className="text-xs text-slate-400">
                {new Date(p.updated_at).toLocaleDateString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Shell>
  );
}
