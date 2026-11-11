const scales = {
    ar_baggage: {
        pos_x: -1316,
        pos_y: 1288,
        scale: 2.539062,
        rotate: 1,
        zoom: 1.3,
        selections: [
            { name: "default", altitude_max: 10000, altitude_min: -5 },
            { name: "lower", altitude_max: -5, altitude_min: -10000 },
        ],
    },
    ar_shoots: {
        pos_x: -1368,
        pos_y: 1952,
        scale: 2.6875,
        rotate: null,
        zoom: null,
        selections: [],
    },
    cs_office: {
        pos_x: -1838,
        pos_y: 1858,
        scale: 4.1,
        rotate: null,
        zoom: null,
        selections: [],
    },
    cs_italy: {
        pos_x: -2647,
        pos_y: 2592,
        scale: 4.6,
        rotate: 1,
        zoom: 1.5,
        selections: [],
    },
    de_ancient: {
        pos_x: -2953,
        pos_y: 2164,
        scale: 5,
        rotate: 0,
        zoom: 0,
        selections: [],
    },
    de_anubis: {
        pos_x: -2796,
        pos_y: 3328,
        scale: 5.22,
        rotate: null,
        zoom: null,
        selections: [],
    },
    de_dust: {
        pos_x: -2850,
        pos_y: 4073,
        scale: 6,
        rotate: 1,
        zoom: 1.3,
        selections: [],
    },
    de_dust2: {
        pos_x: -2476,
        pos_y: 3239,
        scale: 4.4,
        rotate: 1,
        zoom: 1.1,
        selections: [],
    },
    de_inferno: {
        pos_x: -2087,
        pos_y: 3870,
        scale: 4.9,
        rotate: null,
        zoom: null,
        selections: [],
    },
    de_cache: {
        pos_x: -2000,
        pos_y: 3250,
        scale: 5.5,
        rotate: 1,
        zoom: null,
        selections: [],
    },
    de_inferno_s2: {
        pos_x: -2087,
        pos_y: 3870,
        scale: 4.9,
        rotate: null,
        zoom: null,
        selections: [],
    },
    de_mirage: {
        pos_x: -3230,
        pos_y: 1713,
        scale: 5,
        rotate: 0,
        zoom: 0,
        selections: [],
    },
    de_train: {
        pos_x: -2308,
        pos_y: 2078,
        scale: 4.082077,
    },
    de_nuke: {
        pos_x: -3453,
        pos_y: 2887,
        scale: 7,
        rotate: null,
        zoom: null,
        selections: [
            { name: "default", altitude_max: 10000, altitude_min: -495 },
            { name: "lower", altitude_max: -495, altitude_min: -10000 },
        ],
    },
    de_overpass: {
        pos_x: -4831,
        pos_y: 1781,
        scale: 5.2,
        rotate: 0,
        zoom: 0,
        selections: [],
    },
    de_vertigo: {
        pos_x: -3168,
        pos_y: 1762,
        scale: 4,
        rotate: null,
        zoom: null,
        selections: [
            { name: "default", altitude_max: 20000, altitude_min: 11700 },
            { name: "lower", altitude_max: 11700, altitude_min: -10000 },
        ],
    },
};

function getScale(key) {
    return (
        scales[key] || {
            pos_x: 0,
            pos_y: 0,
            scale: 1,
        }
    );
}

export default getScale;
