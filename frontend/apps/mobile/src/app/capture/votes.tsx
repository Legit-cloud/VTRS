import { useRouter } from "expo-router";
import { View } from "react-native";
import { parseCount } from "../../core/capture";
import { useCapture } from "../../state/capture";
import { CaptureFrame } from "../../ui/capture-frame";
import { Button, Field } from "../../ui/kit";
import { AppText, radius, space, useColors } from "../../ui/theme";

export default function Votes() {
  const { contest, draft, setVote } = useCapture();
  const router = useRouter();
  const colors = useColors();
  const blank = contest.candidates.filter((c) => parseCount(draft.votes[c.id]) === null).length;
  const ordered = [...contest.candidates].sort((a, b) => a.ballot_order - b.ballot_order);

  return (
    <CaptureFrame
      step={0}
      title="Votes for each candidate"
      helper="Copy the number beside each name from the result sheet. Write 0 if a candidate has none."
      footer={
        <Button
          title="Next"
          forward
          disabled={blank > 0}
          onPress={() => router.push({ pathname: "/capture/totals" })}
        />
      }
    >
      {ordered.map((c) => (
        <View
          key={c.id}
          style={{
            backgroundColor: colors.card,
            borderRadius: radius.card,
            padding: space[16],
            gap: space[12],
            borderWidth: 1,
            borderColor: colors.border,
          }}
        >
          <View>
            <AppText variant="heading">{c.name}</AppText>
            <AppText variant="body" tone="subtle">
              {c.party_acronym}
            </AppText>
          </View>
          <Field
            label="Votes"
            numeric
            value={draft.votes[c.id] ?? ""}
            onChangeText={(t) => setVote(c.id, t)}
            maxLength={7}
            placeholder="0"
            returnKeyType="next"
          />
        </View>
      ))}
    </CaptureFrame>
  );
}
