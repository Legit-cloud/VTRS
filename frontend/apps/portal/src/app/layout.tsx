import type { Metadata, Viewport } from "next";
import { Onest } from "next/font/google";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import "./globals.css";

const onest = Onest({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "VTRS", template: "%s · VTRS" },
  description: "Vote Tracking and Recording. Results shown are provisional party data.",
  icons: { icon: "/logo-mark.svg" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={onest.variable}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
