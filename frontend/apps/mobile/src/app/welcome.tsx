import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Svg, { Line, Rect } from "react-native-svg";
import { LANGUAGES, useI18n } from "../i18n";
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
  const { t, language, setLanguage } = useI18n();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ flex: 1, padding: size.screenPadding, justifyContent: "space-between" }}>
        <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: space[8] }}>
          {LANGUAGES.map((l) => (
            <Pressable
              key={l.code}
              accessibilityRole="button"
              accessibilityState={{ selected: language === l.code }}
              accessibilityLabel={l.name}
              onPress={() => setLanguage(l.code)}
              style={{
                minHeight: size.hit,
                paddingHorizontal: space[12],
                justifyContent: "center",
                borderBottomWidth: 3,
                borderBottomColor: language === l.code ? colors.primary : "transparent",
              }}
            >
              <AppText variant="label" tone={language === l.code ? "default" : "muted"}>
                {l.name}
              </AppText>
            </Pressable>
          ))}
        </View>
        <View style={{ flex: 1, justifyContent: "center", gap: space[24] }}>
          <Logo />
          <View style={{ gap: space[12] }}>
            <AppText variant="display">{t("welcome.title")}</AppText>
            <AppText variant="bodyLg" tone="subtle">
              {t("welcome.body")}
            </AppText>
          </View>
        </View>
        <View style={{ gap: space[12] }}>
          <Button title={t("welcome.signIn")} forward onPress={() => router.push("/sign-in")} />
          <Button
            title={t("welcome.invite")}
            variant="secondary"
            onPress={() => router.push("/invite")}
          />
        </View>
      </View>
    </SafeAreaView>
  );
}
