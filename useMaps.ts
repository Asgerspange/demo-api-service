import { computed, ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { useQueryClient } from '@tanstack/vue-query'

export default function useMaps() {
    const { useGet } = useApi()
    const queryClient = useQueryClient()

    const mapId = ref<number | null>(null)

    const mapQuery = useGet<any[]>(
        ['maps'],
        '/api/maps'
    )

    // Ensure the queryKey is unique per ID so TanStack Query can track it
    const findQuery = useGet<any>(
        ['map', mapId], 
        computed(() => mapId.value ? `/api/maps/${mapId.value}` : ''),
        undefined,
        computed(() => !!mapId.value)
    )

    class Maps {
        static get() {
            return mapQuery
        }

        static find(id: number) {
            mapId.value = id
            return findQuery
        }

        static async refresh() {
            return queryClient.invalidateQueries({ queryKey: ['maps'] })
        }
    }

    return { Maps }
}