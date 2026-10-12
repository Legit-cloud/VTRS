import Image from "next/image";
import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4 py-10">
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-72 bg-gradient-to-b from-glow/40 to-transparent"
      />
      <div className="tally-bg absolute inset-0 opacity-40" aria-hidden />
      <main className="relative w-full max-w-[440px]">
        <div className="mb-8 flex items-center gap-3">
          <Image src="/logo-mark.svg" alt="" width={44} height={44} priority />
          <span className="text-h1 font-extrabold tracking-tight">VTRS</span>
        </div>
        <div className="rounded-xl border border-border bg-card p-6 shadow-float sm:p-8">
          {children}
        </div>
        <p className="mt-6 text-center text-caption text-subtle-foreground">
          Results shown are provisional party data, not an official declaration.
        </p>
      </main>
    </div>
  );
}
