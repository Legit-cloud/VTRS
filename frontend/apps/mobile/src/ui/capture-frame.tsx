import type { ReactNode } from "react";
import { View } from "react-native";
import { useT } from "../i18n";
import { useApp } from "../state/app";
import { useCapture } from "../state/capture";
import { OfflineBanner, Screen, StepBar, TopBar } from "./kit";
import { AppText, space } from "./theme";

/** The four entry steps' names, in the agent's language. */
export function useSteps(): string[] {
  const t = useT();
  return [t("step.votes"), t("step.totals"), t("step.photo"), t("step.review")];
}

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
  const steps = useSteps();
  return (
    <Screen footer={footer} canvas>
      <TopBar />
      <StepBar steps={steps} current={step} />
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
