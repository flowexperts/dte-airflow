"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { readToken } from "@/lib/api";
import { LandingPage } from "@/components/marketing/landing-page";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    if (readToken()) router.replace("/pipelines");
  }, [router]);

  return <LandingPage />;
}
