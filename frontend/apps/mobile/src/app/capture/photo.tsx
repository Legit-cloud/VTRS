import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { Camera } from "lucide-react-native";
import { useRef, useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { preparePhoto } from "../../platform/files";
import { useCapture } from "../../state/capture";
import { Button, IconBadge, TopBar, StepBar } from "../../ui/kit";
import { AppText, size, space, useColors } from "../../ui/theme";
import { STEPS } from "../../ui/capture-frame";
import { formatBytes } from "@vtrs/core";

const CORNER = 28;

/** Four corner marks that say "fit the whole sheet in here". */
function FrameGuide() {
  const mark = {
    position: "absolute" as const,
    width: CORNER,
    height: CORNER,
    borderColor: "#FFFFFF",
  };
  return (
    <View
      pointerEvents="none"
      style={{ position: "absolute", top: "12%", bottom: "22%", left: 24, right: 24 }}
    >
      <View style={[mark, { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4 }]} />
      <View style={[mark, { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4 }]} />
      <View style={[mark, { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4 }]} />
      <View style={[mark, { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4 }]} />
    </View>
  );
}

export default function PhotoStep() {
  const { draft, setPhoto } = useCapture();
  const router = useRouter();
  const colors = useColors();
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  async function shoot() {
    if (!camera.current || busy) return;
    setBusy(true);
    setError(null);
    try {
      const picture = await camera.current.takePictureAsync({
        quality: 0.9,
        skipProcessing: false,
      });
      setPhoto(await preparePhoto(picture.uri));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not take the photo. Try again.");
    } finally {
      setBusy(false);
    }
  }

  // Ask at the moment it is needed, after saying why.
  if (!permission?.granted) {
    const blocked = permission && !permission.canAskAgain;
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
        <View style={{ flex: 1, padding: size.screenPadding, gap: space[16] }}>
          <TopBar />
          <StepBar steps={STEPS} current={2} />
          <View style={{ flex: 1, justifyContent: "center", gap: space[16] }}>
            <IconBadge>
              <Camera size={30} color="#FFFFFF" strokeWidth={1.75} />
            </IconBadge>
            <AppText variant="title">Allow the camera</AppText>
            <AppText variant="bodyLg" tone="subtle">
              The camera is used only to photograph the result sheet. The photo goes to your party
              with the numbers, so they can check them.
            </AppText>
          </View>
          <Button
            title={blocked ? "Open settings" : "Allow camera"}
            onPress={() => (blocked ? void Linking.openSettings() : void requestPermission())}
          />
        </View>
      </SafeAreaView>
    );
  }

  // A photo is held: show it, with the choice to retake.
  if (draft.photo) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
        <View style={{ flex: 1, padding: size.screenPadding, gap: space[16] }}>
          <TopBar />
          <StepBar steps={STEPS} current={2} />
          <AppText variant="title">Is the sheet readable?</AppText>
          <AppText variant="body" tone="subtle">
            Check every number can be read, then use the photo. Retake it if there is glare, a
            shadow, or it is cut off.
          </AppText>
          <Image
            source={{ uri: draft.photo.uri }}
            accessibilityLabel="Photo of the result sheet"
            resizeMode="contain"
            style={{ flex: 1, borderRadius: 16, backgroundColor: colors.muted }}
          />
          <AppText variant="caption" tone="muted" align="center">
            {draft.photo.width} × {draft.photo.height} · {formatBytes(draft.photo.size)}
          </AppText>
          <View style={{ gap: space[8] }}>
            <Button
              title="Use photo"
              forward
              onPress={() => router.push({ pathname: "/capture/review" })}
            />
            <Button title="Retake" variant="outline" onPress={() => setPhoto(null)} />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#000000" }}>
      <CameraView
        ref={camera}
        style={{ flex: 1 }}
        facing="back"
        onCameraReady={() => setReady(true)}
        onMountError={(e) => setError(e.message)}
      />
      <FrameGuide />
      <SafeAreaView
        edges={["top"]}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          paddingHorizontal: size.screenPadding,
        }}
      >
        <TopBar />
      </SafeAreaView>
      <SafeAreaView
        edges={["bottom"]}
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          alignItems: "center",
          gap: space[12],
          paddingBottom: space[16],
        }}
      >
        <View
          style={{
            backgroundColor: "rgba(0,0,0,0.6)",
            paddingHorizontal: space[16],
            paddingVertical: space[8],
            borderRadius: 999,
          }}
        >
          <AppText variant="label" style={{ color: "#FFFFFF" }}>
            Fill the frame · No shadows
          </AppText>
        </View>
        {error ? (
          <AppText variant="body" style={{ color: "#FFFFFF" }} accessibilityRole="alert">
            {error}
          </AppText>
        ) : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Take photo"
          disabled={!ready || busy}
          onPress={shoot}
          style={{
            width: 72,
            height: 72,
            borderRadius: 36,
            borderWidth: 4,
            borderColor: "#FFFFFF",
            alignItems: "center",
            justifyContent: "center",
            opacity: !ready || busy ? 0.5 : 1,
          }}
        >
          <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: "#FFFFFF" }} />
        </Pressable>
      </SafeAreaView>
    </View>
  );
}
