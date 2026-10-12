import type { StatusView } from "@vtrs/core";
import { useRouter } from "expo-router";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Circle,
  Clock,
  Flag,
  RefreshCw,
  WifiOff,
  type LucideIcon,
} from "lucide-react-native";
import { useEffect, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Svg, { Circle as SvgCircle, Path } from "react-native-svg";
import { useT } from "../i18n";
import { AppText, radius, size, space, useColors } from "./theme";

const ICONS: Record<string, LucideIcon> = {
  clock: Clock,
  "refresh-cw": RefreshCw,
  "check-circle-2": CheckCircle2,
  "alert-circle": AlertCircle,
  flag: Flag,
  circle: Circle,
};

export function Icon({
  name,
  size: px = 24,
  color,
}: {
  name: string;
  size?: number;
  color: string;
}) {
  const Glyph = ICONS[name] ?? Circle;
  return <Glyph size={px} color={color} strokeWidth={1.75} />;
}

// ---- layout -------------------------------------------------------------------------------

/**
 * One task per screen: content scrolls, the primary action does not. The keyboard pushes the
 * action up with the content.
 */
export function Screen({
  children,
  footer,
  canvas,
  scroll = true,
}: {
  children: ReactNode;
  footer?: ReactNode;
  /** White for entry screens, the soft canvas for list screens. */
  canvas?: boolean;
  scroll?: boolean;
}) {
  const colors = useColors();
  const bg = canvas ? colors.canvas : colors.background;
  const body = (
    <View
      style={{ paddingHorizontal: size.screenPadding, paddingBottom: space[24], gap: space[16] }}
    >
      {children}
    </View>
  );
  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: bg }}
      edges={["top", "left", "right", "bottom"]}
    >
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        {scroll ? (
          <ScrollView
            style={{ flex: 1 }}
            contentContainerStyle={{ paddingTop: space[8], flexGrow: 1 }}
            keyboardShouldPersistTaps="handled"
          >
            {body}
          </ScrollView>
        ) : (
          <View style={{ flex: 1, paddingTop: space[8] }}>{body}</View>
        )}
        {footer ? (
          <View
            style={{
              paddingHorizontal: size.screenPadding,
              paddingTop: space[12],
              paddingBottom: space[16],
              gap: space[8],
              backgroundColor: bg,
            }}
          >
            {footer}
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/** Back button with a 48 px hit area, wordmark on the right. */
export function TopBar({ back = true, right }: { back?: boolean; right?: ReactNode }) {
  const colors = useColors();
  const router = useRouter();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        minHeight: size.hit,
      }}
    >
      {back ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
          hitSlop={4}
          style={({ pressed }) => ({
            width: size.hit,
            height: size.hit,
            borderRadius: size.hit / 2,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: pressed ? colors.primarySoftHover : colors.primarySoft,
          })}
        >
          <ArrowLeft size={24} color={colors.primarySoftForeground} strokeWidth={1.75} />
        </Pressable>
      ) : (
        <View />
      )}
      {right ?? (
        <AppText variant="heading" tone="strong" style={{ letterSpacing: 0.5 }}>
          VTRS
        </AppText>
      )}
    </View>
  );
}

// ---- actions ------------------------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";

export function Button({
  title,
  onPress,
  variant = "primary",
  loading,
  disabled,
  forward,
  icon,
}: {
  title: string;
  onPress: () => void;
  variant?: ButtonVariant;
  loading?: boolean;
  disabled?: boolean;
  /** Trailing arrow, only on forward-moving primary buttons in a flow. */
  forward?: boolean;
  icon?: ReactNode;
}) {
  const colors = useColors();
  const off = disabled || loading;
  const palette = {
    primary: {
      bg: off ? colors.primaryDisabled : colors.primary,
      pressed: colors.primaryHover,
      fg: off ? colors.mutedForeground : colors.primaryForeground,
      border: "transparent",
    },
    secondary: {
      bg: off ? colors.muted : colors.primarySoft,
      pressed: colors.primarySoftHover,
      fg: off ? colors.mutedForeground : colors.primarySoftForeground,
      border: "transparent",
    },
    outline: {
      bg: "transparent",
      pressed: colors.muted,
      fg: off ? colors.mutedForeground : colors.foreground,
      border: colors.input,
    },
    ghost: {
      bg: "transparent",
      pressed: colors.primarySoft,
      fg: off ? colors.mutedForeground : colors.primaryHover,
      border: "transparent",
    },
    danger: {
      bg: colors.destructive,
      pressed: colors.destructive,
      fg: colors.destructiveForeground,
      border: "transparent",
    },
  }[variant];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      accessibilityLabel={title}
      disabled={off}
      onPress={onPress}
      style={({ pressed }): ViewStyle => ({
        height: size.control,
        borderRadius: radius.control,
        backgroundColor: pressed ? palette.pressed : palette.bg,
        borderWidth: variant === "outline" ? 1.5 : 0,
        borderColor: palette.border,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        gap: space[8],
        paddingHorizontal: space[20],
      })}
    >
      {loading ? (
        <ActivityIndicator color={palette.fg} />
      ) : (
        <>
          {icon}
          <AppText variant="bodyLg" style={{ color: palette.fg, fontFamily: "Onest_600" }}>
            {title}
          </AppText>
          {forward ? <ArrowRight size={20} color={palette.fg} strokeWidth={1.75} /> : null}
        </>
      )}
    </Pressable>
  );
}

// ---- inputs -------------------------------------------------------------------------------

interface FieldProps extends Omit<TextInputProps, "style"> {
  label: string;
  helper?: string;
  error?: string | null;
  prefix?: ReactNode;
  numeric?: boolean;
}

/** Mint fill, ink-400 border so the field shows in direct sun, label above, fix below. */
export function Field({ label, helper, error, prefix, numeric, ...input }: FieldProps) {
  const colors = useColors();
  return (
    <View style={{ gap: space[4] }}>
      <AppText variant="label" tone="strong">
        {label}
      </AppText>
      <View style={{ flexDirection: "row", gap: space[8] }}>
        {prefix}
        <TextInput
          {...input}
          accessibilityLabel={label}
          accessibilityHint={helper}
          placeholderTextColor={colors.mutedForeground}
          keyboardType={numeric ? "number-pad" : input.keyboardType}
          selectTextOnFocus={numeric || input.selectTextOnFocus}
          maxFontSizeMultiplier={1.3}
          style={{
            flex: 1,
            height: size.control,
            borderRadius: radius.control,
            borderWidth: 1.5,
            borderColor: error ? colors.destructive : colors.input,
            backgroundColor: colors.inputFill,
            paddingHorizontal: space[16],
            color: colors.foreground,
            fontFamily: numeric ? "Onest_800" : "Onest_400",
            fontSize: numeric ? 26 : 17,
            textAlign: numeric ? "right" : "left",
            fontVariant: numeric ? ["tabular-nums"] : undefined,
          }}
        />
      </View>
      {error ? (
        <View style={{ flexDirection: "row", gap: space[4], alignItems: "flex-start" }}>
          <AlertCircle size={16} color={colors.signalRedText} style={{ marginTop: 2 }} />
          <AppText variant="caption" tone="danger" style={{ flex: 1 }}>
            {error}
          </AppText>
        </View>
      ) : helper ? (
        <AppText variant="caption" tone="subtle">
          {helper}
        </AppText>
      ) : null}
    </View>
  );
}

// ---- status -------------------------------------------------------------------------------

const TONES = {
  ink: ["signalInkSoft", "signalInkText"],
  blue: ["signalBlueSoft", "signalBlueText"],
  teal: ["signalTealSoft", "signalTealText"],
  amber: ["signalAmberSoft", "signalAmberText"],
  red: ["signalRedSoft", "signalRedText"],
} as const;

/** Icon and word, never a colour alone. */
export function StatusChip({ status, label }: { status: StatusView; label?: string }) {
  const colors = useColors();
  const [soft, text] = TONES[status.tone];
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: space[4],
        alignSelf: "flex-start",
        height: 28,
        paddingHorizontal: space[8],
        borderRadius: radius.chip,
        backgroundColor: colors[soft],
      }}
    >
      <Icon name={status.icon} size={14} color={colors[text]} />
      <AppText variant="caption" style={{ color: colors[text], fontFamily: "Onest_600" }}>
        {label ?? status.label}
      </AppText>
    </View>
  );
}

export function IconBadge({
  children,
  tone = "brand",
}: {
  children: ReactNode;
  tone?: "brand" | "amber" | "red";
}) {
  const colors = useColors();
  const bg =
    tone === "brand"
      ? colors.brand
      : tone === "amber"
        ? colors.signalAmberSoft
        : colors.signalRedSoft;
  return (
    <View
      style={{
        width: 64,
        height: 64,
        borderRadius: 32,
        backgroundColor: bg,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {children}
    </View>
  );
}

export function OfflineBanner({ online, sending }: { online: boolean; sending: number }) {
  const colors = useColors();
  const t = useT();
  if (online && sending === 0) return null;
  const back = online;
  return (
    <View
      accessibilityRole="alert"
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: space[8],
        paddingHorizontal: space[16],
        paddingVertical: space[8],
        borderRadius: radius.control,
        backgroundColor: back ? colors.signalTealSoft : colors.signalAmberSoft,
      }}
    >
      <WifiOff size={18} color={back ? colors.signalTealText : colors.signalAmberText} />
      <AppText
        variant="label"
        style={{ flex: 1, color: back ? colors.signalTealText : colors.signalAmberText }}
      >
        {back
          ? t("offline.back", {
              count: sending,
              noun: sending === 1 ? t("noun.result") : t("noun.results"),
            })
          : t("offline.banner")}
      </AppText>
    </View>
  );
}

// ---- capture --------------------------------------------------------------------------------

export function StepBar({ steps, current }: { steps: string[]; current: number }) {
  const colors = useColors();
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel={`${current + 1} / ${steps.length}: ${steps[current]}`}
      style={{ flexDirection: "row", gap: space[8] }}
    >
      {steps.map((name, i) => (
        <View key={name} style={{ flex: 1, gap: space[4] }}>
          <View
            style={{
              height: 6,
              borderRadius: 3,
              backgroundColor: i <= current ? colors.primary : colors.track,
            }}
          />
          <AppText
            variant="caption"
            tone={i === current ? "default" : "muted"}
            style={{ fontFamily: i === current ? "Onest_600" : "Onest_500" }}
          >
            {name}
          </AppText>
        </View>
      ))}
    </View>
  );
}

const AnimatedPath = Animated.createAnimatedComponent(Path);

/** The one signature moment: the check draws itself in 360 ms. */
export function SuccessMark({ tone = "teal" }: { tone?: "teal" | "amber" | "red" }) {
  const colors = useColors();
  const [progress] = useState(() => new Animated.Value(0));
  useEffect(() => {
    Animated.timing(progress, {
      toValue: 1,
      duration: 360,
      easing: Easing.bezier(0.2, 0.8, 0.2, 1),
      useNativeDriver: false,
    }).start();
  }, [progress]);
  const offset = progress.interpolate({ inputRange: [0, 1], outputRange: [40, 0] });
  const fill =
    tone === "teal"
      ? colors.primary
      : tone === "amber"
        ? colors.signalAmberSoft
        : colors.signalRedSoft;
  const stroke =
    tone === "teal"
      ? colors.primaryForeground
      : tone === "amber"
        ? colors.signalAmberText
        : colors.signalRedText;
  const ring = tone === "teal" ? colors.track : "transparent";
  return (
    <Svg width={120} height={120} viewBox="0 0 120 120" accessibilityElementsHidden>
      <SvgCircle cx={60} cy={60} r={58} fill="none" stroke={ring} strokeWidth={2} />
      <SvgCircle cx={60} cy={60} r={46} fill={fill} />
      <AnimatedPath
        d="M40 62 L55 77 L82 47"
        fill="none"
        stroke={stroke}
        strokeWidth={7}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="40"
        strokeDashoffset={offset as unknown as number}
      />
    </Svg>
  );
}
