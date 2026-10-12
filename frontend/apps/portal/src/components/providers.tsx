"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@vtrs/core";
import { useState, type ReactNode } from "react";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/lib/auth";
import { ElectionProvider } from "@/lib/election";
import { StepUpProvider } from "@/lib/step-up";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        retry: (count, error) => {
          // Do not hammer on refusals; only network blips and server errors are worth a retry.
          if (error instanceof ApiError && !error.isRetryable) return false;
          return count < 2;
        },
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ElectionProvider>
          <ToastProvider>
            <StepUpProvider>{children}</StepUpProvider>
          </ToastProvider>
        </ElectionProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
