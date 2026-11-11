import { useApi } from '@/composables/useApi';

export default function useImages() {
    const { useGet } = useApi();

    class Images {
        static get(group: string) {
            return useGet<any[]>(
                ['images', group], 
                `/api/images`, 
                { group }
            );
        }
    }

    return {
        Images
    };
}