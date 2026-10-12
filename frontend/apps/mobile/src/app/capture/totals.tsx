import { formatNumber } from "@vtrs/core";
import { useRouter } from "expo-router";
import { AlertCircle, CheckCircle2 } from "lucide-react-native";
import { View } from "react-native";
import {
  FIELD_LABEL,
  candidateNumbers,
  describeChecks,
  liveChecks,
  parseCount,
  sheetFieldsOf,
} from "../../core/capture";
import { useCapture } from "../../state/capture";
import { CaptureFrame } from "../../ui/capture-frame";
import { Button, Field } from "../../ui/kit";
import { AppText, radius, space, useColors } from "../../ui/theme";

export default function Totals() {
  const { contest, draft, setTotal } = useCapture();
  const router = useRouter();
  const colors = useColors();
  const fields = sheetFieldsOf(contest);
  const missing = fields.some((f) => parseCount(draft.totals[f]) === null);

  const checks = liveChecks(contest, draft);
  const valid = parseCount(draft.totals.valid);
  const sum = candidateNumbers(contest, draft).reduce((a, b) => a + b, 0);
  const problems = describeChecks(checks, valid);

  return (
    <CaptureFrame
      step={1}
      title="Totals from the sheet"
      helper="These are the totals printed at the bottom of the sheet."
      footer={
        <Button
          title="Next"
          forward
          disabled={missing}
          onPress={() => router.push({ pathname: "/capture/photo" })}
        />
      }
    >
      {fields.map((f) => (
        <Field
          key={f}
          label={FIELD_LABEL[f]}
          numeric
          value={draft.totals[f] ?? ""}
          onChangeText={(t) => setTotal(f, t)}
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
              Candidate votes {formatNumber(sum)} = Valid votes {formatNumber(valid)} ✓
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
              <View key={p} style={{ flexDirection: "row", gap: space[8] }}>
                <AlertCircle size={20} color={colors.signalRedText} style={{ marginTop: 2 }} />
                <AppText variant="body" style={{ flex: 1, color: colors.signalRedText }}>
                  {p}
                </AppText>
              </View>
            ))}
            <AppText variant="caption" style={{ color: colors.signalRedText }}>
              If the sheet really says this, you can still send it. An officer will look at it.
            </AppText>
          </View>
        )
      ) : null}
    </CaptureFrame>
  );
}
