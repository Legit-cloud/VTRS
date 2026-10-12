import { copy, sentTo } from "@vtrs/core";
import { useLocalSearchParams, useRouter } from "expo-router";
import { AlertCircle, Clock, Flag } from "lucide-react-native";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useApp } from "../state/app";
import { Button, IconBadge, SuccessMark } from "../ui/kit";
import { AppText, size, space, useColors } from "../ui/theme";

/**
 * The confirmation tells the truth about where the result is: on this phone, sent, sent but
 * needing a look, or not sent yet. It stays until the agent leaves; nothing auto-dismisses.
 */
export default function Done() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const { outbox, syncNow, online } = useApp();
  const router = useRouter();
  const colors = useColors();
  const entry = outbox.find((o) => o.versionId === id);

  const state = !entry
    ? "saved"
    : entry.status === "SYNCED"
      ? "sent"
      : entry.status === "REQUIRES_REVIEW"
        ? "review"
        : entry.status === "FAILED"
          ? "failed"
          : online && entry.attempts > 0
            ? "failed"
            : "saved";

  const body = {
    sent: { head: copy.sent.headline, text: entry ? sentTo(entry.ward, entry.puName) : "" },
    saved: { head: copy.savedOffline.headline, text: copy.savedOffline.body },
    review: {
      head: copy.needsReview.headline,
      text: "An officer will check one thing. You don't need to do anything.",
    },
    failed: {
      head: copy.failedSend.headline,
      text:
        entry?.status === "FAILED"
          ? (entry.lastError ?? copy.failedSend.body)
          : copy.failedSend.body,
    },
  }[state];

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
      <View
        style={{
          flex: 1,
          padding: size.screenPadding,
          alignItems: "center",
          justifyContent: "center",
          gap: space[16],
        }}
      >
        {state === "sent" ? (
          <SuccessMark />
        ) : (
          <IconBadge tone={state === "failed" ? "red" : "amber"}>
            {state === "saved" ? (
              <Clock size={30} color={colors.signalAmberText} strokeWidth={1.75} />
            ) : state === "review" ? (
              <Flag size={30} color={colors.signalAmberText} strokeWidth={1.75} />
            ) : (
              <AlertCircle size={30} color={colors.signalRedText} strokeWidth={1.75} />
            )}
          </IconBadge>
        )}
        <AppText variant="title" align="center" accessibilityRole="header">
          {body.head}
        </AppText>
        <AppText variant="bodyLg" tone="subtle" align="center">
          {body.text}
        </AppText>
        {entry && entry.evidence !== "COMPLETE" && entry.evidence !== "NONE" && state === "sent" ? (
          <AppText variant="caption" tone="muted" align="center">
            The photo is still sending.
          </AppText>
        ) : null}
      </View>
      <View style={{ padding: size.screenPadding, gap: space[8] }}>
        {state === "failed" ? <Button title="Try again" onPress={() => void syncNow()} /> : null}
        <Button
          title="Go to Today"
          variant={state === "failed" ? "outline" : "primary"}
          onPress={() => router.replace("/")}
        />
      </View>
    </SafeAreaView>
  );
}
