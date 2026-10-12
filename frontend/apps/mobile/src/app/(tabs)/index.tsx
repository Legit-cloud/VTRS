import {
  distanceMetres,
  formatDateTime,
  formatDistance,
  formatNumber,
  formatRelative,
  wrongLocation,
  SYNC_STATUS,
} from "@vtrs/core";
import { useFocusEffect, useRouter } from "expo-router";
import { MapPin } from "lucide-react-native";
import { useCallback, useState } from "react";
import { RefreshControl, ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
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
        <AppText variant="display">Today</AppText>
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
            <AppText variant="heading">No polling unit yet</AppText>
            <AppText variant="body" tone="subtle">
              {online
                ? "You have not been placed at a polling unit for an election. Your party officer assigns this. Pull down to check again."
                : "Connect once to download your assignment. After that the app works without a network."}
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
                  About {formatNumber(unit.registered_voters)} registered voters
                </AppText>
              ) : null}
              {distance !== null ? (
                <View style={{ marginTop: space[4] }}>
                  <StatusChip
                    status={
                      distance <= 300
                        ? {
                            label: "You're at the polling unit",
                            tone: "teal",
                            icon: "check-circle-2",
                          }
                        : { label: `${formatDistance(distance)} away`, tone: "amber", icon: "flag" }
                    }
                  />
                </View>
              ) : null}
              {distance !== null && distance > 300 ? (
                <AppText variant="caption" tone="subtle">
                  {wrongLocation(formatDistance(distance), unit.ward, unit.name)}
                </AppText>
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
                  Result entry is not open yet
                </AppText>
                <AppText variant="body" style={{ color: colors.signalAmberText }}>
                  {assignment.election.polls_close_at
                    ? `Polls close ${formatDateTime(assignment.election.polls_close_at)}. You can still fill in the numbers; they send when capture opens.`
                    : "Your party opens result entry when polls close."}
                </AppText>
              </View>
            ) : null}

            {assignment.contests.map((contest) => {
              const mine = outbox.filter(
                (o) => o.contestId === contest.id && o.pollingUnitId === unit.id,
              );
              const latest = mine[0];
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
                          latest.serverState === "REJECTED"
                            ? {
                                label: "Sent back for correction",
                                tone: "red",
                                icon: "alert-circle",
                              }
                            : latest.serverState === "APPROVED"
                              ? { label: "Approved", tone: "teal", icon: "check-circle-2" }
                              : SYNC_STATUS[latest.status]
                        }
                      />
                      <AppText variant="caption" tone="subtle">
                        Version {latest.versionNo ?? mine.length} ·{" "}
                        {formatRelative(latest.createdAt)}
                      </AppText>
                      {latest.serverState === "REJECTED" && latest.reviewReason ? (
                        <AppText variant="body" tone="danger">
                          {latest.reviewReason}
                        </AppText>
                      ) : null}
                    </View>
                  ) : null}
                  <Button
                    title={latest ? "Send a correction" : "Start result entry"}
                    forward
                    variant={latest && latest.serverState !== "REJECTED" ? "outline" : "primary"}
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
            Assignment updated {formatRelative(assignmentsAt)}
          </AppText>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
