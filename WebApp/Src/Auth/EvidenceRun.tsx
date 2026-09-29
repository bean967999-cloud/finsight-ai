import { createContext, useContext, useState, type ReactNode } from "react";
import type { EvidenceRun } from "../Api/Evidence";

interface EvidenceRunValue {
  run: EvidenceRun | null;
  setRun: (run: EvidenceRun | null) => void;
}

const EvidenceRunContext = createContext<EvidenceRunValue | null>(null);

export function EvidenceRunProvider({ children }: { children: ReactNode }) {
  const [run, setRun] = useState<EvidenceRun | null>(null);
  return <EvidenceRunContext.Provider value={{ run, setRun }}>
    {children}
  </EvidenceRunContext.Provider>;
}

export function useEvidenceRun(): EvidenceRunValue {
  const value = useContext(EvidenceRunContext);
  if (!value) throw new Error("EvidenceRunProvider 未挂载");
  return value;
}
