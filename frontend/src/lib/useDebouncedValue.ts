import { useEffect, useState } from "react";

/** Keep typing immediate while coalescing server search requests; timers cancel on scope changes/unmount. */
export function useDebouncedValue<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
