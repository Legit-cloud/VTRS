import { ApiError, formatLocalPhone, normalizePhone } from "@vtrs/core";
import { useState } from "react";
import { View } from "react-native";
import { useT } from "../i18n";
import { useApp } from "../state/app";
import { Button, Field, Screen, TopBar } from "../ui/kit";
import { AppText, radius, size, space, useColors } from "../ui/theme";

export default function SignIn() {
  const { signIn, online } = useApp();
  const t = useT();
  const colors = useColors();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    const normalised = normalizePhone(phone);
    if (!normalised) return setPhoneError(t("signIn.badPhone"));
    setPhoneError(null);
    setBusy(true);
    try {
      await signIn(normalised, password);
    } catch (e) {
      const api = e instanceof ApiError ? e : null;
      if (api?.isNetwork) setError(t("error.network"));
      else if (api?.status === 429)
        setError(t("error.throttled", { minutes: Math.ceil((api.retryAfterSeconds ?? 60) / 60) }));
      else if (api?.code === "device_not_registered") setError(t("error.device"));
      else setError(t("error.signIn"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen
      footer={
        <Button
          title={t("signIn.continue")}
          forward
          loading={busy}
          disabled={!phone || !password || !online}
          onPress={submit}
        />
      }
    >
      <TopBar />
      <View style={{ gap: space[8] }}>
        <AppText variant="display">{t("signIn.title")}</AppText>
        <AppText variant="bodyLg" tone="subtle">
          {t("signIn.helper")}
        </AppText>
      </View>
      <Field
        label={t("signIn.phone")}
        value={phone}
        onChangeText={(text) => setPhone(formatLocalPhone(text))}
        keyboardType="phone-pad"
        autoComplete="tel"
        textContentType="telephoneNumber"
        placeholder="0803 123 4567"
        error={phoneError}
        prefix={
          <View
            accessibilityLabel="+234"
            style={{
              width: 72,
              height: size.control,
              borderRadius: radius.control,
              borderWidth: 1.5,
              borderColor: colors.input,
              backgroundColor: colors.inputFill,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppText variant="bodyLg">+234</AppText>
          </View>
        }
      />
      <Field
        label={t("signIn.password")}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="current-password"
        textContentType="password"
        autoCapitalize="none"
      />
      {!online ? (
        <AppText variant="caption" tone="subtle">
          {t("signIn.needsNetwork")}
        </AppText>
      ) : null}
      {error ? (
        <AppText variant="body" tone="danger" accessibilityRole="alert">
          {error}
        </AppText>
      ) : null}
    </Screen>
  );
}
