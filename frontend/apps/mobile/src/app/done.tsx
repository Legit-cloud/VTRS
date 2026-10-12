import { useLocalSearchParams, useRouter } from "expo-router";
import { AlertCircle, Clock, Flag } from "lucide-react-native";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useT } from "../i18n";
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
  const t = useT();
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
    sent: {
      head: t("done.sent"),
      text: entry ? t("done.sentBody", { ward: entry.ward, unit: entry.puName }) : "",
    },
    saved: { head: t("done.saved"), text: t("done.savedBody") },
    review: { head: t("done.review"), text: t("done.reviewBody") },
    failed: {
      head: t("done.failed"),
      text:
        entry?.status === "FAILED"
          ? (entry.lastError ?? t("done.failedBody"))
          : t("done.failedBody"),
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
            {t("done.photoSending")}
          </AppText>
        ) : null}
      </View>
      <View style={{ padding: size.screenPadding, gap: space[8] }}>
        {state === "failed" ? (
          <Button title={t("done.tryAgain")} onPress={() => void syncNow()} />
        ) : null}
        <Button
          title={t("done.goToday")}
          variant={state === "failed" ? "outline" : "primary"}
          onPress={() => router.replace("/")}
        />
      </View>
    </SafeAreaView>
  );
}
