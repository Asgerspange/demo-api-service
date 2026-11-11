-- Stage 02 — map_metadata seed. GENERATED from map_metadata.sql by
-- scripts/gen_map_seed.py — do not edit by hand; re-run the generator instead.
-- 15 maps; `name` is the natural key. Idempotent (upsert on name).

INSERT INTO map_metadata (`map_id`, `name`, `display_name`, `is_active_duty`, `pos_x`, `pos_y`, `scale`, `rotate`, `zoom`, `selections`, `image_path`) VALUES
(0, 'ar_baggage', ' baggage', 0, -1316, 1288, 2.539062, 1, 1.3, '[{\"name\": \"default\", \"altitude_max\": 10000, \"altitude_min\": -5}, {\"name\": \"lower\", \"altitude_max\": -5, \"altitude_min\": -10000}]', '/images/maps/ar_baggage.png'),
(0, 'ar_shoots', ' shoots', 0, -1368, 1952, 2.6875, NULL, NULL, '[]', '/images/maps/ar_shoots.png'),
(0, 'cs_office', ' office', 0, -1838, 1858, 4.1, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/cs_office.png'),
(0, 'cs_italy', ' italy', 0, -2647, 2592, 4.6, 1, 1.5, '[]', 'https://csstrats.b-cdn.net/maps/cs_italy.png'),
(6, 'de_ancient', ' ancient', 1, -2953, 2164, 5, 0, 0, '[]', 'https://csstrats.b-cdn.net/maps/de_ancient.svg'),
(7, 'de_anubis', ' anubis', 1, -2796, 3328, 5.22, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_anubis.svg'),
(2, 'de_dust', ' dust', 0, -2850, 4073, 6, 1, 1.3, '[]', '/images/maps/de_dust.png'),
(2, 'de_dust2', ' dust2', 1, -2476, 3239, 4.4, 1, 1.1, '[]', 'https://csstrats.b-cdn.net/maps/de_dust2.svg'),
(3, 'de_inferno', ' inferno', 1, -2087, 3870, 4.9, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_inferno.svg'),
(1, 'de_mirage', ' mirage', 1, -3230, 1713, 5, 0, 0, '[]', 'https://csstrats.b-cdn.net/maps/de_mirage.svg'),
(8, 'de_train', ' train', 0, -2308, 2078, 4.082077, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_train.svg'),
(9, 'de_nuke', ' nuke', 1, -3453, 2887, 7, NULL, NULL, '[{\"name\": \"default\", \"altitude_max\": 10000, \"altitude_min\": -495}, {\"name\": \"lower\", \"altitude_max\": -495, \"altitude_min\": -10000}]', 'https://csstrats.b-cdn.net/maps/de_nuke.svg'),
(4, 'de_overpass', ' overpass', 1, -4831, 1781, 5.2, 0, 0, '[]', 'https://csstrats.b-cdn.net/maps/de_overpass.svg'),
(5, 'de_vertigo', ' vertigo', 0, -3168, 1762, 4, NULL, NULL, '[{\"name\": \"default\", \"altitude_max\": 20000, \"altitude_min\": 11700}, {\"name\": \"lower\", \"altitude_max\": 11700, \"altitude_min\": -10000}]', 'https://csstrats.b-cdn.net/maps/de_vertigo.svg'),
(10, 'de_cache', 'cache', 1, -2000, 3250, 5.5, 1, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_cache.png')
ON DUPLICATE KEY UPDATE `map_id`=VALUES(`map_id`), `display_name`=VALUES(`display_name`), `is_active_duty`=VALUES(`is_active_duty`), `pos_x`=VALUES(`pos_x`), `pos_y`=VALUES(`pos_y`), `scale`=VALUES(`scale`), `rotate`=VALUES(`rotate`), `zoom`=VALUES(`zoom`), `selections`=VALUES(`selections`), `image_path`=VALUES(`image_path`);
