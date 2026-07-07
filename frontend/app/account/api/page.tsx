"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useApiKeys, useCreateApiKey, useRevokeApiKey, useKeyUsage } from "@/lib/api/apikeys";
import { API_BASE } from "@/lib/api/client";

export default function ApiKeysPage() {
  const { token, user, openAuth } = useAuth();
  const loggedIn = !!token;
  const keys = useApiKeys(loggedIn);
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const [name, setName] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const usage = useKeyUsage(selectedKey);
  const [justCreated, setJustCreated] = useState<string | null>(null);

  if (!loggedIn) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 font-medium text-ink">Sign in to manage API keys.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
          Sign In →
        </button>
      </div>
    );
  }

  if (user && !["fmcg", "insurance"].includes(user.tier)) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center text-provenance">
        API access requires an FMCG or Insurance tier account.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">API Keys</h1>
      <p className="mb-6 text-provenance">
        Base URL: <code className="rounded bg-porcelain px-1.5 py-0.5 font-mono text-xs">{API_BASE}</code> · Auth via{" "}
        <code className="rounded bg-porcelain px-1.5 py-0.5 font-mono text-xs">X-API-Key</code> header.
      </p>

      <div className="mb-8 flex gap-3">
        <input
          className="flex-1 rounded-lg border border-line bg-slab px-3 py-2 text-sm"
          placeholder="Key name (e.g. Production)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          type="button"
          disabled={create.isPending}
          onClick={() =>
            create.mutate(name, {
              onSuccess: (r) => {
                setJustCreated(r.key);
                setName("");
              },
            })
          }
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink disabled:opacity-60"
        >
          {create.isPending ? "Creating…" : "Create new key"}
        </button>
      </div>

      {justCreated && (
        <div className="mb-8 rounded-lg border border-caution bg-caution-pale p-4">
          <p className="mb-2 text-sm font-medium text-caution">
            Your new key: this is the only time it will be shown.
          </p>
          <code className="register block overflow-x-auto rounded bg-slab p-2 text-xs">{justCreated}</code>
        </div>
      )}

      {keys.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : !keys.data || keys.data.length === 0 ? (
        <p className="text-provenance">No API keys yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-porcelain text-left text-xs uppercase tracking-wide text-provenance">
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Prefix</th>
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Last Used</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {keys.data.map((k) => (
                <tr key={k.id} className="border-t border-line">
                  <td className="px-3 py-2">{k.name || "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{k.key_prefix}…</td>
                  <td className="px-3 py-2 font-mono text-xs">{k.created_at.slice(0, 10)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{k.last_used ? k.last_used.slice(0, 10) : "never"}</td>
                  <td className="px-3 py-2">
                    {k.revoked ? <span className="text-risk">Revoked</span> : <span className="text-clear">Active</span>}
                  </td>
                  <td className="px-3 py-2">
                    <button type="button" className="mr-2 text-xs text-ink underline" onClick={() => setSelectedKey(k.id)}>
                      Usage
                    </button>
                    {!k.revoked && (
                      <button type="button" className="text-xs text-risk underline" onClick={() => revoke.mutate(k.id)}>
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedKey && (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-medium">Usage (last 30 days)</h2>
          {usage.isLoading ? (
            <p className="text-sm text-provenance">Loading…</p>
          ) : !usage.data || usage.data.length === 0 ? (
            <p className="text-sm text-provenance">No calls recorded yet.</p>
          ) : (
            <div className="flex items-end gap-1">
              {usage.data.map((d) => (
                <div key={d.day} title={`${d.day}: ${d.calls} calls`} className="flex-1">
                  <div className="rounded-t bg-ink" style={{ height: `${Math.min(80, d.calls * 4)}px` }} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
