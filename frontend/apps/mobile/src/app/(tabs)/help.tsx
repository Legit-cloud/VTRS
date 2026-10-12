import { useState } from "react";
import { Alert, Linking, Pressable, ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { LANGUAGES, useI18n } from "../../i18n";
import { useApp } from "../../state/app";
import { Button } from "../../ui/kit";
import { AppText, radius, size, space, useColors } from "../../ui/theme";

const SUPPORT_PHONE = process.env.EXPO_PUBLIC_SUPPORT_PHONE ?? "";
const GUIDES = ["g1", "g2", "g3", "g4"] as const;

export default function Help() {
  const { me, pending, signOut, deviceId } = useApp();
  const { t, language, setLanguage } = useI18n();
  const colors = useColors();
  const [busy, setBusy] = useState(false);

  const confirmSignOut = () => {
    const message =
      pending > 0
        ? t("help.signOutPending", {
            count: pending,
            noun: pending === 1 ? t("noun.result") : t("noun.results"),
          })
        : t("help.signOutPlain");
    Alert.alert(t("help.signOutTitle"), message, [
      { text: t("help.stay"), style: "cancel" },
      {
        text: t("help.signOut"),
        style: "destructive",
        onPress: () => {
          setBusy(true);
          void signOut().finally(() => setBusy(false));
        },
      },
    ]);
  };

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: colors.canvas }}
      edges={["top", "left", "right"]}
    >
      <ScrollView contentContainerStyle={{ padding: size.screenPadding, gap: space[16] }}>
        <AppText variant="display">{t("help.title")}</AppText>

        {SUPPORT_PHONE ? (
          <View style={{ gap: space[12] }}>
            <Button
              title={t("help.call")}
              onPress={() => void Linking.openURL(`tel:${SUPPORT_PHONE}`)}
            />
            <Button
              title={t("help.whatsapp")}
              variant="secondary"
              onPress={() =>
                void Linking.openURL(`https://wa.me/${SUPPORT_PHONE.replace(/\D/g, "")}`)
              }
            />
          </View>
        ) : (
          <AppText variant="body" tone="subtle">
            {t("help.noSupport")}
          </AppText>
        )}

        <View
          style={{
            backgroundColor: colors.card,
            borderRadius: radius.card,
            padding: space[20],
            gap: space[12],
            borderWidth: 1,
            borderColor: colors.border,
          }}
        >
          <AppText variant="heading">{t("help.language")}</AppText>
          <View style={{ flexDirection: "row", gap: space[8] }}>
            {LANGUAGES.map((l) => (
              <Pressable
                key={l.code}
                accessibilityRole="radio"
                accessibilityState={{ selected: language === l.code }}
                onPress={() => setLanguage(l.code)}
                style={{
                  flex: 1,
                  height: size.hit,
                  borderRadius: radius.control,
                  borderWidth: 1.5,
                  borderColor: language === l.code ? colors.primary : colors.input,
                  backgroundColor: language === l.code ? colors.primarySoft : "transparent",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <AppText variant="label">{l.name}</AppText>
              </Pressable>
            ))}
          </View>
        </View>

        {GUIDES.map((g) => (
          <View
            key={g}
            style={{
              backgroundColor: colors.card,
              borderRadius: radius.card,
              padding: space[20],
              gap: space[8],
              borderWidth: 1,
              borderColor: colors.border,
            }}
          >
            <AppText variant="heading">{t(`help.${g}.title` as const)}</AppText>
            <AppText variant="body" tone="subtle">
              {t(`help.${g}.body` as const)}
            </AppText>
          </View>
        ))}

        <View style={{ gap: space[8], marginTop: space[8] }}>
          {me ? (
            <AppText variant="caption" tone="muted">
              {t("help.signedInAs", { name: me.full_name })}
              {deviceId ? ` · ${deviceId.slice(0, 8)}` : ""}
            </AppText>
          ) : null}
          <Button
            title={t("help.signOut")}
            variant="outline"
            loading={busy}
            onPress={confirmSignOut}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
