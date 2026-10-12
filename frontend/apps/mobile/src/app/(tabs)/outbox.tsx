import { SYNC_STATUS, copy, formatDateTime, formatRelative } from "@vtrs/core";
import { Inbox } from "lucide-react-native";
import { FlatList, RefreshControl, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { OutboxEntry } from "../../core/outbox";
import { useApp } from "../../state/app";
import { Button, IconBadge, OfflineBanner, StatusChip } from "../../ui/kit";
import { AppText, radius, size, space, useColors } from "../../ui/theme";

function photoLine(entry: OutboxEntry): string | null {
  if (entry.evidence === "NONE") return null;
  if (entry.evidence === "COMPLETE") return "Photo sent";
  if (entry.evidence === "FAILED") return "Photo not sent. Tap Try again.";
  return entry.status === "SYNCED" || entry.status === "REQUIRES_REVIEW"
    ? "Photo is still sending"
    : "Photo waits with the result";
}

/** Every result on this phone and where it is: waiting, sending, sent, or needing a second look. */
export default function Outbox() {
  const { outbox, online, pending, syncNow, retryFailed, syncing } = useApp();
  const colors = useColors();
  const hasFailed = outbox.some((o) => o.status === "FAILED" || o.evidence === "FAILED");

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: colors.canvas }}
      edges={["top", "left", "right"]}
    >
      <FlatList
        data={outbox}
        keyExtractor={(item) => item.versionId}
        contentContainerStyle={{ padding: size.screenPadding, gap: space[12] }}
        refreshControl={<RefreshControl refreshing={syncing} onRefresh={() => void syncNow()} />}
        ListHeaderComponent={
          <View style={{ gap: space[12], marginBottom: space[4] }}>
            <AppText variant="display">Outbox</AppText>
            <OfflineBanner online={online} sending={pending} />
            {pending > 0 ? (
              <Button
                title={hasFailed ? "Try again" : "Send all"}
                variant={hasFailed ? "primary" : "secondary"}
                loading={syncing}
                disabled={!online}
                onPress={() => void (hasFailed ? retryFailed() : syncNow())}
              />
            ) : null}
          </View>
        }
        ListEmptyComponent={
          <View
            style={{
              backgroundColor: colors.card,
              borderRadius: radius.card,
              padding: space[24],
              gap: space[12],
              borderWidth: 1,
              borderColor: colors.border,
            }}
          >
            <IconBadge>
              <Inbox size={28} color="#FFFFFF" strokeWidth={1.75} />
            </IconBadge>
            <AppText variant="heading">Nothing sent yet</AppText>
            <AppText variant="body" tone="subtle">
              Results you record appear here with their status. Pull down to check for updates.
            </AppText>
          </View>
        }
        renderItem={({ item }) => {
          const photo = photoLine(item);
          const status =
            item.serverState === "REJECTED"
              ? { label: "Sent back for correction", tone: "red" as const, icon: "alert-circle" }
              : item.serverState === "APPROVED"
                ? { label: "Approved", tone: "teal" as const, icon: "check-circle-2" }
                : SYNC_STATUS[item.status];
          return (
            <View
              accessible
              accessibilityLabel={`${item.contestTitle}, ${item.puName}. ${status.label}.`}
              style={{
                backgroundColor: colors.card,
                borderRadius: radius.card,
                padding: space[16],
                gap: space[8],
                borderWidth: 1,
                borderColor: colors.border,
              }}
            >
              <View
                style={{ flexDirection: "row", justifyContent: "space-between", gap: space[8] }}
              >
                <View style={{ flex: 1 }}>
                  <AppText variant="heading">{item.contestTitle}</AppText>
                  <AppText variant="body" tone="subtle">
                    {item.puName} · {item.ward}
                  </AppText>
                </View>
                <StatusChip status={status} />
              </View>
              <AppText variant="caption" tone="muted">
                Recorded {formatDateTime(item.createdAt)}
                {item.versionNo ? ` · version ${item.versionNo}` : ""}
                {item.sentAt ? ` · sent ${formatRelative(item.sentAt)}` : ""}
              </AppText>
              {photo ? (
                <AppText variant="caption" tone="subtle">
                  {photo}
                </AppText>
              ) : null}
              {item.status === "REQUIRES_REVIEW" ? (
                <AppText variant="body" tone="subtle">
                  An officer will check one thing. You do not need to do anything.
                </AppText>
              ) : null}
              {item.serverState === "REJECTED" && item.reviewReason ? (
                <AppText variant="body" tone="danger">
                  {item.reviewReason}
                </AppText>
              ) : null}
              {item.status === "FAILED" ? (
                <AppText variant="body" tone="danger">
                  {item.lastError ?? copy.failedSend.body}
                </AppText>
              ) : item.status === "PENDING" && item.lastError ? (
                <AppText variant="caption" tone="subtle">
                  {copy.failedSend.line}
                </AppText>
              ) : null}
            </View>
          );
        }}
      />
    </SafeAreaView>
  );
}
