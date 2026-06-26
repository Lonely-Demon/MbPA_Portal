import { useEffect, useState } from "react";
import { client } from "../api/client";
import type { components } from "../api/schema";
import { cn } from "../lib/utils";

type QueueItem = components["schemas"]["OfficerQueueItem"];
type FeeAssessmentRead = components["schemas"]["FeeAssessmentRead"];
type PaymentRead = components["schemas"]["PaymentRead"];
type CertificateRead = components["schemas"]["_Certificate"];
type DocumentSlotRead = components["schemas"]["DocumentSlotRead"];
type ActionEnum = components["schemas"]["ActionEnum"];

function slaBadge(dueAt: string) {
  const now = Date.now();
  const due = new Date(dueAt).getTime();
  const diffMs = due - now;
  const diffDays = diffMs / (1000 * 60 * 60 * 24);
  if (diffMs < 0 || diffDays < 1) {
    return (
      <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700">
        Overdue
      </span>
    );
  }
  if (diffDays <= 3) {
    return (
      <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700">
        Due soon
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700">
      On track
    </span>
  );
}

function fmt(dt: string | null | undefined) {
  if (!dt) return "—";
  return new Date(dt).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

type Tab = "action" | "documents" | "fees" | "certificates";

function MilestoneActionPanel({
  item,
  onSuccess,
}: {
  item: QueueItem;
  onSuccess: () => void;
}) {
  const [action, setAction] = useState<ActionEnum>("approve");
  const [note, setNote] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error: apiError } = await client.POST(
        "/api/applications/{application_number}/milestones/{id}/action/",
        {
          params: {
            path: { application_number: item.application_number, id: item.id },
          },
          body: {
            action,
            decision_note: note,
            correction_reason: action === "return_for_correction" ? correctionReason : "",
          },
        },
      );
      if (apiError) {
        setError("Action failed. Please try again.");
        return;
      }
      onSuccess();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="text-slate">Stream</span>
          <p className="font-medium">{item.stream_name}</p>
        </div>
        <div>
          <span className="text-slate">Milestone</span>
          <p className="font-medium">{item.milestone_name}</p>
        </div>
        <div>
          <span className="text-slate">SLA</span>
          <p className="font-medium">{item.sla_working_days} working days</p>
        </div>
        <div>
          <span className="text-slate">Due</span>
          <p className="font-medium">{fmt(item.due_at)}</p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-harbour mb-1">Action</label>
        <select
          value={action}
          onChange={(e) => setAction(e.target.value as ActionEnum)}
          className="w-full rounded border border-paper-dark px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal"
        >
          <option value="approve">Approve</option>
          <option value="return_for_correction">Return for Correction</option>
          <option value="reject">Reject</option>
        </select>
      </div>

      {action === "return_for_correction" && (
        <div>
          <label className="block text-sm font-medium text-harbour mb-1">
            Correction reason
          </label>
          <textarea
            value={correctionReason}
            onChange={(e) => setCorrectionReason(e.target.value)}
            rows={2}
            className="w-full rounded border border-paper-dark px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal"
          />
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-harbour mb-1">Decision note</label>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          className="w-full rounded border border-paper-dark px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal"
        />
      </div>

      {error && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

      <button
        type="submit"
        disabled={loading}
        className={cn(
          "rounded bg-harbour text-white font-medium py-2 px-5 text-sm",
          "hover:bg-harbour-light transition-colors disabled:opacity-60",
        )}
      >
        {loading ? "Submitting…" : "Submit"}
      </button>
    </form>
  );
}

function DocumentsPanel({ item }: { item: QueueItem }) {
  const [slots, setSlots] = useState<DocumentSlotRead[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    client
      .GET("/api/documents/slots/{milestone_instance_id}/", {
        params: { path: { milestone_instance_id: item.id } },
      })
      .then(({ data }) => {
        setSlots(data ?? []);
        setLoading(false);
      });
  }, [item]);

  if (loading || slots === null) return <p className="text-sm text-slate">Loading…</p>;
  if (slots.length === 0) return <p className="text-sm text-slate">No document requirements for this milestone.</p>;

  return (
    <div className="space-y-2">
      <p className="text-xs text-slate mb-3">
        Required document types for {item.milestone_code}. Count of uploaded files shown in queue badge.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-slate">
            <th className="pb-2 pr-4 font-medium">Document type</th>
            <th className="pb-2 pr-4 font-medium">Required</th>
            <th className="pb-2 font-medium">Condition</th>
          </tr>
        </thead>
        <tbody>
          {slots.map((slot) => (
            <tr key={slot.id} className="border-b last:border-0">
              <td className="py-2 pr-4 font-medium">{slot.document_type}</td>
              <td className="py-2 pr-4">
                {slot.is_mandatory ? (
                  <span className="text-xs text-red-600 font-medium">Mandatory</span>
                ) : (
                  <span className="text-xs text-slate">Optional</span>
                )}
              </td>
              <td className="py-2 text-xs text-slate">{slot.applies_when ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FeesPanel({ item }: { item: QueueItem }) {
  const [assessment, setAssessment] = useState<FeeAssessmentRead | null>(null);
  const [payments, setPayments] = useState<PaymentRead[]>([]);
  const [verifyId, setVerifyId] = useState<number | null>(null);
  const [decision, setDecision] = useState<"verified" | "rejected" | "mismatch">("verified");
  const [verifyRemarks, setVerifyRemarks] = useState("");
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .GET("/api/fees/{application_number}/assessment/", {
        params: { path: { application_number: item.application_number } },
      })
      .then(({ data }) => data && setAssessment(data));
    client
      .GET("/api/fees/{application_number}/payments/", {
        params: { path: { application_number: item.application_number } },
      })
      .then(({ data }) => data && setPayments(data));
  }, [item]);

  async function submitVerify(e: React.FormEvent) {
    e.preventDefault();
    if (verifyId === null) return;
    setError(null);
    setVerifyLoading(true);
    try {
      const { error: apiError } = await client.PATCH(
        "/api/fees/{application_number}/payments/{id}/verify/",
        {
          params: { path: { application_number: item.application_number, id: verifyId } },
          body: { decision, remarks: verifyRemarks },
        },
      );
      if (apiError) {
        setError("Verification failed.");
        return;
      }
      const { data } = await client.GET("/api/fees/{application_number}/payments/", {
        params: { path: { application_number: item.application_number } },
      });
      if (data) setPayments(data);
      setVerifyId(null);
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setVerifyLoading(false);
    }
  }

  if (!assessment) return <p className="text-sm text-slate">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm bg-paper rounded p-3">
        <div>
          <span className="text-slate block">Scrutiny fee</span>
          <span className="font-medium">₹{assessment.scrutiny_fee}</span>
        </div>
        <div>
          <span className="text-slate block">Security deposit</span>
          <span className="font-medium">₹{assessment.security_deposit}</span>
        </div>
        <div>
          <span className="text-slate block">Debris deposit</span>
          <span className="font-medium">₹{assessment.debris_deposit}</span>
        </div>
        {assessment.premium_total && (
          <div>
            <span className="text-slate block">Premium total</span>
            <span className="font-medium">₹{assessment.premium_total}</span>
          </div>
        )}
        <div className="col-span-2 border-t pt-2">
          <span className="text-slate block">Total</span>
          <span className="font-semibold text-harbour">₹{assessment.total_amount}</span>
        </div>
      </div>

      {payments.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-harbour mb-2">Payments</h4>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-slate">
                <th className="pb-1 pr-3 font-medium">Challan</th>
                <th className="pb-1 pr-3 font-medium">Claimed</th>
                <th className="pb-1 pr-3 font-medium">Status</th>
                <th className="pb-1 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id} className="border-b last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-xs">{p.challan_reference}</td>
                  <td className="py-1.5 pr-3">₹{p.claimed_amount}</td>
                  <td className="py-1.5 pr-3">
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-xs font-medium",
                        p.status === "verified"
                          ? "bg-green-100 text-green-700"
                          : p.status === "claimed"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-red-100 text-red-700",
                      )}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td className="py-1.5">
                    {p.status === "claimed" && (
                      <button
                        onClick={() => setVerifyId(p.id)}
                        className="text-teal hover:underline text-xs"
                      >
                        Verify
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {verifyId !== null && (
        <form onSubmit={submitVerify} className="space-y-3 border-t pt-3">
          <h4 className="text-sm font-medium text-harbour">Verify Payment</h4>
          <div>
            <label className="block text-sm font-medium text-harbour mb-1">Decision</label>
            <select
              value={decision}
              onChange={(e) =>
                setDecision(e.target.value as "verified" | "rejected" | "mismatch")
              }
              className="rounded border border-paper-dark px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal"
            >
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
              <option value="mismatch">Amount Mismatch</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-harbour mb-1">Remarks</label>
            <input
              type="text"
              value={verifyRemarks}
              onChange={(e) => setVerifyRemarks(e.target.value)}
              className="w-full rounded border border-paper-dark px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={verifyLoading}
              className="rounded bg-harbour text-white font-medium py-1.5 px-4 text-sm hover:bg-harbour-light disabled:opacity-60"
            >
              {verifyLoading ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setVerifyId(null)}
              className="rounded border border-paper-dark py-1.5 px-4 text-sm hover:bg-paper"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function CertificatesPanel({ item }: { item: QueueItem }) {
  const [certs, setCerts] = useState<CertificateRead[] | null>(null);
  const [uploadingId, setUploadingId] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadLoading, setUploadLoading] = useState(false);

  useEffect(() => {
    client
      .GET("/api/certificates/{application_number}/", {
        params: { path: { application_number: item.application_number } },
      })
      .then(({ data }) => data && setCerts(data));
  }, [item]);

  async function download(certId: number) {
    const { data } = await client.GET(
      "/api/certificates/{application_number}/{id}/download/",
      {
        params: { path: { application_number: item.application_number, id: certId } },
      },
    );
    if (data?.url) window.open(data.url, "_blank", "noopener");
  }

  async function uploadSigned(certId: number, file: File) {
    setUploadError(null);
    setUploadLoading(true);
    try {
      const formData = new FormData();
      formData.append("signed_pdf", file);
      const res = await fetch(
        `/api/certificates/${item.application_number}/${certId}/receive-signed/`,
        {
          method: "POST",
          body: formData,
          headers: {
            "X-CSRFToken":
              document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ?? "",
          },
        },
      );
      if (!res.ok) {
        setUploadError("Upload failed.");
        return;
      }
      const { data } = await client.GET("/api/certificates/{application_number}/", {
        params: { path: { application_number: item.application_number } },
      });
      if (data) setCerts(data);
      setUploadingId(null);
    } catch {
      setUploadError("An unexpected error occurred.");
    } finally {
      setUploadLoading(false);
    }
  }

  if (!certs) return <p className="text-sm text-slate">Loading…</p>;
  if (certs.length === 0) return <p className="text-sm text-slate">No certificates issued.</p>;

  return (
    <div className="space-y-3">
      {certs.map((cert) => (
        <div key={cert.id} className="rounded border border-paper-dark p-3 text-sm space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{cert.certificate_number}</span>
            <span className="text-xs text-slate">{cert.certificate_type}</span>
          </div>
          <p className="text-slate text-xs">Issued: {fmt(cert.issued_at)}</p>
          {cert.valid_until && (
            <p className="text-slate text-xs">Valid until: {fmt(cert.valid_until)}</p>
          )}
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => download(cert.id)}
              className="text-teal hover:underline text-xs"
            >
              Download
            </button>
            {uploadingId === cert.id ? (
              <label className="text-xs cursor-pointer text-harbour hover:underline">
                {uploadLoading ? "Uploading…" : "Choose file"}
                <input
                  type="file"
                  accept=".pdf"
                  className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadSigned(cert.id, f);
                  }}
                />
              </label>
            ) : (
              <button
                onClick={() => setUploadingId(cert.id)}
                className="text-xs text-harbour hover:underline"
              >
                Upload Signed PDF
              </button>
            )}
          </div>
          {uploadError && uploadingId === cert.id && (
            <p className="text-xs text-red-600">{uploadError}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function DetailPanel({
  item,
  onActionSuccess,
}: {
  item: QueueItem;
  onActionSuccess: () => void;
}) {
  const [tab, setTab] = useState<Tab>("action");
  const tabs: { id: Tab; label: string }[] = [
    { id: "action", label: "Milestone Action" },
    { id: "documents", label: "Documents" },
    { id: "fees", label: "Fee Assessment" },
    { id: "certificates", label: "Certificates" },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="border-b flex gap-1 px-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.id
                ? "border-teal text-teal"
                : "border-transparent text-slate hover:text-harbour",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {tab === "action" && (
          <MilestoneActionPanel item={item} onSuccess={onActionSuccess} />
        )}
        {tab === "documents" && <DocumentsPanel item={item} />}
        {tab === "fees" && <FeesPanel item={item} />}
        {tab === "certificates" && <CertificatesPanel item={item} />}
      </div>
    </div>
  );
}

export default function OfficerDashboard() {
  const [queue, setQueue] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<QueueItem | null>(null);

  async function fetchQueue() {
    const { data, error: apiError } = await client.GET("/api/officer/queue/");
    if (apiError) {
      setError("Failed to load queue.");
      return;
    }
    setQueue(data ?? []);
  }

  useEffect(() => {
    fetchQueue();
  }, []);

  function handleActionSuccess() {
    setSelected(null);
    fetchQueue();
  }

  return (
    <div className="min-h-screen bg-paper">
      <header className="bg-harbour text-white px-6 py-3 flex items-center gap-4">
        <h1 className="text-lg font-bold">MbPA Officer Console</h1>
      </header>

      <div className="flex h-[calc(100vh-52px)]">
        {/* Left panel — Review Queue */}
        <div className="w-full lg:w-96 border-r border-paper-dark bg-white overflow-y-auto flex-shrink-0">
          <div className="px-4 py-3 border-b border-paper-dark">
            <h2 className="font-semibold text-harbour">Review Queue</h2>
          </div>

          {error && (
            <p className="m-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
          )}

          {queue === null && (
            <p className="p-4 text-sm text-slate">Loading…</p>
          )}

          {queue !== null && queue.length === 0 && (
            <p className="p-4 text-sm text-slate">No items in queue.</p>
          )}

          {queue !== null && queue.length > 0 && (
            <ul>
              {queue.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => setSelected(item)}
                    className={cn(
                      "w-full text-left px-4 py-3 border-b border-paper-dark hover:bg-paper transition-colors",
                      selected?.id === item.id && "bg-paper",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-xs font-mono text-slate">
                        {item.application_number}
                      </span>
                      {slaBadge(item.due_at)}
                    </div>
                    <p className="text-sm font-medium text-harbour truncate">
                      {item.milestone_name}
                    </p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-xs text-slate">{item.stream_name}</span>
                      <span className="text-xs text-slate">Due {fmt(item.due_at)}</span>
                      {item.document_count > 0 && (
                        <span className="text-xs bg-brass/20 text-harbour rounded-full px-2 py-0.5">
                          {item.document_count} doc{item.document_count !== 1 ? "s" : ""}
                        </span>
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Right panel — Application Detail */}
        <div className="flex-1 bg-white overflow-hidden">
          {selected === null ? (
            <div className="flex items-center justify-center h-full text-slate text-sm">
              Select an item from the queue to review.
            </div>
          ) : (
            <div className="flex flex-col h-full">
              <div className="px-6 py-3 border-b border-paper-dark bg-paper/50 flex items-center gap-3">
                <div>
                  <span className="text-xs font-mono text-slate">
                    {selected.application_number}
                  </span>
                  <h3 className="font-semibold text-harbour">{selected.milestone_name}</h3>
                </div>
                <div className="ml-auto">{slaBadge(selected.due_at)}</div>
              </div>
              <div className="flex-1 overflow-hidden">
                <DetailPanel item={selected} onActionSuccess={handleActionSuccess} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
