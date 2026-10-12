import { Tabs } from "expo-router";
import { CircleHelp, ClipboardList, Inbox } from "lucide-react-native";
import { useT } from "../../i18n";
import { useApp } from "../../state/app";
import { size, typography, useColors } from "../../ui/theme";

/** Three tabs, labels always shown, 64 px high. The Outbox carries a count of what is waiting. */
export default function TabsLayout() {
  const colors = useColors();
  const t = useT();
  const { pending } = useApp();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.subtleForeground,
        tabBarLabelStyle: {
          fontFamily: typography.caption.fontFamily,
          fontSize: 13,
          marginBottom: 6,
        },
        tabBarStyle: {
          height: size.tabBar,
          paddingTop: 6,
          backgroundColor: colors.card,
          borderTopColor: colors.border,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t("tab.today"),
          tabBarIcon: ({ color }) => <ClipboardList size={24} color={color} strokeWidth={1.75} />,
        }}
      />
      <Tabs.Screen
        name="outbox"
        options={{
          title: t("tab.outbox"),
          tabBarBadge: pending > 0 ? pending : undefined,
          tabBarBadgeStyle: { backgroundColor: colors.signalAmberMark, color: "#0B2B27" },
          tabBarIcon: ({ color }) => <Inbox size={24} color={color} strokeWidth={1.75} />,
        }}
      />
      <Tabs.Screen
        name="help"
        options={{
          title: t("tab.help"),
          tabBarIcon: ({ color }) => <CircleHelp size={24} color={color} strokeWidth={1.75} />,
        }}
      />
    </Tabs>
  );
}
