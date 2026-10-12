import { useState } from "react";
import { Alert, Linking, ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useApp } from "../../state/app";
import { Button } from "../../ui/kit";
import { AppText, radius, size, space, useColors } from "../../ui/theme";

const SUPPORT_PHONE = process.env.EXPO_PUBLIC_SUPPORT_PHONE ?? "";

const GUIDES: [string, string][] = [
  [
    "Working without a network",
    "You can enter results and take the photo with no network at all. The result waits on your phone, marked Waiting to send, and goes by itself when you have a signal. You can close the app.",
  ],
  [
    "Taking a good photo of the sheet",
    "Fill the frame with the whole sheet. Stand in good light with no shadow across it. Keep the phone flat and still, then check the numbers are readable before you use the photo.",
  ],
  [
    "If the numbers do not add up",
    "The app tells you when the candidates' votes do not equal the valid votes, or more votes were cast than voters accredited. Check the sheet. If it really says that, you can still send it. An officer will look at it.",
  ],
  [
    "If you made a mistake after sending",
    "A sent result cannot be edited. Open Today and choose Send a correction. Your officer sees both versions.",
  ],
];

export default function Help() {
  const { me, pending, signOut, deviceId } = useApp();
  const colors = useColors();
  const [busy, setBusy] = useState(false);

  const confirmSignOut = () => {
    const message =
      pending > 0
        ? `${pending} ${pending === 1 ? "result is" : "results are"} still on this phone and have not been sent. Sign out only after they are sent, or they will wait until you sign in again.`
        : "You will need your password to sign in again.";
    Alert.alert("Sign out?", message, [
      { text: "Stay signed in", style: "cancel" },
      {
        text: "Sign out",
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
        <AppText variant="display">Help</AppText>

        {SUPPORT_PHONE ? (
          <View style={{ gap: space[12] }}>
            <Button
              title="Call support"
              onPress={() => void Linking.openURL(`tel:${SUPPORT_PHONE}`)}
            />
            <Button
              title="Message on WhatsApp"
              variant="secondary"
              onPress={() =>
                void Linking.openURL(`https://wa.me/${SUPPORT_PHONE.replace(/\D/g, "")}`)
              }
            />
          </View>
        ) : (
          <AppText variant="body" tone="subtle">
            Your party officer is your first point of contact. Support numbers appear here when your
            party sets them.
          </AppText>
        )}

        {GUIDES.map(([title, body]) => (
          <View
            key={title}
            style={{
              backgroundColor: colors.card,
              borderRadius: radius.card,
              padding: space[20],
              gap: space[8],
              borderWidth: 1,
              borderColor: colors.border,
            }}
          >
            <AppText variant="heading">{title}</AppText>
            <AppText variant="body" tone="subtle">
              {body}
            </AppText>
          </View>
        ))}

        <View style={{ gap: space[8], marginTop: space[8] }}>
          {me ? (
            <AppText variant="caption" tone="muted">
              Signed in as {me.full_name}
              {deviceId ? ` · device ${deviceId.slice(0, 8)}` : ""}
            </AppText>
          ) : null}
          <Button title="Sign out" variant="outline" loading={busy} onPress={confirmSignOut} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
