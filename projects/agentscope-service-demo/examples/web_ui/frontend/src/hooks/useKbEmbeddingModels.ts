import { useCallback, useEffect, useState } from "react";

import { client } from "@/api/client";
import type { DimensionPolicy, KbEmbeddingProvider } from "@/api";

/**
 * Fetches the list of embedding models a user can pick at KB-creation
 * time. Server-side already filtered by the manager's
 * :class:`DimensionPolicy`; the UI just renders.
 *
 * Refetches when ``refetchTrigger`` changes (e.g. after a credential
 * was created), mirroring the contract used by other selectors.
 */
export function useKbEmbeddingModels(refetchTrigger?: number) {
  const [providers, setProviders] = useState<KbEmbeddingProvider[]>([]);
  const [policy, setPolicy] = useState<DimensionPolicy | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // The portal catalog is authoritative: models must be manually typed,
      // configured and enabled before they appear here.  Do not merge the
      // legacy provider cards — an OpenAI-compatible provider otherwise
      // exposes unrelated static OpenAI embedding choices.
      const catalog = await client.get<{
        providers: KbEmbeddingProvider[];
        policy: DimensionPolicy;
      }>("/portal/knowledge-bases/embedding-models");
      setProviders(catalog.providers);
      setPolicy(catalog.policy);
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch, refetchTrigger]);

  return { providers, policy, loading, error, refetch };
}
