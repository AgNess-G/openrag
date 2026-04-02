"use client";

import { Loader2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/auth-context";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isLoading, isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [redirectAttempts, setRedirectAttempts] = useState(0);
  const [hasRedirected, setHasRedirected] = useState(false);

  console.log(
    "ProtectedRoute - isLoading:",
    isLoading,
    "isAuthenticated:",
    isAuthenticated,
    "isNoAuthMode:",
    isNoAuthMode,
    "isIbmAuthMode:",
    isIbmAuthMode,
    "pathname:",
    pathname,
    "redirectAttempts:",
    redirectAttempts,
  );

  // Reset redirect tracking when pathname changes
  useEffect(() => {
    setHasRedirected(false);
  }, [pathname]);

  useEffect(() => {
    if (isLoading) return;

    // Prevent redirect loops
    if (redirectAttempts >= 3) {
      console.error("Too many redirect attempts, stopping to prevent loop");
      return;
    }

    if (!isAuthenticated) {
      if (isNoAuthMode) return;
      
      if (isIbmAuthMode) {
        if (!hasRedirected) {
          setHasRedirected(true);
          setRedirectAttempts((prev) => prev + 1);
          router.push("/unauthorized");
        }
        return;
      }
      
      if (!hasRedirected) {
        setHasRedirected(true);
        setRedirectAttempts((prev) => prev + 1);
        const redirectUrl = `/login?redirect=${encodeURIComponent(pathname)}`;
        router.push(redirectUrl);
      }
    }
  }, [isLoading, isAuthenticated, isNoAuthMode, isIbmAuthMode, router, pathname, redirectAttempts, hasRedirected]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  if (isNoAuthMode) {
    return <>{children}</>;
  }

  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
