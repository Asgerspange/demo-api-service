/**
 * useDemo
 * Fetches and exposes top-level demo metadata: map info, round list, icons.
 * Accepts an `externalId` ref so it works for both the primary demo and any
 * additional demos loaded for comparison.
 */
import { computed } from 'vue';
import useDemos from '@/composables/useDemos';
import useImages from '@/composables/useImages';

export function useDemo(externalId) {
  const { Demos } = useDemos();
  const { Images } = useImages();

  const { data: demo, isSuccess } = Demos.show(externalId);

  const demoId       = computed(() => demo.value?.id);
  const map          = computed(() => demo.value?.map || 'unknown_map');
  const mapMetadata  = computed(() => demo.value?.map_metadata ?? null);
  const demoRounds   = computed(() => demo.value?.rounds || []);
  const version      = computed(() => demo.value?.version || 1.0);

  // Icon sprites (headshot, blind kill, etc.)
  const { data: iconData } = Images.get('demo_icon');
  const demoIcons = computed(() =>
    Object.fromEntries((iconData.value || []).map(icon => [icon.name, icon]))
  );

  return { demo, isSuccess, demoId, map, mapMetadata, demoRounds, version, demoIcons };
}