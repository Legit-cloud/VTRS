import type { ReactNode } from "react";
import { View } from "react-native";
import { useApp } from "../state/app";
import { useCapture } from "../state/capture";
import { OfflineBanner, Screen, StepBar, TopBar } from "./kit";
import { AppText, space } from "./theme";

export const STEPS = ["Votes", "Totals", "Photo", "Review"];

/** Shared frame for the four entry steps: step bar on top, one pinned action below. */
export function CaptureFrame({
  step,
  title,
  helper,
  footer,
  children,
}: {
  step: number;
  title: string;
  helper?: string;
  footer: ReactNode;
  children: ReactNode;
}) {
  const { assignment, contest } = useCapture();
  const { online, pending } = useApp();
  return (
    <Screen footer={footer} canvas>
      <TopBar />
      <StepBar steps={STEPS} current={step} />
      <View style={{ gap: space[4] }}>
        <AppText variant="caption" tone="muted">
          {contest.title} · {assignment.polling_unit.name}
        </AppText>
        <AppText variant="title">{title}</AppText>
        {helper ? (
          <AppText variant="body" tone="subtle">
            {helper}
          </AppText>
        ) : null}
      </View>
      {!online ? <OfflineBanner online={online} sending={pending} /> : null}
      {children}
    </Screen>
  );
}
