import type { HumanGate } from "./types";

// Shared by the 运行 list (`Console.tsx`'s `humanApprovalLabel`) and the demo
// landing page (`DemoTour.tsx`): both need to turn "every gate this Run
// opened" into "did one of them actually grant or withhold authority", and
// duplicating that judgment risked the two disagreeing about what counts as
// decided. Neither function renders evidence itself -- that stays the
// Evidence tab's job (see `RunDetail` in `Console.tsx`).

export function findApprovedGate(gates: HumanGate[]): HumanGate | null {
  return gates.find((gate) => gate.status === "approved") ?? null;
}

export function findDecidedAgainstGate(gates: HumanGate[]): HumanGate | null {
  return gates.find((gate) => gate.status === "rejected" || gate.status === "expired") ?? null;
}
