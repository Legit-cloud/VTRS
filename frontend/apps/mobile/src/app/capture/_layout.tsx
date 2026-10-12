import { Redirect, Stack, useLocalSearchParams } from "expo-router";
import { CaptureProvider } from "../../state/capture";
import { useApp } from "../../state/app";

/** Finds the assignment and contest from the route, then holds the draft for the four steps. */
export default function CaptureLayout() {
  const { assignments } = useApp();
  const params = useLocalSearchParams<{ assignment?: string; contest?: string }>();
  const assignment = assignments?.find((a) => a.assignment_id === params.assignment);
  const contest = assignment?.contests.find((c) => c.id === params.contest);
  if (!assignment || !contest) return <Redirect href="/" />;
  return (
    <CaptureProvider assignment={assignment} contest={contest}>
      <Stack screenOptions={{ headerShown: false, animation: "slide_from_right" }} />
    </CaptureProvider>
  );
}
