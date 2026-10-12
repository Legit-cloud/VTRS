import {
  SYNC_STATUS,
  distanceMetres,
  formatDateTime,
  formatDistance,
  formatNumber,
  formatRelative,
} from "@vtrs/core";
import { useFocusEffect, useRouter } from "expo-router";
import { MapPin } from "lucide-react-native";
import { useCallback, useState } from "react";
import { RefreshControl, ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useT } from "../../i18n";
import { currentFix, locationAccess } from "../../platform/location";
import { useApp } from "../../state/app";
import { Button, IconBadge, OfflineBanner, StatusChip } from "../../ui/kit";
import { AppText, radius, size, space, useColors } from "../../ui/theme";

/** Where an agent starts: the unit, whether capture is open, and one button. */
export default function Today() {
  const {
    assignments,
    assignmentsAt,
    outbox,
    online,
    pending,
    refreshAssignments,
    refreshingAssignments,
    syncNow,
  } = useApp();
  const router = useRouter();
  const colors = useColors();
  const t = useT();
  const [distance, setDistance] = useState<number | null>(null);

  const assignment = assignments?.[0] ?? null;
  const unit = assignment?.polling_unit;
  const unitLat = unit?.latitude;
  const unitLng = unit?.longitude;

  // A one-off position check when the screen opens, only if location is already allowed.
  useFocusEffect(
    useCallback(() => {
      let alive = true;
      (async () => {
        if (!unitLat || !unitLng) return setDistance(null);
        if ((await locationAccess()) !== "granted") return;
        const fix = await currentFix(4000);
        if (alive && fix) {
          setDistance(
            distanceMetres(
              { lat: fix.lat, lng: fix.lng },
              { lat: Number(unitLat), lng: Number(unitLng) },
            ),
          );
        }
      })();
      return () => {
        alive = false;
      };
    }, [unitLat, unitLng]),
  );

  const open = assignment?.election.capture_open ?? false;

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: colors.canvas }}
      edges={["top", "left", "right"]}
    >
      <ScrollView
        contentContainerStyle={{ padding: size.screenPadding, gap: space[16] }}
        refreshControl={
          <RefreshControl
            refreshing={refreshingAssignments}
            onRefresh={() => void refreshAssignments().then(syncNow)}
          />
        }
      >
        <AppText variant="display">{t("today.title")}</AppText>
        <OfflineBanner online={online} sending={pending} />

        {!assignment || !unit ? (
          <View
            style={{
              backgroundColor: colors.card,
              borderRadius: radius.card,
              padding: space[24],
              gap: space[12],
              alignItems: "flex-start",
            }}
          >
            <IconBadge>
              <MapPin size={28} color="#FFFFFF" strokeWidth={1.75} />
            </IconBadge>
            <AppText variant="heading">{t("today.noUnit")}</AppText>
            <AppText variant="body" tone="subtle">
              {online ? t("today.noUnitOnline") : t("today.noUnitOffline")}
            </AppText>
          </View>
        ) : (
          <>
            <View
              style={{
                backgroundColor: colors.card,
                borderRadius: radius.card,
                padding: space[20],
                gap: space[8],
                borderWidth: 1,
                borderColor: colors.border,
              }}
            >
              <AppText variant="caption" tone="muted">
                {assignment.election.name}
              </AppText>
              <AppText variant="title">{unit.name}</AppText>
              <AppText variant="body" tone="subtle">
                <AppText variant="body" tone="subtle" style={{ fontVariant: ["tabular-nums"] }}>
                  {unit.inec_code}
                </AppText>
                {" · "}
                {unit.ward} · {unit.lga}
              </AppText>
              {unit.registered_voters ? (
                <AppText variant="body" tone="subtle">
                  {t("today.voters", { count: formatNumber(unit.registered_voters) })}
                </AppText>
              ) : null}
              {distance !== null ? (
                <View style={{ marginTop: space[4] }}>
                  <StatusChip
                    status={
                      distance <= 300
                        ? { label: t("today.atUnit"), tone: "teal", icon: "check-circle-2" }
                        : {
                            label: t("today.away", { distance: formatDistance(distance) }),
                            tone: "amber",
                            icon: "flag",
                          }
                    }
                  />
                </View>
              ) : null}
            </View>

            {!open ? (
              <View
                style={{
                  backgroundColor: colors.signalAmberSoft,
                  borderRadius: radius.control,
                  padding: space[16],
                }}
              >
                <AppText variant="label" style={{ color: colors.signalAmberText }}>
                  {t("today.notOpen")}
                </AppText>
                <AppText variant="body" style={{ color: colors.signalAmberText }}>
                  {assignment.election.polls_close_at
                    ? t("today.notOpenBody", {
                        when: formatDateTime(assignment.election.polls_close_at),
                      })
                    : t("today.notOpenNoTime")}
                </AppText>
              </View>
            ) : null}

            {assignment.contests.map((contest) => {
              const mine = outbox.filter(
                (o) => o.contestId === contest.id && o.pollingUnitId === unit.id,
              );
              const latest = mine[0];
              const rejected = latest?.serverState === "REJECTED";
              return (
                <View
                  key={contest.id}
                  style={{
                    backgroundColor: colors.card,
                    borderRadius: radius.card,
                    padding: space[20],
                    gap: space[12],
                    borderWidth: 1,
                    borderColor: colors.border,
                  }}
                >
                  <AppText variant="heading">{contest.title}</AppText>
                  {latest ? (
                    <View style={{ gap: space[4] }}>
                      <StatusChip
                        status={
                          rejected
                            ? { label: t("today.sentBack"), tone: "red", icon: "alert-circle" }
                            : latest.serverState === "APPROVED"
                              ? { label: t("today.approved"), tone: "teal", icon: "check-circle-2" }
                              : {
                                  ...SYNC_STATUS[latest.status],
                                  label: t(`status.${latest.status}` as const),
                                }
                        }
                      />
                      <AppText variant="caption" tone="subtle">
                        {t("today.version", {
                          n: latest.versionNo ?? mine.length,
                          when: formatRelative(latest.createdAt),
                        })}
                      </AppText>
                      {rejected && latest.reviewReason ? (
                        <AppText variant="body" tone="danger">
                          {latest.reviewReason}
                        </AppText>
                      ) : null}
                    </View>
                  ) : null}
                  <Button
                    title={latest ? t("today.correct") : t("today.start")}
                    forward
                    variant={latest && !rejected ? "outline" : "primary"}
                    onPress={() =>
                      router.push({
                        pathname: "/capture/votes",
                        params: { assignment: assignment.assignment_id, contest: contest.id },
                      })
                    }
                  />
                </View>
              );
            })}
          </>
        )}

        {assignmentsAt ? (
          <AppText variant="caption" tone="muted" align="center">
            {t("today.updated", { when: formatRelative(assignmentsAt) })}
          </AppText>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
