import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { PurchaseOrder, Vendor } from '../types';

// Session-level cache for reference data used to enrich run views (PO line
// descriptions, vendor names). Billing figures shown on a run come from the
// run's own stage output, never from this cache.
let vendorsP: Promise<Vendor[]> | null = null;
let posP: Promise<PurchaseOrder[]> | null = null;

export function invalidateReference() {
  vendorsP = null;
  posP = null;
}

function useCached<T>(get: () => Promise<T>): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    get()
      .then((x) => alive && setV(x))
      .catch(() => {
        /* enrichment only; ignore */
      });
    return () => {
      alive = false;
    };
  }, [get]);
  return v;
}

const getVendors = () => {
  if (!vendorsP) vendorsP = api.vendors().catch((e) => ((vendorsP = null), Promise.reject(e)));
  return vendorsP;
};
const getPos = () => {
  if (!posP) posP = api.pos().catch((e) => ((posP = null), Promise.reject(e)));
  return posP;
};

export const useVendors = () => useCached(getVendors);
export const usePurchaseOrders = () => useCached(getPos);
