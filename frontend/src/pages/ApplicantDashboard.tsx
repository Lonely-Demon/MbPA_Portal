import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { client } from "../api/client";
import type { components } from "../api/schema";
import { api } from "../lib/api";
import { cn } from "../lib/utils";

type ApplicationRead = components["schemas"]["ApplicationRead"];
type StatusLookupResponse = components["schemas"]["StatusLookupResponse"];
type StatusMilestoneItem = components["schemas"]["StatusMilestoneItem"];
type DocumentSlotRead = components["schemas"]["DocumentSlotRead"];
type FeeAssessmentRead = components["schemas"]["FeeAssessmentRead"];
type PaymentRead = components["schemas"]["PaymentRead"];

function getCsrf() {
  return document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ?? "";
}

function fmt(v: string | null | undefined) {
  if (!v) return "—";
  return `₹${parseFloat(v).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    draft: "bg-paper-dark text-slate",
    submitted: "bg-amber-100 text-amber-700",
    in_progress: "bg-blue-100 text-blue-700",
    approved: "bg-teal/10 text-teal",
    rejected: "bg-red-100 text-red-600",
    withdrawn: "bg-slate/10 text-slate",
  };
  return cn(
    "text-xs rounded px-2 py-0.5 font-medium",
    map[status] ?? "bg-paper-dark text-slate",
  );
}

function MilestoneStrip({ milestones }: { milestones: StatusMilestoneItem[] }) {
  return (
    <ol className="space-y-2">
      {milestones.map((m) => (
        <li key={m.code} className="flex items-start gap-3 text-sm">
          <span
            className={cn(
              "mt-0.5 w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center text-xs",
              m.status === "completed" && "bg-teal text-white",
              m.status === "in_progress" && "bg-amber-400 text-white",
              m.status === "pending" && "bg-paper-dark text-slate",
            )}
          >
            {m.status === "completed" ? "✓" : m.sequence}
          </span>
          <div className="flex-1">
            <span
              className={cn(
                m.status === "completed" && "text-harbour",
                m.status === "in_progress" && "font-medium text-harbour",
                m.status === "pending" && "text-slate",
              )}
            >
              {m.name}
            </span>
            {m.completed_at && (
              <span className="block text-xs text-slate">
                {new Date(m.completed_at).toLocaleDateString("en-IN")}
              </span>
            )}
          </div>
          {m.is_deemed && (
            <span className="text-xs bg-teal/10 text-teal rounded px-1.5 py-0.5 flex-shrink-0">
              Deemed
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

interface DetailPanelProps {
  app: ApplicationRead;
}

function DetailPanel({ app }: DetailPanelProps) {
  const [tab, setTab] = useState<"timeline" | "docs" | "fees">("timeline");
  const [status, setStatus] = useState<StatusLookupResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [docSlots, setDocSlots] = useState<DocumentSlotRead[] | null>(null);
  const [uploadingSlot, setUploadingSlot] = useState<number | null>(null);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<FeeAssessmentRead | null>(null);
  const [payments, setPayments] = useState<PaymentRead[]>([]);
  const [feesLoading, setFeesLoading] = useState(false);
  const [payForm, setPayForm] = useState({ challan_reference: "", claimed_amount: "", payment_date: "" });
  const [paySubmitting, setPaySubmitting] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  const hasNumber = !!app.application_number;

  const activeMilestoneId = status?.milestones?.find((m) => m.status === "in_progress") as
    | (StatusMilestoneItem & { id?: number })
    | undefined;

  useEffect(() => {
    if (tab === "timeline" && hasNumber && !status) {
      setStatusLoading(true);
      api<StatusLookupResponse>(
        `/api/applications/status/?application_number=${encodeURIComponent(app.application_number)}`,
      )
        .then(setStatus)
        .catch(() => {})
        .finally(() => setStatusLoading(false));
    }
  }, [tab, hasNumber, status, app.application_number]);

  useEffect(() => {
    if (tab === "fees" && hasNumber && !assessment && !feesLoading) {
      setFeesLoading(true);
      Promise.all([
        client.GET("/api/fees/{application_number}/assessment/", {
          params: { path: { application_number: app.application_number } },
        }),
        client.GET("/api/fees/{application_number}/payments/", {
          params: { path: { application_number: app.application_number } },
        }),
      ])
        .then(([aRes, pRes]) => {
          if (aRes.data) setAssessment(aRes.data);
          if (pRes.data) setPayments(pRes.data);
        })
        .catch(() => {})
        .finally(() => setFeesLoading(false));
    }
  }, [tab, hasNumber, assessment, feesLoading, app.application_number]);

  async function loadDocSlots(milestoneInstanceId: number) {
    const { data } = await client.GET("/api/documents/slots/{milestone_instance_id}/", {
      params: { path: { milestone_instance_id: milestoneInstanceId } },
    });
    if (data) setDocSlots(data);
  }

  useEffect(() => {
    if (tab === "docs" && status) {
      const active = status.milestones?.find((m) => m.status === "in_progress") as
        | (StatusMilestoneItem & { id?: number })
        | undefined;
      if (active?.id && docSlots === null) {
        loadDocSlots(active.id);
      }
    }
  }, [tab, status, docSlots]);

  async function handleUpload(slotId: number, file: File, milestoneInstanceId: number) {
    setUploadingSlot(slotId);
    setUploadMsg(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("document_slot_id", String(slotId));
      fd.append("milestone_instance_id", String(milestoneInstanceId));
      const res = await fetch("/api/documents/upload/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrf() },
        credentials: "include",
        body: fd,
      });
      if (res.ok) {
        setUploadMsg("File uploaded successfully.");
      } else {
        setUploadMsg("Upload failed. Please try again.");
      }
    } catch {
      setUploadMsg("Upload failed.");
    } finally {
      setUploadingSlot(null);
    }
  }

  async function handlePaymentRecord(e: React.FormEvent) {
    e.preventDefault();
    setPayError(null);
    setPaySubmitting(true);
    try {
      const { data, error } = await client.POST(
        "/api/fees/{application_number}/payments/record/",
        {
          params: { path: { application_number: app.application_number } },
          body: payForm,
        },
      );
      if (error || !data) {
        setPayError("Could not record payment. Check your details.");
        return;
      }
      setPayments((prev) => [...prev, data]);
      setPayForm({ challan_reference: "", claimed_amount: "", payment_date: "" });
    } catch {
      setPayError("An unexpected error occurred.");
    } finally {
      setPaySubmitting(false);
    }
  }

  const tabs: { key: typeof tab; label: string }[] = [
    { key: "timeline", label: "Status" },
    { key: "docs", label: "Documents" },
    { key: "fees", label: "Fee & Payment" },
  ];

  return (
    <div className="border-t border-paper-dark">
      {/* Tab bar */}
      <div className="flex border-b border-paper-dark">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "px-4 py-2 text-sm font-medium",
              tab === t.key
                ? "border-b-2 border-teal text-teal"
                : "text-slate hover:text-harbour",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="p-4">
        {/* Timeline tab */}
        {tab === "timeline" && (
          <>
            {!hasNumber && (
              <p className="text-sm text-slate">
                This application is still a draft. Submit it to track milestone progress.
              </p>
            )}
            {hasNumber && statusLoading && <p className="text-sm text-slate">Loading…</p>}
            {hasNumber && status && <MilestoneStrip milestones={status.milestones} />}
          </>
        )}

        {/* Documents tab */}
        {tab === "docs" && (
          <>
            {!hasNumber && (
              <p className="text-sm text-slate">Documents can be uploaded after submission.</p>
            )}
            {hasNumber && !status && (
              <p className="text-sm text-slate">
                Loading status to find active milestone…
              </p>
            )}
            {hasNumber && status && !activeMilestoneId && (
              <p className="text-sm text-slate">No active milestone to upload documents for.</p>
            )}
            {hasNumber && status && activeMilestoneId?.id && (
              <>
                {uploadMsg && (
                  <p className="text-sm text-teal mb-3">{uploadMsg}</p>
                )}
                {!docSlots && <p className="text-sm text-slate">Loading document slots…</p>}
                {docSlots && docSlots.length === 0 && (
                  <p className="text-sm text-slate">No document slots defined for this milestone.</p>
                )}
                {docSlots && docSlots.length > 0 && (
                  <ul className="space-y-3">
                    {docSlots.map((slot) => (
                      <li key={slot.id} className="text-sm">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium text-harbour">{slot.document_type}</span>
                          {slot.is_mandatory && (
                            <span className="text-xs text-red-500">Required</span>
                          )}
                        </div>
                        <input
                          type="file"
                          disabled={uploadingSlot === slot.id}
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file && activeMilestoneId.id) {
                              handleUpload(slot.id, file, activeMilestoneId.id);
                            }
                          }}
                          className="block text-xs text-slate"
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </>
        )}

        {/* Fee & Payment tab */}
        {tab === "fees" && (
          <>
            {!hasNumber && (
              <p className="text-sm text-slate">Fee assessment is available after submission.</p>
            )}
            {hasNumber && feesLoading && <p className="text-sm text-slate">Loading…</p>}
            {hasNumber && !feesLoading && !assessment && (
              <p className="text-sm text-slate">No fee assessment found for this application.</p>
            )}
            {hasNumber && assessment && (
              <div className="space-y-4">
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate">Scrutiny fee</span>
                    <span>{fmt(assessment.scrutiny_fee)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate">Security deposit</span>
                    <span>{fmt(assessment.security_deposit)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate">Debris deposit</span>
                    <span>{fmt(assessment.debris_deposit)}</span>
                  </div>
                  {assessment.premium_total && parseFloat(assessment.premium_total) > 0 && (
                    <div className="flex justify-between">
                      <span className="text-slate">Premium total</span>
                      <span>{fmt(assessment.premium_total)}</span>
                    </div>
                  )}
                  <div className="flex justify-between font-semibold border-t pt-1 text-harbour">
                    <span>Total</span>
                    <span>{fmt(assessment.total_amount)}</span>
                  </div>
                </div>

                {payments.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-harbour mb-2">Payments</h4>
                    <ul className="space-y-1 text-xs">
                      {payments.map((p) => (
                        <li key={p.id} className="flex justify-between">
                          <span className="text-slate">{p.challan_reference}</span>
                          <span>{fmt(p.claimed_amount)}</span>
                          <span
                            className={cn(
                              "rounded px-1.5",
                              p.status === "verified" && "bg-teal/10 text-teal",
                              p.status === "claimed" && "bg-amber-100 text-amber-700",
                              p.status === "rejected" && "bg-red-100 text-red-600",
                            )}
                          >
                            {p.status ?? "claimed"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <h4 className="text-sm font-medium text-harbour mb-2">Record a Payment</h4>
                  {payError && (
                    <p className="text-xs text-red-600 mb-2">{payError}</p>
                  )}
                  <form onSubmit={handlePaymentRecord} className="space-y-2">
                    <input
                      type="text"
                      placeholder="Challan reference"
                      value={payForm.challan_reference}
                      onChange={(e) => setPayForm((f) => ({ ...f, challan_reference: e.target.value }))}
                      required
                      className="w-full rounded border border-paper-dark px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-teal"
                    />
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      placeholder="Amount (₹)"
                      value={payForm.claimed_amount}
                      onChange={(e) => setPayForm((f) => ({ ...f, claimed_amount: e.target.value }))}
                      required
                      className="w-full rounded border border-paper-dark px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-teal"
                    />
                    <input
                      type="date"
                      value={payForm.payment_date}
                      onChange={(e) => setPayForm((f) => ({ ...f, payment_date: e.target.value }))}
                      required
                      className="w-full rounded border border-paper-dark px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-teal"
                    />
                    <button
                      type="submit"
                      disabled={paySubmitting}
                      className="rounded bg-teal text-white text-xs py-1.5 px-4 hover:bg-teal-light transition-colors disabled:opacity-60"
                    >
                      {paySubmitting ? "Recording…" : "Record Payment"}
                    </button>
                  </form>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function ApplicantDashboard() {
  const navigate = useNavigate();
  const [apps, setApps] = useState<ApplicationRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      const { error: meError } = await client.GET("/api/identity/me/");
      if (meError) {
        navigate("/");
        return;
      }
      const { data } = await client.GET("/api/applications/");
      if (data) setApps(data);
      setLoading(false);
    }
    load();
  }, [navigate]);

  function toggle(id: number) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center">
        <p className="text-slate text-sm">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-paper">
      <header className="bg-harbour text-white px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">My Applications</h1>
          <p className="text-xs text-white/70 mt-0.5">MbPA Building Permission Portal</p>
        </div>
        <a href="/planner" className="text-xs text-white/70 hover:text-white underline">
          Fee Planner
        </a>
      </header>

      <div className="max-w-3xl mx-auto p-6 space-y-4">
        {apps.length === 0 && (
          <div className="bg-white rounded-lg shadow-sm p-8 text-center">
            <p className="text-slate text-sm mb-3">You have no applications yet.</p>
            <a
              href="/signup"
              className="inline-block rounded bg-teal text-white text-sm font-medium py-2 px-5 hover:bg-teal-light transition-colors"
            >
              Start a new application
            </a>
          </div>
        )}

        {apps.map((app) => (
          <div key={app.id} className="bg-white rounded-lg shadow-sm overflow-hidden">
            <button
              onClick={() => toggle(app.id)}
              className="w-full text-left px-5 py-4 flex items-center justify-between hover:bg-paper/50 transition-colors"
            >
              <div>
                <div className="flex items-center gap-3">
                  <span className="font-mono font-semibold text-harbour">
                    {app.application_number || "Draft"}
                  </span>
                  <span className={statusBadge(app.status)}>
                    {app.status.replace(/_/g, " ")}
                  </span>
                </div>
                <div className="text-sm text-slate mt-0.5">
                  {app.stream_name}
                  {app.submitted_at && (
                    <span className="ml-2">
                      · {new Date(app.submitted_at).toLocaleDateString("en-IN")}
                    </span>
                  )}
                </div>
              </div>
              <span className="text-slate text-lg">{expandedId === app.id ? "▲" : "▼"}</span>
            </button>

            {expandedId === app.id && <DetailPanel app={app} />}
          </div>
        ))}
      </div>
    </div>
  );
}
