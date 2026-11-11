import { ref, reactive, computed } from 'vue';
import { useApi } from '@/composables/useApi';
import { useQueryClient } from '@tanstack/vue-query';
import { storeToRefs } from 'pinia';
import { useStore } from '@/store';

export default function useDemos() {
    const { useGet, usePost, useDelete, usePatch } = useApi();
    const store = useStore();
    const { selectedTeamId } = storeToRefs(store);
    const queryClient = useQueryClient();
    const hideFolderDemos = ref(false);
    const queryKey = reactive(['demos', { hideFolderDemos }]);
    const apiUrl = computed(() => {
        return `/api/demos?hideFolderDemos=${hideFolderDemos.value}`;
    });

    const demosQuery = useGet<any[]>(
        queryKey, 
        apiUrl,
        {
            refetchInterval: (query) => {
                const data = query.state.data;
                const hasProcessing = data?.some((demo: any) => demo.status);
                return hasProcessing ? 10000 : false;
            },
            refetchIntervalInBackground: true
        }
    );

    const createMutation = usePost<any, any>(['demos']);
    const deleteMutation = useDelete(['demos']);
    const updateMutation = usePatch<any, any>(['demos']);

    class Demos {
        static get(hideDemos = false) {
            hideFolderDemos.value = hideDemos;
            return demosQuery;
        }

        static show(id: number) {
            console.log(`Fetching demo with ID: ${id}`);
            return useGet<any>(
                ['demo', id], 
                `/api/demos/${id}`,
            );
        }

        static async create(payload: FormData) {
            if (!selectedTeamId.value) return;

            return await createMutation.mutateAsync({
                url: `/api/demos`,
                payload: payload 
            });
        }

        static async update(id: number, payload: { demo_name: string, shared_teams?: number[], demo_folder_id?: number | null }) {
            return await updateMutation.mutateAsync({
                url: `/api/demos/${id}/update`,
                payload
            }).then(() => {
                queryClient.invalidateQueries({ queryKey: ['demofolders'] });
                queryClient.invalidateQueries({ queryKey: ['demofolder', payload.demo_folder_id] });
            });
        }

        static async delete(id: number) {
            return await deleteMutation.mutateAsync(`/api/demos/${id}`);
        }

        static async refresh() {
            return await queryClient.invalidateQueries({ queryKey: queryKey });
        }
    }

    return {
        Demos,
        isCreating: createMutation.isPending,
        isUpdating: updateMutation.isPending,
        isDeleting: deleteMutation.isPending
    };
}