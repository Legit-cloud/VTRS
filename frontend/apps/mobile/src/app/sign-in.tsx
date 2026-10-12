import { ApiError, formatLocalPhone, normalizePhone } from "@vtrs/core";
import { useState } from "react";
import { View } from "react-native";
import { useApp } from "../state/app";
import { Button, Field, Screen, TopBar } from "../ui/kit";
import { AppText, space, useColors, radius, size } from "../ui/theme";

export default function SignIn() {
  const { signIn, online } = useApp();
  const colors = useColors();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    const normalised = normalizePhone(phone);
    if (!normalised) return setPhoneError("Enter your phone number, like 0803 123 4567.");
    setPhoneError(null);
    setBusy(true);
    try {
      await signIn(normalised, password);
    } catch (e) {
      const api = e instanceof ApiError ? e : null;
      if (api?.isNetwork) setError("Could not reach the server. Check your network and try again.");
      else if (api?.status === 429)
        setError(
          `Too many attempts. Try again in ${Math.ceil((api.retryAfterSeconds ?? 60) / 60)} min.`,
        );
      else if (api?.code === "device_not_registered")
        setError(
          "This phone is not the one your account was set up on. Ask your officer for a new invitation.",
        );
      else setError(api?.detail ?? "Could not sign in. Check your number and password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen
      footer={
        <Button
          title="Continue"
          forward
          loading={busy}
          disabled={!phone || !password || !online}
          onPress={submit}
        />
      }
    >
      <TopBar />
      <View style={{ gap: space[8] }}>
        <AppText variant="display">Enter your mobile number</AppText>
        <AppText variant="bodyLg" tone="subtle">
          Use the number your party invited you with.
        </AppText>
      </View>
      <Field
        label="Phone number"
        value={phone}
        onChangeText={(t) => setPhone(formatLocalPhone(t))}
        keyboardType="phone-pad"
        autoComplete="tel"
        textContentType="telephoneNumber"
        placeholder="0803 123 4567"
        error={phoneError}
        prefix={
          <View
            accessibilityLabel="Country code plus 234"
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
        label="Password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="current-password"
        textContentType="password"
        autoCapitalize="none"
      />
      {!online ? (
        <AppText variant="caption" tone="subtle">
          Signing in needs a network. Once you are in, the app works without one.
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
