import { useRouter } from "expo-router";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Svg, { Line, Rect } from "react-native-svg";
import { Button } from "../ui/kit";
import { AppText, size, space, useColors } from "../ui/theme";

/** The mark: four white strokes crossed by an aqua slash on a teal rounded square. */
function Logo({ px = 88 }: { px?: number }) {
  return (
    <Svg width={px} height={px} viewBox="0 0 96 96" accessibilityLabel="VTRS">
      <Rect width={96} height={96} rx={24} fill="#00907F" />
      {[24, 38, 52, 66].map((x) => (
        <Line
          key={x}
          x1={x}
          y1={26}
          x2={x}
          y2={70}
          stroke="#FFFFFF"
          strokeWidth={7}
          strokeLinecap="round"
        />
      ))}
      <Line
        x1={16}
        y1={62}
        x2={76}
        y2={34}
        stroke="#A4F7EF"
        strokeWidth={7}
        strokeLinecap="round"
      />
    </Svg>
  );
}

export default function Welcome() {
  const router = useRouter();
  const colors = useColors();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ flex: 1, padding: size.screenPadding, justifyContent: "space-between" }}>
        <View style={{ flex: 1, justifyContent: "center", gap: space[24] }}>
          <Logo />
          <View style={{ gap: space[12] }}>
            <AppText variant="display">Record your polling unit&apos;s result</AppText>
            <AppText variant="bodyLg" tone="subtle">
              Enter the numbers from the result sheet, take a photo, and send. It works without a
              network and sends when you are back online.
            </AppText>
          </View>
        </View>
        <View style={{ gap: space[12] }}>
          <Button title="Sign in" forward onPress={() => router.push("/sign-in")} />
          <Button
            title="I have an invitation"
            variant="secondary"
            onPress={() => router.push("/invite")}
          />
        </View>
      </View>
    </SafeAreaView>
  );
}
