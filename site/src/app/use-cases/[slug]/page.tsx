import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UseCasePage } from "@/components/marketing/use-case-page";
import { USE_CASES, findUseCase } from "@/lib/use-cases";

export function generateStaticParams() {
  return USE_CASES.map((u) => ({ slug: u.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const uc = findUseCase((await params).slug);
  if (!uc) return {};
  return {
    title: uc.title,
    description: uc.lede,
    alternates: { canonical: `/use-cases/${uc.slug}/` },
  };
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const uc = findUseCase((await params).slug);
  if (!uc) notFound();
  return <UseCasePage uc={uc} />;
}
