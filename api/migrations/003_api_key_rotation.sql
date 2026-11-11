-- Stage 03 — key rotation grace window.
-- `expires_at` lets a rotated key stay valid for a grace period: rotation issues a new key
-- and stamps the old one with expires_at = now + grace (status stays 'active' until then).
-- Revocation is immediate (status='revoked'). A key authenticates only while
-- status='active' AND (expires_at IS NULL OR expires_at > now).
ALTER TABLE api_keys
  ADD COLUMN expires_at TIMESTAMP NULL AFTER revoked_at,
  ADD COLUMN rotated_to BIGINT UNSIGNED NULL AFTER expires_at;  -- id of the replacement key
