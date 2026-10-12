import { formatNumber } from "@vtrs/core";
import { useRouter } from "expo-router";
import { AlertCircle, CheckCircle2 } from "lucide-react-native";
import { View } from "react-native";
import {
  candidateNumbers,
  describeChecks,
  liveChecks,
  parseCount,
  sheetFieldsOf,
} from "../../core/capture";
import { useT } from "../../i18n";
import { useCapture } from "../../state/capture";
import { CaptureFrame } from "../../ui/capture-frame";
import { Button, Field } from "../../ui/kit";
import { AppText, radius, space, useColors } from "../../ui/theme";

export default function Totals() {
  const { contest, draft, setTotal } = useCapture();
  const router = useRouter();
  const colors = useColors();
  const t = useT();
  const fields = sheetFieldsOf(contest);
  const missing = fields.some((f) => parseCount(draft.totals[f]) === null);

  const checks = liveChecks(contest, draft);
  const valid = parseCount(draft.totals.valid);
  const sum = candidateNumbers(contest, draft).reduce((a, b) => a + b, 0);
  const problems = describeChecks(checks, valid);

  return (
    <CaptureFrame
      step={1}
      title={t("totals.title")}
      helper={t("totals.helper")}
      footer={
        <Button
          title={t("common.next")}
          forward
          disabled={missing}
          onPress={() => router.push({ pathname: "/capture/photo" })}
        />
      }
    >
      {fields.map((f) => (
        <Field
          key={f}
          label={t(`field.${f}` as const)}
          numeric
          value={draft.totals[f] ?? ""}
          onChangeText={(text) => setTotal(f, text)}
          maxLength={7}
          placeholder="0"
        />
      ))}

      {valid !== null ? (
        problems.length === 0 ? (
          <View
            accessibilityRole="alert"
            style={{
              flexDirection: "row",
              gap: space[8],
              padding: space[16],
              borderRadius: radius.control,
              backgroundColor: colors.signalTealSoft,
            }}
          >
            <CheckCircle2 size={20} color={colors.signalTealText} />
            <AppText variant="label" style={{ flex: 1, color: colors.signalTealText }}>
              {t("totals.ok", { sum: formatNumber(sum), valid: formatNumber(valid) })}
            </AppText>
          </View>
        ) : (
          <View
            accessibilityRole="alert"
            style={{
              gap: space[8],
              padding: space[16],
              borderRadius: radius.control,
              backgroundColor: colors.signalRedSoft,
            }}
          >
            {problems.map((p) => (
              <View key={p.key} style={{ flexDirection: "row", gap: space[8] }}>
                <AlertCircle size={20} color={colors.signalRedText} style={{ marginTop: 2 }} />
                <AppText variant="body" style={{ flex: 1, color: colors.signalRedText }}>
                  {t(p.key, p.params)}
                </AppText>
              </View>
            ))}
            <AppText variant="caption" style={{ color: colors.signalRedText }}>
              {t("totals.stillSend")}
            </AppText>
          </View>
        )
      ) : null}
    </CaptureFrame>
  );
}
