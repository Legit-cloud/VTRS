"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { me, status } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (status !== "authenticated" || !me) return;
    router.replace(me.role === "PLATFORM_ADMIN" ? "/platform" : "/war-room");
  }, [status, me, router]);
  return null;
}
