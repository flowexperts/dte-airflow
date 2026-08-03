"use client";

import { Button, Dropdown, Field, Input, Panel, PanelHead, Segmented } from "@/components/ui";
import { FieldPicker } from "@/components/ui";
import type { ContractType, QualityContract } from "@/lib/api";
import { useSchemas } from "./schema-context";

const CONTRACT_TYPE_OPTIONS: { value: ContractType; label: string }[] = [
  { value: "row_count_between", label: "Row count between" },
  { value: "column_not_null", label: "Column not null" },
  { value: "column_unique", label: "Column unique" },
  { value: "column_in_range", label: "Column in range" },
  { value: "column_matches", label: "Column matches regex" },
];

const SEVERITY_OPTIONS: { value: "warn" | "fail"; label: string }[] = [
  { value: "fail", label: "Fail" },
  { value: "warn", label: "Warn" },
];

function ContractRow({
  contract,
  onChange,
  onRemove,
  fields,
}: {
  contract: QualityContract;
  onChange: (updated: QualityContract) => void;
  onRemove: () => void;
  fields: { name: string; type?: string }[];
}) {
  const needsColumn = contract.type !== "row_count_between";

  return (
    <div className="px-4 py-3 border-b border-border last:border-b-0 flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        {/* Contract type */}
        <div className="w-48 shrink-0">
          <Dropdown<ContractType>
            value={contract.type}
            onChange={(type) => {
              const next: QualityContract = { ...contract, type };
              // Clear params not relevant to the new type
              if (type === "row_count_between") {
                delete next.column;
                delete next.regex;
              } else if (type !== "column_in_range") {
                delete next.min;
                delete next.max;
              }
              if (type !== "column_matches") {
                delete next.regex;
              }
              onChange(next);
            }}
            options={CONTRACT_TYPE_OPTIONS}
          />
        </div>

        {/* Column picker (hidden for row_count_between) */}
        {needsColumn && (
          <div className="flex-1">
            <FieldPicker
              value={contract.column ?? ""}
              onChange={(column) => onChange({ ...contract, column })}
              options={fields}
              placeholder="column…"
            />
          </div>
        )}

        {/* Severity toggle */}
        <Segmented<"warn" | "fail">
          value={contract.severity}
          onChange={(severity) => onChange({ ...contract, severity })}
          options={SEVERITY_OPTIONS}
        />

        {/* Remove button */}
        <button
          type="button"
          aria-label="Remove contract"
          onClick={onRemove}
          className="text-subtle hover:text-red transition-colors text-[16px] leading-none px-1"
        >
          ×
        </button>
      </div>

      {/* Type-specific params */}
      {(contract.type === "row_count_between" || contract.type === "column_in_range") && (
        <div className="flex items-center gap-2 pl-0">
          <Field label="Min" className="flex-1">
            <Input
              type="number"
              value={contract.min ?? ""}
              onChange={(e) => {
                const next = { ...contract };
                if (e.target.value === "") {
                  delete next.min;
                } else {
                  next.min = Number(e.target.value);
                }
                onChange(next);
              }}
              placeholder="0"
            />
          </Field>
          <Field label="Max" className="flex-1">
            <Input
              type="number"
              value={contract.max ?? ""}
              onChange={(e) => {
                const next = { ...contract };
                if (e.target.value === "") {
                  delete next.max;
                } else {
                  next.max = Number(e.target.value);
                }
                onChange(next);
              }}
              placeholder="any"
            />
          </Field>
        </div>
      )}

      {contract.type === "column_matches" && (
        <Field label="Regex pattern">
          <Input
            value={contract.regex ?? ""}
            onChange={(e) => onChange({ ...contract, regex: e.target.value })}
            placeholder="^[A-Z]{2}[0-9]+$"
            className="font-mono"
          />
        </Field>
      )}
    </div>
  );
}

export function QualityContractsPanel({
  contracts,
  onChange,
}: {
  contracts: QualityContract[];
  onChange: (contracts: QualityContract[]) => void;
}) {
  const { allFields } = useSchemas();
  const fieldOptions = allFields.map((f) => ({ name: f.name, type: f.type }));

  const addContract = () => {
    const newContract: QualityContract = {
      id: crypto.randomUUID(),
      type: "column_not_null",
      severity: "fail",
    };
    onChange([...contracts, newContract]);
  };

  const updateContract = (id: string, updated: QualityContract) => {
    onChange(contracts.map((c) => (c.id === id ? updated : c)));
  };

  const removeContract = (id: string) => {
    onChange(contracts.filter((c) => c.id !== id));
  };

  return (
    <Panel>
      <PanelHead
        label="Quality contracts"
        count={contracts.length > 0 ? contracts.length : undefined}
      />
      {contracts.length === 0 ? (
        <div className="px-4 py-4 text-sm text-subtle">
          No contracts defined. Add one to validate data after each run.
        </div>
      ) : (
        <div>
          {contracts.map((contract) => (
            <ContractRow
              key={contract.id}
              contract={contract}
              fields={fieldOptions}
              onChange={(updated) => updateContract(contract.id, updated)}
              onRemove={() => removeContract(contract.id)}
            />
          ))}
        </div>
      )}
      <div className="px-4 py-3 border-t border-border">
        <Button variant="ghost" size="sm" onClick={addContract}>
          + Add contract
        </Button>
      </div>
    </Panel>
  );
}
