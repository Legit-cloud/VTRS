"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, formatNumber, formatPercent, type MessagingChannel } from "@vtrs/core";
import { Mail, MessageSquare } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Select } from "@/components/ui/field";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { useStepUp } from "@/lib/step-up";

const LABEL: Record<string, string> = {
  SMS: "SMS",
  EMAIL: "Email",
  PUSH: "Push notifications",
  WHATSAPP: "WhatsApp",
  IN_APP: "In the portal",
};

export default function Messaging() {
  const stepUp = useStepUp();
  const [hours, setHours] = useState(24);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const stats = useQuery({
    queryKey: ["platform", "messaging", hours],
    queryFn: () => ep.platform.messaging(hours),
    refetchInterval: 30_000,
  });

  const test = useMutation({
    mutationFn: (channel: "SMS" | "EMAIL") => stepUp(() => ep.platform.testMessage(channel)),
    onSuccess: (r) => setResult({ ok: true, text: `Sent to ${r.sent_to}. Check that it arrives.` }),
    onError: (e) =>
      setResult({
        ok: false,
        text: e instanceof ApiError ? e.detail : "The provider did not accept the message.",
      }),
  });

  return (
    <>
      <PageHeader
        title="Messaging providers"
        description="Do codes and alerts get delivered? Rates are for messages the platform tried to send in the window."
      />
      <div className="flex flex-col gap-6">
        <div>
          <Field label="Window" className="w-48">
            {(p) => (
              <Select {...p} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                <option value={1}>Last hour</option>
                <option value={24}>Last 24 hours</option>
                <option value={72}>Last 3 days</option>
                <option value={168}>Last 7 days</option>
              </Select>
            )}
          </Field>
        </div>

        {stats.isError ? (
          <QueryError error={stats.error} onRetry={() => void stats.refetch()} />
        ) : stats.isLoading ? (
          <Skeleton className="h-64" />
        ) : (
          <DataTable<MessagingChannel>
            caption="Delivery by channel"
            rows={stats.data!.channels}
            rowKey={(c) => c.channel}
            columns={[
              {
                key: "channel",
                header: "Channel",
                cell: (c) => <span className="font-semibold">{LABEL[c.channel] ?? c.channel}</span>,
              },
              {
                key: "provider",
                header: "Provider",
                cell: (c) => <span className="mono">{c.provider}</span>,
              },
              {
                key: "attempted",
                header: "Attempted",
                numeric: true,
                cell: (c) => formatNumber(c.attempted),
              },
              { key: "sent", header: "Accepted", numeric: true, cell: (c) => formatNumber(c.sent) },
              {
                key: "delivered",
                header: "Confirmed",
                numeric: true,
                cell: (c) => formatNumber(c.delivered),
              },
              {
                key: "failed",
                header: "Failed",
                numeric: true,
                cell: (c) =>
                  c.failed > 0 ? (
                    <span className="font-semibold text-signal-red-text">
                      {formatNumber(c.failed)}
                    </span>
                  ) : (
                    "0"
                  ),
              },
              {
                key: "rate",
                header: "Success",
                numeric: true,
                cell: (c) => (c.success_pct === null ? "–" : formatPercent(c.success_pct)),
              },
            ]}
            empty={null}
          />
        )}

        <Card>
          <CardHeader
            title="Test a provider"
            description="Sends one message to your own phone or email through the live provider, the same way real codes go out. Needs your authenticator code."
          />
          <div className="flex flex-col gap-4 p-5 pt-2">
            <div className="flex flex-wrap gap-3">
              <Button
                variant="secondary"
                leading={<MessageSquare className="h-4 w-4" aria-hidden />}
                loading={test.isPending && test.variables === "SMS"}
                onClick={() => test.mutate("SMS")}
              >
                Send a test SMS
              </Button>
              <Button
                variant="secondary"
                leading={<Mail className="h-4 w-4" aria-hidden />}
                loading={test.isPending && test.variables === "EMAIL"}
                onClick={() => test.mutate("EMAIL")}
              >
                Send a test email
              </Button>
            </div>
            {result ? (
              <InlineAlert
                tone={result.ok ? "success" : "danger"}
                title={result.ok ? "Message sent" : "Not sent"}
              >
                {result.text}
              </InlineAlert>
            ) : null}
          </div>
        </Card>
      </div>
    </>
  );
}
