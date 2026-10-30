import type { UseCase } from "@/lib/use-cases";

/** A use case's pipeline, drawn the way its steps read in the builder. */
export function PipelineCard({ steps }: { steps: UseCase["steps"] }) {
  return (
    <div className="pipe" aria-label="pipeline steps">
      {steps.map((s) => (
        <div key={s.op + s.expr} className={`stp${s.op === "source" || s.op === "destination" ? " io" : ""}`}>
          <b>{s.op}</b><span>{s.expr}</span>
        </div>
      ))}
    </div>
  );
}
