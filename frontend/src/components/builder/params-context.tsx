"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { PipelineParam } from "@/lib/api";

const Ctx = createContext<PipelineParam[]>([]);

export function PipelineParamsProvider({
  params,
  children,
}: {
  params: PipelineParam[] | undefined;
  children: ReactNode;
}) {
  return <Ctx.Provider value={params ?? []}>{children}</Ctx.Provider>;
}

/** Declared pipeline inputs, for the variable picker in filter/map editors. */
export function usePipelineParams(): PipelineParam[] {
  return useContext(Ctx);
}
