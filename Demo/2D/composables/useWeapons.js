import { computed } from 'vue';
import useImages from '@/composables/useImages';

const WEAPON_ALIAS_MAP = {
  "high explosive grenade": "he-grenade", "he_grenade": "he-grenade",
  "smoke": "smoke-grenade", "smoke grenade": "smoke-grenade",
  "incendiary grenade": "incendiary-grenade", "dual berettas": "dual-berettas",
  "desert eagle": "desert-eagle", "galil ar": "galil-ar",
  "decoy": "decoy-grenade", "incendiary_grenade": "incendiary-grenade",
  "usp_silencer": "usp-s", "glock": "glock-18", "hkp2000": "p2000",
  "elite": "dual-berettas", "ssg 08": "ssg-08", "ssg08": "ssg-08",
  "scar 20": "scar-20", "fiveseven": "five-seven", "ak47": "ak-47",
  "galilar": "galil-ar", "mac10": "mac-10", "m4a1_silencer": "m4a1-s",
  "deagle": "desert-eagle", "tec9": "tec-9", "hegrenade": "he-grenade",
  "m4a1": "m4a1-s", "decoy grenade": "decoy-grenade", "ump45": "ump-45",
  "karambit": "knife_karambit", "butterfly knife": "knife_butterfly",
  "kukri knife": "knife_kukri", "ursus knife": "knife_ursus",
  "m9 bayonet": "knife_m9_bayonet", "navaja knife": "knife_gypsy_jackknife",
  "stiletto knife": "knife_stiletto", "flip knife": "knife_flip",
  "gut knife": "knife_gut", "shadow daggers": "knife_push",
  "survival knife": "knife_canis", "skeleton knife": "knife_skeleton",
  "paracord knife": "knife_cord", "talon knife": "knife_widowmaker",
  "nomad knife": "knife_outdoor", "zeus x27": "zeus",
  "c4 explosive": "c4", "cflashbang": "flashbang",
  "chegrenade": "he-grenade", "csmokegrenade": "smoke-grenade",
  "cincendiarygrenade": "incendiary-grenade", "cmolotovgrenade": "molotov",
  "csmokegrenadeprojectile": "smoke-grenade",
  "chegrenadeprojectile": "he-grenade", "cmolotovprojectile": "molotov",
  "cflashbangprojectile": "flashbang",
  "bowie knife": "knife_survival_bowie", "planted_c4": "c4",
  "huntsman knife": "knife_tactical", "classic knife": "knife_css",
  "r8 revolver": "r8-revolver",
};

export const UTILITIES = [
  'High Explosive Grenade', 'Smoke Grenade', 'Flashbang',
  'Decoy Grenade', 'Molotov', 'Incendiary Grenade', 'Zeus x27', 'Defuser',
];

export const PISTOLS = [
  'CZ75-Auto', 'Desert-Eagle', 'Dual-Berettas', 'Five-SeveN',
  'Glock-18', 'P2000', 'P250', 'R8-Revolver', 'Tec-9', 'USP-S',
];

export const WEAPON_CATEGORIES = {
  rifle:   ['ak-47','m4a4','m4a1-s','galil-ar','famas','aug','sg-553'],
  sniper:  ['awp','ssg-08','scar-20','g3sg1'],
  smg:     ['mp9','mac-10','mp7','ump-45','p90','pp-bizon','mp5-sd'],
  pistol:  ['glock-18','usp-s','p2000','p250','five-seven','tec-9','cz75-auto','desert-eagle','r8-revolver','dual-berettas'],
};

// FIX: A perfectly stable empty fallback object guarantees Vue's virtual DOM
// identity checks (===) succeed across frames, stopping repeated `<img src>` re-renders.
const EMPTY_WEAPON = { url: '', svg_path: '' };

export function useWeapons() {
  const { Images } = useImages();
  const { data: weaponImages } = Images.get('weapon');

  // Computed dictionary is far faster and more reactive than a manual Map cache
  const weaponMap = computed(() => {
    const map = {};
    if (weaponImages.value) {
      for (const w of weaponImages.value) {
        map[w.name.toLowerCase()] = w;
      }
    }
    return map;
  });

  function getWeapon(name) {
    if (!name) return EMPTY_WEAPON;
    const normalised = (WEAPON_ALIAS_MAP[name.toLowerCase()] ?? name.toLowerCase());
    return weaponMap.value[normalised] ?? EMPTY_WEAPON;
  }

  function getStashedWeapon(player) {
    let stashed = player.inventory.filter(item =>
      !UTILITIES.includes(item) &&
      item !== player.active_weapon_name &&
      !item.toLowerCase().includes('knife') &&
      item.toLowerCase() !== 'bayonet' &&
      item.toLowerCase() !== 'c4'
    );
    if (stashed.length > 1) stashed = stashed.filter(item => !PISTOLS.includes(item));
    return stashed[0];
  }

  function getUtilityItems(player) {
    return [
      ...(player.has_defuser ? ['Defuser'] : []),
      ...player.inventory.filter(i => UTILITIES.includes(i)).sort(),
    ];
  }

  function checkWeaponFilter(weaponName, filter) {
    if (!filter) return true;
    const norm = weaponName.toLowerCase().replace(/_/g, '-');
    if (WEAPON_CATEGORIES[filter]) {
      return WEAPON_CATEGORIES[filter].some(w => norm.includes(w) || w.includes(norm));
    }
    return norm.includes(filter) || filter.includes(norm);
  }

  return { getWeapon, getStashedWeapon, getUtilityItems, checkWeaponFilter };
}