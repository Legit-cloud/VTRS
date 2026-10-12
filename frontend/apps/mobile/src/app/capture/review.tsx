import { formatNumber } from "@vtrs/core";
import { useRouter } from "expo-router";
import { Check, Image as ImageIcon, MapPin } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Image, View } from "react-native";
import { describeChecks, liveChecks, parseCount, sheetFieldsOf } from "../../core/capture";
import { useT } from "../../i18n";
import { askForLocation, locationAccess, type LocationAccess } from "../../platform/location";
import { useCapture } from "../../state/capture";
import { CaptureFrame } from "../../ui/capture-frame";
import { Button } from "../../ui/kit";
import { AppText, radius, space, useColors } from "../../ui/theme";

export default function Review() {
  const { contest, assignment, draft, send } = useCapture();
  const router = useRouter();
  const colors = useColors();
  const t = useT();
  const [access, setAccess] = useState<LocationAccess>("undetermined");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void locationAccess().then(setAccess);
  }, []);

  const fields = sheetFieldsOf(contest);
  const warnings = describeChecks(liveChecks(contest, draft), parseCount(draft.totals.valid));

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const versionId = await send();
      router.replace({ pathname: "/done", params: { id: versionId } });
    } catch {
      setError(t("review.saveFailed"));
      setBusy(false);
    }
  }

  return (
    <CaptureFrame
      step={3}
      title={t("review.title")}
      helper={t("review.helper")}
      footer={
        <Button
          title={t("review.send")}
          loading={busy}
          icon={<Check size={20} color={colors.primaryForeground} strokeWidth={2} />}
          onPress={submit}
        />
      }
    >
      <View
        style={{
          backgroundColor: colors.card,
          borderRadius: radius.card,
          padding: space[16],
          gap: space[12],
          borderWidth: 1,
          borderColor: colors.border,
        }}
      >
        <AppText variant="heading">{assignment.polling_unit.name}</AppText>
        {[...contest.candidates]
          .sort((a, b) => a.ballot_order - b.ballot_order)
          .map((c) => (
            <View
              key={c.id}
              style={{ flexDirection: "row", justifyContent: "space-between", gap: space[8] }}
            >
              <AppText variant="body" style={{ flex: 1 }}>
                {c.name}{" "}
                <AppText variant="body" tone="muted">
                  {c.party_acronym}
                </AppText>
              </AppText>
              <AppText
                variant="bodyLg"
                style={{ fontFamily: "Onest_700", fontVariant: ["tabular-nums"] }}
              >
                {formatNumber(parseCount(draft.votes[c.id]))}
              </AppText>
            </View>
          ))}
        <View style={{ height: 1, backgroundColor: colors.border }} />
        {fields.map((f) => (
          <View key={f} style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <AppText variant="body" tone="subtle">
              {t(`field.${f}` as const)}
            </AppText>
            <AppText
              variant="bodyLg"
              style={{ fontFamily: "Onest_700", fontVariant: ["tabular-nums"] }}
            >
              {formatNumber(parseCount(draft.totals[f]))}
            </AppText>
          </View>
        ))}
      </View>

      {warnings.length > 0 ? (
        <View
          accessibilityRole="alert"
          style={{
            backgroundColor: colors.signalAmberSoft,
            borderRadius: radius.control,
            padding: space[16],
            gap: space[4],
          }}
        >
          <AppText variant="label" style={{ color: colors.signalAmberText }}>
            {t("review.officerLook")}
          </AppText>
          {warnings.map((w) => (
            <AppText key={w.key} variant="body" style={{ color: colors.signalAmberText }}>
              {t(w.key, w.params)}
            </AppText>
          ))}
        </View>
      ) : null}

      {draft.photo ? (
        <View style={{ flexDirection: "row", gap: space[12], alignItems: "center" }}>
          <Image
            source={{ uri: draft.photo.uri }}
            accessibilityLabel={t("review.photo")}
            style={{ width: 72, height: 96, borderRadius: 12, backgroundColor: colors.muted }}
          />
          <View style={{ flex: 1, gap: space[4] }}>
            <View style={{ flexDirection: "row", gap: space[8], alignItems: "center" }}>
              <ImageIcon size={18} color={colors.signalTealText} />
              <AppText variant="label" tone="strong">
                {t("review.photo")}
              </AppText>
            </View>
            <Button
              title={t("photo.retake")}
              variant="ghost"
              onPress={() => router.replace("/capture/photo")}
            />
          </View>
        </View>
      ) : null}

      <View
        style={{
          backgroundColor: colors.card,
          borderRadius: radius.control,
          padding: space[16],
          gap: space[8],
          borderWidth: 1,
          borderColor: colors.border,
        }}
      >
        <View style={{ flexDirection: "row", gap: space[8], alignItems: "center" }}>
          <MapPin
            size={18}
            color={access === "granted" ? colors.signalTealText : colors.signalAmberText}
          />
          <AppText variant="label" tone="strong">
            {t("review.location")}
          </AppText>
        </View>
        {access === "granted" ? (
          <AppText variant="body" tone="subtle">
            {t("review.locationOn")}
          </AppText>
        ) : (
          <>
            <AppText variant="body" tone="subtle">
              {t("review.locationAsk")}
            </AppText>
            <Button
              title={t("review.allowLocation")}
              variant="secondary"
              onPress={() => void askForLocation().then(setAccess)}
            />
          </>
        )}
      </View>

      {error ? (
        <AppText variant="body" tone="danger" accessibilityRole="alert">
          {error}
        </AppText>
      ) : null}
    </CaptureFrame>
  );
}
