import { createContext, useCallback, useContext, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

const PageStateContext = createContext<Map<string, unknown> | null>(null);

export function PageStateProvider({ children }: { children: ReactNode }) {
  const cache = useRef(new Map<string, unknown>());
  return <PageStateContext.Provider value={cache.current}>{children}</PageStateContext.Provider>;
}

export function usePageState<T>(key: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const cache = useContext(PageStateContext);
  if (!cache) throw new Error("PageStateProvider 未挂载");
  const [value, setValue] = useState<T>(() => cache.has(key) ? cache.get(key) as T
    : typeof initial === "function" ? (initial as () => T)() : initial);
  const current = useRef(value);
  const update = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    const resolved = typeof next === "function" ? (next as (previous: T) => T)(current.current) : next;
    current.current = resolved;
    cache.set(key, resolved);
    setValue(resolved);
  }, [cache, key]);
  return [value, update];
}
