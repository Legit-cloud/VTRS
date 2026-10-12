import { ApiError } from "@vtrs/core";
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { View } from "react-native";
import { tokenFrom } from "../core/invite";
import { useT } from "../i18n";
import { useApp } from "../state/app";
import { Button, Field, Screen, TopBar } from "../ui/kit";
import { AppText, space } from "../ui/theme";

const MIN_PASSWORD = 12;

export default function Invite() {
  const { acceptInvitation, completeInvitation, online } = useApp();
  const t = useT();
  const params = useLocalSearchParams<{ token?: string }>();
  const [link, setLink] = useState(params.token ?? "");
  const [challenge, setChallenge] = useState<{ id: string; hint: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const describe = (e: unknown) =>
    e instanceof ApiError ? (e.isNetwork ? t("error.network") : e.detail) : t("error.generic");

  async function step1() {
    setBusy(true);
    setError(null);
    try {
      const result = await acceptInvitation(tokenFrom(link));
      setChallenge({ id: result.challengeId, hint: result.hint });
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function step2() {
    if (!challenge) return;
    setBusy(true);
    setError(null);
    try {
      await completeInvitation({
        token: tokenFrom(link),
        challengeId: challenge.id,
        code: code.trim(),
        password,
      });
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = again.length > 0 && again !== password;

  return (
    <Screen
      footer={
        challenge ? (
          <Button
            title={t("invite.create")}
            forward
            loading={busy}
            disabled={
              code.trim().length < 4 || password.length < MIN_PASSWORD || mismatch || !online
            }
            onPress={step2}
          />
        ) : (
          <Button
            title={t("signIn.continue")}
            forward
            loading={busy}
            disabled={link.trim().length < 8 || !online}
            onPress={step1}
          />
        )
      }
    >
      <TopBar />
      <View style={{ gap: space[8] }}>
        <AppText variant="display">{challenge ? t("invite.codeTitle") : t("invite.title")}</AppText>
        <AppText variant="bodyLg" tone="subtle">
          {challenge ? t("invite.codeHelper", { hint: challenge.hint || "…" }) : t("invite.helper")}
        </AppText>
      </View>
      {challenge ? (
        <>
          <Field
            label={t("invite.code")}
            value={code}
            onChangeText={setCode}
            numeric
            autoComplete="one-time-code"
            textContentType="oneTimeCode"
            maxLength={8}
          />
          <Field
            label={t("invite.password")}
            helper={t("invite.passwordHelper", { min: MIN_PASSWORD })}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            textContentType="newPassword"
            error={tooShort ? t("invite.passwordShort", { min: MIN_PASSWORD }) : null}
          />
          <Field
            label={t("invite.again")}
            value={again}
            onChangeText={setAgain}
            secureTextEntry
            autoCapitalize="none"
            textContentType="newPassword"
            error={mismatch ? t("invite.mismatch") : null}
          />
        </>
      ) : (
        <Field
          label={t("invite.link")}
          value={link}
          onChangeText={setLink}
          autoCapitalize="none"
          autoCorrect={false}
          multiline
          placeholder="https://…"
        />
      )}
      {error ? (
        <AppText variant="body" tone="danger" accessibilityRole="alert">
          {error}
        </AppText>
      ) : null}
    </Screen>
  );
}
