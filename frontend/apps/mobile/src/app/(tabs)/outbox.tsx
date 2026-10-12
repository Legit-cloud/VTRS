import { SYNC_STATUS, formatDateTime, formatRelative } from "@vtrs/core";
import { Inbox } from "lucide-react-native";
import { FlatList, RefreshControl, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { OutboxEntry } from "../../core/outbox";
import { useT } from "../../i18n";
import { useApp } from "../../state/app";
import { Button, IconBadge, OfflineBanner, StatusChip } from "../../ui/kit";
import { AppText, radius, size, space, useColors } from "../../ui/theme";

/** Every result on this phone and where it is: waiting, sending, sent, or needing a second look. */
export default function Outbox() {
  const { outbox, online, pending, syncNow, retryFailed, syncing } = useApp();
  const colors = useColors();
  const t = useT();
  const hasFailed = outbox.some((o) => o.status === "FAILED" || o.evidence === "FAILED");

  const photoLine = (entry: OutboxEntry): string | null => {
    if (entry.evidence === "NONE") return null;
    if (entry.evidence === "COMPLETE") return t("outbox.photoSent");
    if (entry.evidence === "FAILED") return t("outbox.photoFailed");
    return entry.status === "SYNCED" || entry.status === "REQUIRES_REVIEW"
      ? t("outbox.photoSending")
      : t("outbox.photoWaits");
  };

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
            <AppText variant="display">{t("outbox.title")}</AppText>
            <OfflineBanner online={online} sending={pending} />
            {pending > 0 ? (
              <Button
                title={hasFailed ? t("outbox.tryAgain") : t("outbox.sendAll")}
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
            <AppText variant="heading">{t("outbox.emptyTitle")}</AppText>
            <AppText variant="body" tone="subtle">
              {t("outbox.emptyBody")}
            </AppText>
          </View>
        }
        renderItem={({ item }) => {
          const photo = photoLine(item);
          const status =
            item.serverState === "REJECTED"
              ? { label: t("today.sentBack"), tone: "red" as const, icon: "alert-circle" }
              : item.serverState === "APPROVED"
                ? { label: t("today.approved"), tone: "teal" as const, icon: "check-circle-2" }
                : { ...SYNC_STATUS[item.status], label: t(`status.${item.status}` as const) };
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
                {t("outbox.recorded", { when: formatDateTime(item.createdAt) })}
                {item.versionNo ? t("outbox.versionNo", { n: item.versionNo }) : ""}
                {item.sentAt ? t("outbox.sentWhen", { when: formatRelative(item.sentAt) }) : ""}
              </AppText>
              {photo ? (
                <AppText variant="caption" tone="subtle">
                  {photo}
                </AppText>
              ) : null}
              {item.status === "REQUIRES_REVIEW" ? (
                <AppText variant="body" tone="subtle">
                  {t("outbox.officer")}
                </AppText>
              ) : null}
              {item.serverState === "REJECTED" && item.reviewReason ? (
                <AppText variant="body" tone="danger">
                  {item.reviewReason}
                </AppText>
              ) : null}
              {item.status === "FAILED" ? (
                <AppText variant="body" tone="danger">
                  {item.lastError ?? t("done.failedBody")}
                </AppText>
              ) : item.status === "PENDING" && item.lastError ? (
                <AppText variant="caption" tone="subtle">
                  {t("outbox.retryLine")}
                </AppText>
              ) : null}
            </View>
          );
        }}
      />
    </SafeAreaView>
  );
}
