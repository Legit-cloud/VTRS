import {
  light,
  radius,
  size,
  space,
  typography,
  type ThemeColors,
} from "@vtrs/design-system/mobile/theme";
import { createContext, useContext, type ReactNode } from "react";
import { Text, type StyleProp, type TextProps, type TextStyle } from "react-native";

export { radius, size, space, typography };

const ThemeContext = createContext<ThemeColors>(light);

/**
 * The agent app is light by default: it is used outdoors, in sun. The dark theme exists in the
 * tokens for night use; wire a switch here when it is wanted.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  return <ThemeContext.Provider value={light}>{children}</ThemeContext.Provider>;
}

export const useColors = (): ThemeColors => useContext(ThemeContext);

export type Variant =
  "display" | "title" | "heading" | "bodyLg" | "body" | "label" | "caption" | "numeral";

type Tone = "default" | "muted" | "subtle" | "primary" | "danger" | "onPrimary" | "strong";

interface Props extends TextProps {
  variant?: Variant;
  tone?: Tone;
  align?: TextStyle["textAlign"];
  style?: StyleProp<TextStyle>;
}

/** Every piece of text goes through here so the type scale and Onest stay in one place. */
export function AppText({ variant = "body", tone = "default", align, style, ...props }: Props) {
  const colors = useColors();
  const spec = typography[variant];
  const color = {
    default: colors.foreground,
    strong: colors.strongForeground,
    muted: colors.mutedForeground,
    subtle: colors.subtleForeground,
    primary: colors.primary,
    danger: colors.signalRedText,
    onPrimary: colors.primaryForeground,
  }[tone];
  return (
    <Text
      {...props}
      // Scale with the OS text size, up to the 130% the design commits to.
      maxFontSizeMultiplier={1.3}
      style={[
        {
          fontFamily: spec.fontFamily,
          fontSize: spec.fontSize,
          lineHeight: spec.lineHeight,
          color,
          textAlign: align,
        },
        "fontVariant" in spec ? { fontVariant: [...spec.fontVariant] } : null,
        style,
      ]}
    />
  );
}
