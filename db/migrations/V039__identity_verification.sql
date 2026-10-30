-- P05/M2. Email verification and identity verification are different facts:
-- the legacy column only mirrored the OIDC email_verified claim. Coordinated
-- cutover without a permanent alias; user-service writes the new name.
SET LOCAL lock_timeout = '2s';
ALTER TABLE public.usuario RENAME COLUMN verificado TO email_verified;

-- Identity results from an external provider. No document image, document
-- number or birth date is stored: the fingerprint is an HMAC (by key_id) of the
-- provider's stable opaque identity identifier, and only the adult result is kept.
CREATE TABLE public.identity_verifications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES public.usuario(id),
 provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_-]{0,31}$'),
 provider_ref text NOT NULL CHECK (provider_ref ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$'),
 purpose text NOT NULL CHECK (purpose IN ('compa_onboarding','client_booking')),
 status text NOT NULL DEFAULT 'pending'
  CHECK (status IN ('pending','approved','rejected','expired','needs_review')),
 is_adult boolean,
 document_country char(2) CHECK (document_country ~ '^[A-Z]{2}$'),
 document_fingerprint bytea CHECK (octet_length(document_fingerprint) = 32),
 fingerprint_key_id text CHECK (fingerprint_key_id ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
 decided_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 UNIQUE (provider, provider_ref),
 CONSTRAINT identity_fingerprint_complete
  CHECK (num_nonnulls(document_fingerprint, fingerprint_key_id) IN (0, 2)),
 CONSTRAINT identity_decision_time
  CHECK ((status = 'pending') = (decided_at IS NULL)),
 -- An approval always means a provider-backed adult with a fingerprint.
 CONSTRAINT identity_approved_adult
  CHECK (status <> 'approved' OR (is_adult IS TRUE AND document_fingerprint IS NOT NULL AND document_country IS NOT NULL))
);
CREATE UNIQUE INDEX identity_verifications_one_pending
 ON public.identity_verifications (user_id, purpose) WHERE status = 'pending';
CREATE INDEX identity_verifications_user ON public.identity_verifications (user_id, created_at DESC);
CREATE INDEX identity_verifications_fingerprint
 ON public.identity_verifications (fingerprint_key_id, document_fingerprint)
 WHERE document_fingerprint IS NOT NULL;

-- Fingerprints withheld after a confirmed evasion case. A match never bans a
-- new person automatically: the verification goes to review (D12 pending).
CREATE TABLE public.banned_identity_fingerprints (
 fingerprint bytea NOT NULL CHECK (octet_length(fingerprint) = 32),
 key_id text NOT NULL CHECK (key_id ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
 case_id uuid,
 created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 PRIMARY KEY (key_id, fingerprint)
);

-- Signed webhook event ids, kept only to reject replays. No payload is stored.
CREATE TABLE public.identity_webhook_events (
 provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_-]{0,31}$'),
 event_id text NOT NULL CHECK (event_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$'),
 received_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 PRIMARY KEY (provider, event_id)
);

-- User owns identity state. No DELETE: erasure is a separate, audited saga (P12).
-- Bans are written by the trust & safety owner, never by the verification flow.
GRANT SELECT, INSERT ON public.identity_verifications TO rac_user;
GRANT UPDATE (status, is_adult, document_country, document_fingerprint, fingerprint_key_id, decided_at, updated_at)
 ON public.identity_verifications TO rac_user;
GRANT SELECT ON public.banned_identity_fingerprints TO rac_user;
GRANT INSERT ON public.identity_webhook_events TO rac_user;
