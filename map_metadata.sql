-- phpMyAdmin SQL Dump
-- version 5.2.3
-- https://www.phpmyadmin.net/
--
-- Vært: percona_db
-- Genereringstid: 09. 06 2026 kl. 07:38:39
-- Serverversion: 8.0.45-36
-- PHP-version: 8.3.26

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `csstrats`
--

-- --------------------------------------------------------

--
-- Struktur-dump for tabellen `map_metadata`
--

CREATE TABLE `map_metadata` (
  `id` bigint UNSIGNED NOT NULL,
  `map_id` int NOT NULL,
  `display_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active_duty` tinyint(1) NOT NULL DEFAULT '0',
  `pos_x` double NOT NULL,
  `pos_y` double NOT NULL,
  `scale` double NOT NULL,
  `rotate` double DEFAULT NULL,
  `zoom` double DEFAULT NULL,
  `selections` json DEFAULT NULL,
  `image_path` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Data dump for tabellen `map_metadata`
--

INSERT INTO `map_metadata` (`id`, `map_id`, `display_name`, `name`, `is_active_duty`, `pos_x`, `pos_y`, `scale`, `rotate`, `zoom`, `selections`, `image_path`, `created_at`, `updated_at`) VALUES
(1, 0, ' baggage', 'ar_baggage', 0, -1316, 1288, 2.539062, 1, 1.3, '[{\"name\": \"default\", \"altitude_max\": 10000, \"altitude_min\": -5}, {\"name\": \"lower\", \"altitude_max\": -5, \"altitude_min\": -10000}]', '/images/maps/ar_baggage.png', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(2, 0, ' shoots', 'ar_shoots', 0, -1368, 1952, 2.6875, NULL, NULL, '[]', '/images/maps/ar_shoots.png', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(3, 0, ' office', 'cs_office', 0, -1838, 1858, 4.1, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/cs_office.png', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(4, 0, ' italy', 'cs_italy', 0, -2647, 2592, 4.6, 1, 1.5, '[]', 'https://csstrats.b-cdn.net/maps/cs_italy.png', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(5, 6, ' ancient', 'de_ancient', 1, -2953, 2164, 5, 0, 0, '[]', 'https://csstrats.b-cdn.net/maps/de_ancient.svg', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(6, 7, ' anubis', 'de_anubis', 1, -2796, 3328, 5.22, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_anubis.svg', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(7, 2, ' dust', 'de_dust', 0, -2850, 4073, 6, 1, 1.3, '[]', '/images/maps/de_dust.png', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(8, 2, ' dust2', 'de_dust2', 1, -2476, 3239, 4.4, 1, 1.1, '[]', 'https://csstrats.b-cdn.net/maps/de_dust2.svg', '2026-03-26 09:42:39', '2026-03-26 09:42:39'),
(9, 3, ' inferno', 'de_inferno', 1, -2087, 3870, 4.9, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_inferno.svg', '2026-03-26 09:42:40', '2026-03-26 09:42:40'),
(10, 1, ' mirage', 'de_mirage', 1, -3230, 1713, 5, 0, 0, '[]', 'https://csstrats.b-cdn.net/maps/de_mirage.svg', '2026-03-26 09:42:40', '2026-03-26 09:42:40'),
(11, 8, ' train', 'de_train', 0, -2308, 2078, 4.082077, NULL, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_train.svg', '2026-03-26 09:42:40', '2026-03-26 09:42:40'),
(12, 9, ' nuke', 'de_nuke', 1, -3453, 2887, 7, NULL, NULL, '[{\"name\": \"default\", \"altitude_max\": 10000, \"altitude_min\": -495}, {\"name\": \"lower\", \"altitude_max\": -495, \"altitude_min\": -10000}]', 'https://csstrats.b-cdn.net/maps/de_nuke.svg', '2026-03-26 09:42:40', '2026-03-26 09:42:40'),
(13, 4, ' overpass', 'de_overpass', 1, -4831, 1781, 5.2, 0, 0, '[]', 'https://csstrats.b-cdn.net/maps/de_overpass.svg', '2026-03-26 09:42:40', '2026-03-26 09:42:40'),
(14, 5, ' vertigo', 'de_vertigo', 0, -3168, 1762, 4, NULL, NULL, '[{\"name\": \"default\", \"altitude_max\": 20000, \"altitude_min\": 11700}, {\"name\": \"lower\", \"altitude_max\": 11700, \"altitude_min\": -10000}]', 'https://csstrats.b-cdn.net/maps/de_vertigo.svg', '2026-03-26 09:42:40', '2026-03-26 09:42:40'),
(16, 10, 'cache', 'de_cache', 1, -2000, 3250, 5.5, 1, NULL, '[]', 'https://csstrats.b-cdn.net/maps/de_cache.png', '2026-03-26 09:42:39', '2026-03-26 09:42:39');

--
-- Begrænsninger for dumpede tabeller
--

--
-- Indeks for tabel `map_metadata`
--
ALTER TABLE `map_metadata`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `map_metadata_name_unique` (`name`);

--
-- Brug ikke AUTO_INCREMENT for slettede tabeller
--

--
-- Tilføj AUTO_INCREMENT i tabel `map_metadata`
--
ALTER TABLE `map_metadata`
  MODIFY `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=17;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
