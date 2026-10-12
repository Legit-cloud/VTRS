import { formatNumber } from "@vtrs/core";
import { useRouter } from "expo-router";
import { Check, Image as ImageIcon, MapPin } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Image, View } from "react-native";
import {
  FIELD_LABEL,
  describeChecks,
  liveChecks,
  parseCount,
  sheetFieldsOf,
} from "../../core/capture";
import { askForLocation, locationAccess, type LocationAccess } from "../../platform/location";
import { useCapture } from "../../state/capture";
import { CaptureFrame } from "../../ui/capture-frame";
import { Button } from "../../ui/kit";
import { AppText, radius, space, useColors } from "../../ui/theme";

export default function Review() {
  const { contest, assignment, draft, send } = useCapture();
  const router = useRouter();
  const colors = useColors();
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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the result. Try again.");
      setBusy(false);
    }
  }

  return (
    <CaptureFrame
      step={3}
      title="Check, then send"
      helper="Once sent, a result cannot be edited. A mistake is fixed by sending a correction."
      footer={
        <Button
          title="Send result"
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
              {FIELD_LABEL[f]}
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
            This will go to an officer for a look
          </AppText>
          {warnings.map((w) => (
            <AppText key={w} variant="body" style={{ color: colors.signalAmberText }}>
              {w}
            </AppText>
          ))}
        </View>
      ) : null}

      {draft.photo ? (
        <View style={{ flexDirection: "row", gap: space[12], alignItems: "center" }}>
          <Image
            source={{ uri: draft.photo.uri }}
            accessibilityLabel="Photo of the result sheet"
            style={{ width: 72, height: 96, borderRadius: 12, backgroundColor: colors.muted }}
          />
          <View style={{ flex: 1, gap: space[4] }}>
            <View style={{ flexDirection: "row", gap: space[8], alignItems: "center" }}>
              <ImageIcon size={18} color={colors.signalTealText} />
              <AppText variant="label" tone="strong">
                Result sheet photo
              </AppText>
            </View>
            <Button
              title="Retake"
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
            Location
          </AppText>
        </View>
        {access === "granted" ? (
          <AppText variant="body" tone="subtle">
            Your position is recorded once, when you send, to confirm you are at the polling unit.
          </AppText>
        ) : (
          <>
            <AppText variant="body" tone="subtle">
              We use your location once, when you send a result, to confirm you&apos;re at your
              polling unit. We don&apos;t track you.
            </AppText>
            <Button
              title="Allow location"
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
