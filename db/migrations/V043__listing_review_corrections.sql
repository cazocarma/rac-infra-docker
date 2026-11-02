-- P08: authenticated correction/rejection commands, not publication approval.
-- No catalog is seeded or activated: D04/D06 remain human decisions.
SET LOCAL lock_timeout='2s';

-- Deferred constraints fire at COMMIT, after a scoped SECURITY DEFINER command
-- has returned to its function-only caller. Their invariant queries therefore
-- need their owner's authority too; never grant raw SELECT to the API instead.
-- Both remain trigger-only, with PUBLIC execution revoked since V041.
ALTER FUNCTION public.check_listing_pointers() SECURITY DEFINER;
ALTER FUNCTION public.check_listing_pointers() SET search_path=pg_catalog;
ALTER FUNCTION public.check_listing_decision_pointer() SECURITY DEFINER;
ALTER FUNCTION public.check_listing_decision_pointer() SET search_path=pg_catalog;

CREATE TABLE listing_review.reason_catalogs (
 version text PRIMARY KEY CHECK(version ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 reviewed_by audit.reference NOT NULL,
 reviewed_at timestamptz NOT NULL CHECK(isfinite(reviewed_at))
);
CREATE TABLE listing_review.reasons (
 catalog_version text NOT NULL REFERENCES listing_review.reason_catalogs(version) DEFERRABLE INITIALLY DEFERRED,
 code text NOT NULL CHECK(code ~ '^[a-z][a-z0-9_]{1,63}$'),
 action text NOT NULL CHECK(action IN('rejected','changes_requested')),
 message_key text NOT NULL CHECK(message_key ~ '^[A-Za-z][A-Za-z0-9]{0,95}$'),
 PRIMARY KEY(catalog_version,code,action)
);
CREATE TABLE listing_review.reason_head (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 catalog_version text NOT NULL REFERENCES listing_review.reason_catalogs(version),
 version bigint NOT NULL CHECK(version>0)
);
-- Only the owner may install a reviewed catalog/head. The reviewer credential
-- has no DML, no activation entrypoint and cannot invent a reason at runtime.
CREATE TRIGGER listing_reason_catalog_immutable BEFORE UPDATE OR DELETE ON listing_review.reason_catalogs
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();
CREATE TRIGGER listing_reason_immutable BEFORE UPDATE OR DELETE ON listing_review.reasons
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();
-- Load definitions first, then seal by inserting their reviewed catalog in the
-- same transaction. A sealed version cannot acquire new definitions later.
CREATE FUNCTION listing_review.guard_reason_insert() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.reason:'||NEW.catalog_version,0));
 IF EXISTS(SELECT FROM listing_review.reason_catalogs WHERE version=NEW.catalog_version) THEN
  RAISE EXCEPTION 'Listing reason catalog is sealed' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER listing_reason_insert_guard BEFORE INSERT ON listing_review.reasons
 FOR EACH ROW EXECUTE FUNCTION listing_review.guard_reason_insert();
CREATE FUNCTION listing_review.guard_catalog_seal() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.reason:'||NEW.version,0));
 RETURN NEW;
END $$;
CREATE TRIGGER listing_reason_catalog_seal BEFORE INSERT ON listing_review.reason_catalogs
 FOR EACH ROW EXECUTE FUNCTION listing_review.guard_catalog_seal();

ALTER TABLE public.listing_revision_decisions
 ADD COLUMN reason_catalog_version text REFERENCES listing_review.reason_catalogs(version);
-- NULL identifies pre-V043 structural fixtures/legacy decisions, never an
-- implicit attribution to a new reason catalog.

CREATE TABLE listing_review.decision_events (
 event_id audit.reference PRIMARY KEY,
 revision_id uuid NOT NULL UNIQUE REFERENCES public.listing_revision_decisions(revision_id),
 human_actor audit.reference NOT NULL,
 database_role name NOT NULL,
 policy_version audit.reference NOT NULL,
 command jsonb NOT NULL CHECK(jsonb_typeof(command)='object'),
 result jsonb NOT NULL CHECK(jsonb_typeof(result)='object'),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(occurred_at))
);
CREATE TRIGGER listing_decision_event_immutable BEFORE UPDATE OR DELETE ON listing_review.decision_events
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();

-- Durable, minimal delivery intent. No emails/push/RabbitMQ producer is enabled
-- by this migration. A future authorized worker must deliver idempotently.
CREATE TABLE listing_review.outbox (
 event_id audit.reference PRIMARY KEY REFERENCES listing_review.decision_events(event_id),
 recipient_user_id uuid NOT NULL REFERENCES public.usuario(id),
 kind text NOT NULL CHECK(kind='listing.reviewed.v1'),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at))
);
CREATE TRIGGER listing_review_outbox_immutable BEFORE UPDATE OR DELETE ON listing_review.outbox
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();

CREATE FUNCTION listing_review.correction_ready() RETURNS boolean
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT listing_review.ready() AND EXISTS(
  SELECT FROM listing_review.reason_head h JOIN listing_review.reason_catalogs c ON c.version=h.catalog_version
  WHERE h.singleton AND c.reviewed_at<=clock_timestamp()
   AND EXISTS(SELECT FROM listing_review.reasons r WHERE r.catalog_version=c.version)
 )
$$;

CREATE FUNCTION listing_review.correct(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_action text,p_catalog text,p_reason text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 prior listing_review.decision_events%ROWTYPE;
 listing public.listings%ROWTYPE;
 revision public.listing_revisions%ROWTYPE;
 owner_id uuid; owner_subject text; effective_catalog text; reason_key text;
 command jsonb; result jsonb; note_key text;
BEGIN
 IF NOT listing_review.ready() THEN
  RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501';
 END IF;
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_revision IS NULL
 OR p_expected IS NULL OR p_expected<0 OR p_expected=9223372036854775807
 OR p_hash IS NULL OR p_action IS NULL OR p_action NOT IN('rejected','changes_requested')
 OR p_catalog IS NULL OR p_catalog !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'
 OR p_reason IS NULL OR p_reason !~ '^[a-z][a-z0-9_]{1,63}$' THEN
  RAISE EXCEPTION 'invalid_listing_review_command' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('revision_id',p_revision,'expected_version',p_expected::text,
  'sha256',p_hash,'decision',p_action,'reason_catalog_version',p_catalog,'reason_code',p_reason);
 -- Serialize retries before checking mutable state. Hash collisions only cause
 -- extra serialization; event identity and command equality are checked below.
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.review:'||p_event::text,0));
 SELECT * INTO prior FROM listing_review.decision_events WHERE event_id=p_event;
 IF FOUND THEN
  IF prior.human_actor<>p_actor OR prior.database_role<>session_user
   OR prior.policy_version<>p_policy OR prior.command<>command THEN
   RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
  END IF;
  RETURN prior.result;
 END IF;
 -- Hold the registry lease through commit. A stale screen cannot silently use
 -- a newer definition of its reason code.
 SELECT h.catalog_version INTO effective_catalog FROM listing_review.reason_head h
 JOIN listing_review.reason_catalogs c ON c.version=h.catalog_version
 WHERE h.singleton AND c.reviewed_at<=clock_timestamp()
  AND EXISTS(SELECT FROM listing_review.reasons r WHERE r.catalog_version=c.version)
 FOR SHARE OF h;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'listing_reasons_unavailable' USING ERRCODE='55000';
 END IF;
 IF effective_catalog<>p_catalog THEN
  RAISE EXCEPTION 'listing_reason_catalog_conflict' USING ERRCODE='40001';
 END IF;
 SELECT r.message_key INTO reason_key FROM listing_review.reasons r
 WHERE r.catalog_version=p_catalog AND r.code=p_reason AND r.action=p_action;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'invalid_listing_review_reason' USING ERRCODE='22023';
 END IF;
 SELECT * INTO revision FROM public.listing_revisions WHERE id=p_revision;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'listing_revision_not_found' USING ERRCODE='P0002';
 END IF;
 SELECT * INTO STRICT listing FROM public.listings WHERE id=revision.listing_id FOR NO KEY UPDATE;
 IF listing.version<>p_expected OR listing.pending_revision_id IS DISTINCT FROM p_revision
  OR encode(revision.payload_hash,'hex')<>p_hash THEN
  RAISE EXCEPTION 'listing_revision_conflict' USING ERRCODE='40001';
 END IF;
 SELECT u.id,u.keycloak_id INTO STRICT owner_id,owner_subject FROM public.compa_perfil cp
 JOIN public.usuario u ON u.id=cp.usuario_id WHERE cp.id=listing.compa_id FOR KEY SHARE OF cp,u;
 IF lower(owner_subject)=p_actor::text THEN
  RAISE EXCEPTION 'listing_self_review' USING ERRCODE='42501';
 END IF;
 note_key:=CASE p_action WHEN 'rejected' THEN 'listingRejected' ELSE 'listingChangesRequested' END;
 INSERT INTO public.listing_revision_decisions
 (revision_id,action,reviewer_subject,reason_code,note_to_user_key,reason_catalog_version)
 VALUES(p_revision,p_action,p_actor::text,p_reason,note_key,p_catalog);
 -- Both negative decisions preserve the last approved revision/state.
 UPDATE public.listings SET pending_revision_id=NULL,version=version+1 WHERE id=listing.id;
 result:=jsonb_build_object('event_id',p_event,'revision_id',p_revision,'listing_id',listing.id,
  'listing_version',(p_expected+1)::text,'decision',p_action,'reason_catalog_version',p_catalog,
  'reason_code',p_reason,'reason_message_key',reason_key,'note_to_user_key',note_key);
 INSERT INTO listing_review.decision_events
 (event_id,revision_id,human_actor,database_role,policy_version,command,result)
 VALUES(p_event,p_revision,p_actor,session_user,p_policy,command,result);
 INSERT INTO listing_review.outbox(event_id,recipient_user_id,kind,payload)
 VALUES(p_event,owner_id,'listing.reviewed.v1',result);
 -- Existing audit vocabulary: service principal + correlated delegated actor.
 -- This is not an external WORM proof of the entire command or private content.
 PERFORM audit.append(p_event,'listing.reviewed',p_revision,'case_review',p_policy);
 RETURN result;
END $$;

REVOKE ALL ON listing_review.reason_catalogs,listing_review.reasons,listing_review.reason_head,
 listing_review.decision_events,listing_review.outbox FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.correct(audit.reference,audit.reference,audit.reference,
 audit.reference,bigint,audit.digest,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.guard_reason_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.guard_catalog_seal() FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.correction_ready() FROM PUBLIC;
-- rac_user and reader-only logins receive no correction authority automatically.
