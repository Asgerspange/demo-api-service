import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import api from '@/lib/axios'
import { toValue, type MaybeRefOrGetter } from 'vue';

export { api }

export function useApi() {
    const queryClient = useQueryClient()

    /* -------------------- GET -------------------- */
    function useGet<T>(
        key: unknown[],
        url: MaybeRefOrGetter<string>, 
        params?: MaybeRefOrGetter<Record<string, any>>,
        enabled: MaybeRefOrGetter<boolean> = true
    ) {
        return useQuery({
            queryKey: key,
            enabled: () => toValue(enabled),
            retry: (failureCount, error: any) => {
                if (error.response?.status === 403) return false; 
                return failureCount < 3;
            },
            queryFn: async () => {
                const resolvedUrl = toValue(url);
                const resolvedParams = toValue(params);
                const { data } = await api.get<T>(resolvedUrl, { params: resolvedParams });
                return data;
            }
        });
    }

    /* -------------------- POST -------------------- */
    function usePost<T, P = unknown>(
        invalidateKeys: unknown[]
    ) {
        return useMutation({
            mutationFn: async ({ url, payload }: { url: string; payload: P }) => {
                const config = payload instanceof FormData 
                    ? { headers: { 'Content-Type': 'multipart/form-data' } } 
                    : {};
                
                const { data } = await api.post<T>(url, payload, config)
                return data
            },
            onSuccess: () => {
                queryClient.invalidateQueries({ queryKey: invalidateKeys })
            }
        })
    }

    /* -------------------- PUT -------------------- */
    function usePut<T, P = unknown>(
        invalidateKeys: unknown[]
    ) {
        return useMutation({
            mutationFn: async ({ url, payload }: { url: string; payload: P }) => {
                const config = payload instanceof FormData 
                    ? { headers: { 'Content-Type': 'multipart/form-data' } } 
                    : {};
                const { data } = await api.put<T>(url, payload, config)
                return data
            },
            onSuccess: () => {
                queryClient.invalidateQueries({ queryKey: invalidateKeys })
            }
        })
    }

    /* -------------------- PATCH -------------------- */
    function usePatch<T, P = unknown>(
        invalidateKeys: unknown[]
    ) {
        return useMutation({
            mutationFn: async ({ url, payload }: { url: string; payload: P }) => {
                const { data } = await api.patch<T>(url, payload)
                return data
            },
            onSuccess: () => {
                queryClient.invalidateQueries({ queryKey: invalidateKeys })
            }
        })
    }

    /* -------------------- DELETE -------------------- */
    function useDelete(
        invalidateKeys: unknown[]
    ) {
        return useMutation({
            mutationFn: async (url: string) => {
                await api.delete(url)
            },
            onSuccess: () => {
                queryClient.invalidateQueries({ queryKey: invalidateKeys })
            }
        })
    }

    return {
        useGet,
        usePost,
        usePut,
        usePatch,
        useDelete
    }
}